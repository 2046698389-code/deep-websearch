"""Structured search APIs, with no scraping or implicit credential acquisition.

Primary API contracts checked 2026-10-04:
Brave: https://api-dashboard.search.brave.com/api-reference/web/search/get
SearXNG: https://docs.searxng.org/dev/search_api.html
Exa: https://exa.ai/docs/reference/search
Tavily: https://docs.tavily.com/documentation/api-reference/endpoint/search
Serper: https://serper.dev/ and its public playground code generator
SerpAPI: https://serpapi.com/search-api

See docs/provider-web.md for response mapping and intentional limits. In
particular, provider keys and request URLs are never copied into result metadata.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from ..config import Settings
from ..http import HttpClient
from ..models import SearchResult, SourceState, SourceStatus
from .base import AdapterError, BaseAdapter


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _http_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return ""
        if parsed.username or parsed.password:
            return ""
        _ = parsed.port  # Invalid ports should be treated as malformed rows.
    except ValueError:
        return ""
    return value


class _WebAdapter(BaseAdapter):
    """Small shared parser; provider rows remain untrusted input."""

    @property
    def options(self) -> dict[str, Any]:
        return self.settings.sources[self.name].options

    def _ready(self, query: str, limit: int) -> bool:
        status = self.availability()
        if status.status != SourceState.enabled:
            raise AdapterError(status.status, status.reason)
        return bool(query.strip()) and limit > 0

    def _options(self, *names: str) -> dict[str, Any]:
        return {name: self.options[name] for name in names if self.options.get(name) is not None}

    def _check_error(self, payload: dict[str, Any]) -> None:
        error = payload.get("error")
        metadata = payload.get("search_metadata")
        if not error and not (
            isinstance(metadata, dict) and metadata.get("status") == "Error"
        ):
            return
        # Inspect text only for classification; never expose an upstream error
        # which may echo a query-string API key or other credentials.
        detail = str(error).lower()
        if any(word in detail for word in ("quota", "credit", "exhausted", "limit exceeded", "insufficient")):
            state = SourceState.quota_exhausted
            reason = "Provider search quota is exhausted."
        elif any(word in detail for word in ("rate", "too many requests")):
            state = SourceState.rate_limited
            reason = "Provider rate limit reached."
        elif any(word in detail for word in ("api key", "api_key", "authentication", "unauthorized", "token")):
            state = SourceState.unavailable
            reason = "Provider rejected the configured credential."
        else:
            state = SourceState.error
            reason = "Provider returned an API error."
        raise AdapterError(state, reason)

    def _result(
        self,
        query: str,
        row: dict[str, Any],
        *,
        url_field: str = "url",
        snippet_field: str = "snippet",
        date_field: str = "published_at",
        snippet: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> SearchResult | None:
        url = _http_url(row.get(url_field))
        title = self.clean(_text(row.get("title")))
        if not url or not title:
            return None
        metadata = {
            key: row[key]
            for key in ("score", "position", "engine", "engines", "category")
            if isinstance(row.get(key), (str, int, float, list))
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        try:
            return SearchResult(
                source=self.name,
                query=query,
                title=title,
                url=url,
                snippet=self.clean(_text(row.get(snippet_field)) if snippet is None else snippet),
                published_at=_text(row.get(date_field)) or None,
                author=_text(row.get("author")) or None,
                metadata=metadata,
                provenance=[{"source": self.name, "query": query, "url": url}],
            )
        except (ValidationError, ValueError, TypeError):
            return None

    def _parse(
        self, query: str, rows: Any, limit: int, **mapping: Any
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for row in _rows(rows):
            result = self._result(query, row, **mapping)
            if result is not None:
                results.append(result)
                if len(results) >= limit:
                    break
        return results


class BraveAdapter(_WebAdapter):
    name = "brave"
    required_env = ("BRAVE_SEARCH_API_KEY",)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        params = {
            **self._options("country", "search_lang", "ui_lang", "safesearch", "freshness"),
            "q": query,
            "count": min(limit, 20),
            "text_decorations": "false",
            "result_filter": "web",
        }
        payload = await self.http.request_json(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers={"X-Subscription-Token": self.settings.env["BRAVE_SEARCH_API_KEY"]},
        )
        self._check_error(payload)
        web = payload.get("web")
        rows = web.get("results") if isinstance(web, dict) else []
        return self._parse(query, rows, limit, snippet_field="description", date_field="page_age")


class SearxngAdapter(_WebAdapter):
    name = "searxng"
    required_env = ("SEARXNG_URL",)

    def availability(self) -> SourceStatus:
        status = super().availability()
        if status.status == SourceState.enabled and not _http_url(self.settings.env.get("SEARXNG_URL")):
            return SourceStatus(
                source=self.name,
                status=SourceState.unavailable,
                reason="SEARXNG_URL must be an absolute HTTP or HTTPS instance URL without embedded credentials.",
            )
        return status

    def _endpoint(self) -> str:
        # The environment URL is an explicitly configured trusted backend. A
        # self-hosted localhost/private instance is supported without an extra
        # public-only URL policy intended for arbitrary fetch_page requests.
        base = urlsplit(self.settings.env["SEARXNG_URL"].strip())
        path = base.path.rstrip("/")
        if not path.endswith("/search"):
            path += "/search"
        return urlunsplit((base.scheme, base.netloc, path, "", ""))

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        params = {
            **self._options("engines", "categories", "language", "safesearch", "time_range"),
            "q": query,
            "format": "json",
        }
        payload = await self.http.request_json("GET", self._endpoint(), params=params)
        self._check_error(payload)
        return self._parse(query, payload.get("results"), limit, snippet_field="content", date_field="publishedDate")


class ExaAdapter(_WebAdapter):
    name = "exa"
    required_env = ("EXA_API_KEY",)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        body = {
            "type": "auto",
            **self._options(
                "type", "category", "includeDomains", "excludeDomains", "startPublishedDate", "endPublishedDate"
            ),
            "query": query,
            "numResults": min(limit, 100),
        }
        # Content extraction may incur an additional provider charge. It is
        # opt-in; the normal search does not silently add content requests.
        if self.options.get("include_highlights") is True:
            body["contents"] = {"highlights": True}
        payload = await self.http.request_json(
            "POST", "https://api.exa.ai/search", json=body,
            headers={"x-api-key": self.settings.env["EXA_API_KEY"]},
        )
        self._check_error(payload)
        results: list[SearchResult] = []
        for row in _rows(payload.get("results")):
            highlights = row.get("highlights")
            snippet = _text(row.get("summary")) or _text(row.get("text"))
            if not snippet and isinstance(highlights, list):
                snippet = " ".join(_text(value) for value in highlights if isinstance(value, str))
            result = self._result(query, row, snippet=snippet, date_field="publishedDate")
            if result is not None:
                results.append(result)
                if len(results) >= limit:
                    break
        return results


class TavilyAdapter(_WebAdapter):
    name = "tavily"
    required_env = ("TAVILY_API_KEY",)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        body = {
            "search_depth": "basic",
            **self._options("search_depth", "topic", "time_range", "include_domains", "exclude_domains", "country", "language"),
            "query": query,
            "max_results": min(limit, 20),
            "include_answer": False,
            "include_raw_content": False,
            "auto_parameters": False,
        }
        payload = await self.http.request_json(
            "POST", "https://api.tavily.com/search", json=body,
            headers={"Authorization": f"Bearer {self.settings.env['TAVILY_API_KEY']}"},
        )
        self._check_error(payload)
        return self._parse(query, payload.get("results"), limit, snippet_field="content", date_field="published_date")


class SerperAdapter(_WebAdapter):
    name = "serper"
    required_env = ("SERPER_API_KEY",)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        body = {**self._options("gl", "hl", "location", "tbs"), "q": query, "num": min(limit, 100)}
        payload = await self.http.request_json(
            "POST", "https://google.serper.dev/search", json=body,
            headers={"X-API-KEY": self.settings.env["SERPER_API_KEY"]},
        )
        self._check_error(payload)
        return self._parse(query, payload.get("organic"), limit, url_field="link", date_field="date")


class SerpapiAdapter(_WebAdapter):
    name = "serpapi"
    required_env = ("SERPAPI_API_KEY",)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._ready(query, limit):
            return []
        # Current Google API docs no longer advertise the old `num` parameter.
        # Retrieve one page and truncate locally; never promise exact counts.
        params = {
            **self._options("gl", "hl", "location", "safe", "tbs", "google_domain"),
            "engine": "google",
            "q": query,
            "api_key": self.settings.env["SERPAPI_API_KEY"],
        }
        payload = await self.http.request_json("GET", "https://serpapi.com/search.json", params=params)
        self._check_error(payload)
        return self._parse(query, payload.get("organic_results"), limit, url_field="link", date_field="date")


def build_web_adapters(settings: Settings, http: HttpClient) -> dict[str, BaseAdapter]:
    return {
        adapter.name: adapter(settings, http)
        for adapter in (BraveAdapter, SearxngAdapter, ExaAdapter, TavilyAdapter, SerperAdapter, SerpapiAdapter)
    }
