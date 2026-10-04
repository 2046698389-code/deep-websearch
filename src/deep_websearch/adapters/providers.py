"""Read-only platform search through the user's TikOmni or TikHub account.

Contracts: docs.tikomni.com and TikHub/TikHub-API-Python-SDK, checked 2026-10-05.
Only fixed documented search routes are allowed; no user-supplied credential destinations.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

from ..config import CREDENTIAL_ALIASES
from ..models import AdapterError, SearchResult, SourceState, SourceStatus
from .base import BaseAdapter

ROUTES = {
    "youtube": ("GET", "youtube/web_v2/get_general_search_v2"),
    "reddit": ("GET", "reddit/app/fetch_dynamic_search"),
    "x": ("GET", "twitter/web/fetch_search_timeline"),
    "douyin": ("POST", "douyin/search/fetch_video_search_v2"),
    "bilibili": ("GET", "bilibili/app/fetch_search_by_type"),
}
BASES = {"tikomni": "https://api.tikomni.com/api/u1/v1/", "tikhub": "https://api.tikhub.io/api/v1/"}


def provider_key(env: dict[str, str], provider: str) -> str:
    canonical = "TIKOMNI_API_KEY" if provider == "tikomni" else "TIKHUB_API_KEY"
    for name in (canonical, *CREDENTIAL_ALIASES[canonical]):
        value = env.get(name, "").strip()
        if value:
            return value[7:].strip() if value.lower().startswith("bearer ") else value
    return ""


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("simpleText") or value.get("name")) or " ".join(
            _text(x) for x in value.get("runs", []) if isinstance(x, dict))
    return ""


def _walk(value: Any, depth: int = 0) -> Iterator[dict]:
    # Raw Twitter GraphQL, Reddit edges, and video responses have nested records.
    if depth > 18:
        return
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key not in {"author", "user", "core", "thumbnails", "video", "music", "statistics"}:
                yield from _walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value[:1000]:
            yield from _walk(child, depth + 1)


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return ""


class ProviderAdapter(BaseAdapter):
    def __init__(self, settings, http, platform: str, provider: str):
        super().__init__(settings, http)
        self.name = platform
        self.provider = provider
        self.required_env = ("TIKOMNI_API_KEY" if provider == "tikomni" else "TIKHUB_API_KEY",)

    def availability(self):
        if self.settings.sources[self.name].enabled is False:
            return SourceStatus(source=self.name, status=SourceState.unavailable, reason="Disabled by source config")
        if not provider_key(self.settings.env, self.provider):
            return SourceStatus(source=self.name, status=SourceState.missing_credentials,
                                reason=f"Missing {self.required_env[0]}", missing_credentials=list(self.required_env))
        return SourceStatus(source=self.name, status=SourceState.enabled,
                            reason=f"Configured platform search via {self.provider}; search request verifies access")

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        status = self.availability()
        if status.status != SourceState.enabled:
            raise AdapterError(status.status, status.reason)
        if not query.strip() or limit <= 0:
            return []
        options = self.settings.sources[self.name].options
        if self.name == "youtube":
            params = {"keyword": query, "type": "video", "sort_by": options.get("sort_by", "relevance")}
        elif self.name == "reddit":
            params = {"query": query, "search_type": "post", "sort": "RELEVANCE", "time_range": "all",
                      "allow_nsfw": "0", "need_format": "true"}
        elif self.name == "x":
            params = {"keyword": query, "search_type": options.get("search_type", "Top")}
        elif self.name == "douyin":
            params = {"keyword": query, "cursor": 0, "sort_type": "0", "publish_time": "0",
                      "filter_duration": "0", "content_type": "0", "search_id": "", "backtrace": ""}
        else:
            params = {"keyword": query, "search_type": "video", "page_size": min(limit, 20)}
        method, route = ROUTES[self.name]
        payload = await self.http.request_json(
            method, BASES[self.provider] + route,
            params=params if method == "GET" else None,
            json=params if method == "POST" else None,
            headers={"Authorization": "Bearer " + provider_key(self.settings.env, self.provider)},
        )
        code = payload.get("code", 200)
        if isinstance(code, str) and code.isdigit():
            code = int(code)
        if code not in (0, 200, "200", "0"):
            state = {401: SourceState.unavailable, 403: SourceState.unavailable,
                     402: SourceState.quota_exhausted, 429: SourceState.rate_limited}.get(code, SourceState.error)
            raise AdapterError(state, f"{self.provider} returned an unsuccessful API response")
        data = payload.get("data")
        if not isinstance(data, (dict, list)):
            raise AdapterError(SourceState.error, f"{self.provider} returned no structured search data")
        return self.parse(data, query, limit)

    def parse(self, data: Any, query: str, limit: int) -> list[SearchResult]:
        results = []
        seen = set()
        for row in _walk(data):
            title = snippet = author = url = ""
            if self.name == "youtube":
                video_id = row.get("video_id") or row.get("videoId")
                if not isinstance(video_id, str) or not video_id:
                    continue
                title = _text(row.get("title"))
                url = f"https://www.youtube.com/watch?v={video_id}"
                snippet = _text(row.get("description_snippet") or row.get("description") or row.get("descriptionSnippet"))
                author = _text(row.get("author") or row.get("ownerText"))
            elif self.name == "douyin":
                identifier = row.get("aweme_id")
                if not isinstance(identifier, (str, int)):
                    continue
                title = _text(row.get("desc"))
                url = f"https://www.douyin.com/video/{identifier}"
                author = _text(row.get("author", {}).get("nickname")) if isinstance(row.get("author"), dict) else ""
                snippet = title
            elif self.name == "x":
                legacy = row.get("legacy", row)
                if not isinstance(legacy, dict):
                    continue
                identifier = legacy.get("id_str") or row.get("rest_id") or row.get("tweet_id")
                snippet = _text(legacy.get("full_text") or row.get("text"))
                if not identifier or not snippet:
                    continue
                title = snippet[:200]
                url = f"https://x.com/i/status/{identifier}"
            elif self.name == "reddit":
                title = _text(row.get("title") or row.get("postTitle"))
                permalink = row.get("permalink")
                if isinstance(permalink, str) and permalink.startswith("/r/"):
                    url = "https://www.reddit.com" + permalink
                else:
                    url = _safe_url(row.get("url") or row.get("post_url"))
                content = row.get("content", {})
                snippet = _text(row.get("selftext") or row.get("body") or row.get("text") or (
                    content.get("markdown") if isinstance(content, dict) else ""))
                author = _text(row.get("author") or row.get("authorInfo"))
            else:
                bvid = row.get("bvid")
                title = _text(row.get("title"))
                url = f"https://www.bilibili.com/video/{bvid}" if bvid else _safe_url(row.get("uri"))
                snippet = _text(row.get("description") or row.get("desc"))
            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(source=self.name, query=query, title=self.clean(title), url=url,
                                        snippet=self.clean(snippet), author=author or None,
                                        metadata={"provider": self.provider, "search_method": "provider_api"}))
            if len(results) >= limit:
                break
        if not results and isinstance(data, dict) and any(k in data for k in ("error", "errors")):
            raise AdapterError(SourceState.error, f"{self.provider} upstream platform search failed")
        return results


def route_providers(settings, http, adapters):
    for platform in ROUTES:
        existing = adapters[platform]
        requested = settings.sources[platform].options.get("provider", "auto")
        if requested not in {"auto", "official", "tikomni", "tikhub"}:
            raise ValueError(f"Invalid search provider for {platform}")
        if requested == "official":
            continue
        if requested in BASES:
            adapters[platform] = ProviderAdapter(settings, http, platform, requested)
        elif existing.availability().status != SourceState.enabled:
            for provider in ("tikomni", "tikhub"):
                if provider_key(settings.env, provider):
                    adapters[platform] = ProviderAdapter(settings, http, platform, provider)
                    break
    return adapters
