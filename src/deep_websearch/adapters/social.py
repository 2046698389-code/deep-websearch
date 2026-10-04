"""Read-only social/video adapters with explicit, truthful access requirements.

Public web access to Bilibili is best-effort and is not an official OpenAPI.
Douyin uses the documented, permission-gated video search capability only.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import re
import time
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from ..config import Settings
from ..http import HttpClient
from ..models import SearchResult, SourceState, SourceStatus
from .base import AdapterError, BaseAdapter


def _published(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _result_list(value: Any, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AdapterError(SourceState.error, f"{source} returned an unexpected search response.")
    return _items(value)


def _bounded_query(query: str, source: str, suffix: str = "", max_chars: int = 512) -> str:
    """Bound simple keyword queries while retaining every explicit exclusion.

    A reduction of quoted/Boolean/grouped syntax could change its meaning, so
    reject an overlong complex query rather than silently broaden it.
    """
    normalized = " ".join(query.split())
    tokens = normalized.split()
    suffix = suffix if suffix and suffix not in tokens else ""
    native = f"{normalized} {suffix}".strip()
    if len(native) <= max_chars:
        return native
    if re.search(r'["()]|\b(?:OR|AND|NOT)\b', normalized):
        raise AdapterError(SourceState.error,
                           f"{source} native query exceeds {max_chars} characters; "
                           "shorten quoted, grouped or Boolean query syntax.")
    exclusions = [token for token in tokens if token.startswith("-") or ":" in token]
    if suffix:
        exclusions.append(suffix)
    reserved = " ".join(exclusions)
    budget = max_chars - len(reserved) - (1 if reserved else 0)
    if budget <= 0:
        raise AdapterError(SourceState.error,
                           f"{source} query exclusions exceed its {max_chars}-character limit.")
    keywords = []
    for token in tokens:
        if token.startswith("-") or ":" in token:
            continue
        remaining = budget - len(" ".join(keywords)) - (1 if keywords else 0)
        if len(token) <= remaining:
            keywords.append(token)
        elif not keywords and ":" not in token and remaining > 0:
            # Long unbroken keyword text, including CJK, may be shortened.
            keywords.append(token[:remaining])
            break
        else:
            break
    if not keywords:
        raise AdapterError(SourceState.error,
                           f"{source} native query cannot fit its {max_chars}-character limit "
                           "without altering an operator; shorten the query.")
    return " ".join(keywords + exclusions)


def _ttl(value: Any, default: int = 3600) -> float:
    try:
        return max(1, float(value) - 30)
    except (TypeError, ValueError):
        return float(default - 30)


def _require(adapter: BaseAdapter) -> None:
    status = adapter.availability()
    if status.status != SourceState.enabled:
        raise AdapterError(status.status, status.reason)


def _status(adapter: BaseAdapter, error: AdapterError | None = None) -> SourceStatus:
    if error:
        return SourceStatus(source=adapter.name, status=error.state, reason=error.reason)
    return adapter.availability()


class YouTubeAdapter(BaseAdapter):
    name = "youtube"
    required_env = ("YOUTUBE_API_KEY",)
    endpoint = "https://www.googleapis.com/youtube/v3/search"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        _require(self)
        if limit <= 0:
            return []
        options = self.settings.sources[self.name].options
        params: dict[str, Any] = {
            "key": self.settings.env["YOUTUBE_API_KEY"],
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": min(limit, 50),
            "order": options.get("order", "relevance"),
        }
        for option, parameter in (
            ("relevance_language", "relevanceLanguage"),
            ("region_code", "regionCode"),
            ("published_after", "publishedAfter"),
            ("published_before", "publishedBefore"),
        ):
            if options.get(option):
                params[parameter] = options[option]
        payload = await self.http.request_json("GET", self.endpoint, params=params)
        if payload.get("error"):
            error = _object(payload["error"])
            reasons = {entry.get("reason") for entry in _items(error.get("errors", []))}
            state = (
                SourceState.quota_exhausted
                if reasons & {"quotaExceeded", "dailyLimitExceeded"}
                else SourceState.rate_limited
                if reasons & {"rateLimitExceeded", "userRateLimitExceeded"}
                else SourceState.unavailable
            )
            raise AdapterError(state, "YouTube rejected API access; check project enablement and quota.")
        results = []
        for item in _result_list(payload.get("items"), "YouTube"):
            video_id = _object(item.get("id")).get("videoId")
            snippet = item.get("snippet", {})
            if not video_id or not isinstance(snippet, dict):
                continue
            results.append(SearchResult(
                source=self.name,
                query=query,
                title=self.clean(snippet.get("title", "")),
                url=f"https://www.youtube.com/watch?v={quote(str(video_id), safe='')}",
                snippet=self.clean(snippet.get("description", "")),
                author=self.clean(snippet.get("channelTitle", "")) or None,
                published_at=_published(snippet.get("publishedAt")),
                metadata={"video_id": str(video_id), "channel_id": snippet.get("channelId"),
                          "access_method": "official_api"},
            ))
        return results[:limit]


class RedditAdapter(BaseAdapter):
    name = "reddit"
    required_env = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")
    token_endpoint = "https://www.reddit.com/api/v1/access_token"

    def __init__(self, settings: Settings, http: HttpClient):
        super().__init__(settings, http)
        self._token: str | None = None
        self._expires_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.settings.env.get(
            "REDDIT_USER_AGENT", "python:deep-websearch:0.2.0 (local research plugin)"
        )}

    async def _access_token(self) -> str:
        _require(self)
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        credentials = (
            f"{self.settings.env['REDDIT_CLIENT_ID']}:{self.settings.env['REDDIT_CLIENT_SECRET']}"
        ).encode("utf-8")
        headers = self._headers()
        headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        refresh = self.settings.env.get("REDDIT_REFRESH_TOKEN")
        data = {"grant_type": "refresh_token", "refresh_token": refresh} if refresh else {
            "grant_type": "client_credentials"
        }
        payload = await self.http.request_json("POST", self.token_endpoint, headers=headers, data=data)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise AdapterError(SourceState.unavailable, "Reddit OAuth did not grant an access token.")
        self._token = token
        self._expires_at = time.monotonic() + _ttl(payload.get("expires_in"))
        return token

    async def initialize(self) -> SourceStatus:
        status = self.availability()
        if status.status != SourceState.enabled:
            return status
        try:
            await self._access_token()
        except AdapterError as error:
            return _status(self, error)
        return status

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        _require(self)
        if limit <= 0:
            return []
        options = self.settings.sources[self.name].options
        subreddit = options.get("subreddit")
        endpoint = "https://oauth.reddit.com/search"
        if subreddit:
            endpoint = f"https://oauth.reddit.com/r/{quote(str(subreddit), safe='')}/search"
        native_query = _bounded_query(query, "Reddit")
        headers = self._headers()
        headers["Authorization"] = f"Bearer {await self._access_token()}"
        params: dict[str, Any] = {
            "q": native_query, "limit": min(limit, 100), "sort": options.get("sort", "relevance"),
            "t": options.get("time_filter", "all"), "raw_json": 1,
        }
        if subreddit:
            params["restrict_sr"] = "true"
        payload = await self.http.request_json("GET", endpoint, headers=headers, params=params)
        if payload.get("error"):
            raise AdapterError(SourceState.unavailable, "Reddit search access was denied.")
        results = []
        for child in _result_list(_object(payload.get("data")).get("children"), "Reddit"):
            item = child.get("data", {})
            if not isinstance(item, dict) or not item.get("permalink"):
                continue
            results.append(SearchResult(
                source=self.name, query=query,
                title=self.clean(item.get("title", "")),
                url=urljoin("https://www.reddit.com/", str(item["permalink"])),
                snippet=self.clean(item.get("selftext", "")),
                author=self.clean(item.get("author", "")) or None,
                published_at=_published(item.get("created_utc")),
                metadata={"subreddit": item.get("subreddit"), "score": item.get("score"),
                          "num_comments": item.get("num_comments"), "access_method": "official_api",
                          "effective_query": native_query,
                          "query_reduced": native_query != " ".join(query.split())},
            ))
        return results[:limit]


class XAdapter(BaseAdapter):
    name = "x"
    required_env = ("X_BEARER_TOKEN",)
    endpoint = "https://api.x.com/2/tweets/search/recent"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        _require(self)
        if limit <= 0:
            return []
        options = self.settings.sources[self.name].options
        suffix = "-is:retweet" if options.get("include_retweets", False) is not True else ""
        native_query = _bounded_query(query, "X", suffix)
        params: dict[str, Any] = {
            "query": native_query, "max_results": max(10, min(limit, 100)),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id", "user.fields": "username,name",
        }
        for option in ("start_time", "end_time"):
            if options.get(option):
                params[option] = options[option]
        payload = await self.http.request_json(
            "GET", self.endpoint, params=params,
            headers={"Authorization": f"Bearer {self.settings.env['X_BEARER_TOKEN']}"},
        )
        if payload.get("errors") and not payload.get("data"):
            raise AdapterError(SourceState.unavailable, "X recent search is unavailable for this app or query.")
        users = {str(user.get("id")): user
                 for user in _items(_object(payload.get("includes")).get("users"))}
        raw_results = payload.get("data")
        if raw_results is None and _object(payload.get("meta")).get("result_count") == 0:
            return []
        results = []
        for item in _result_list(raw_results, "X"):
            if not item.get("id"):
                continue
            text = self.clean(item.get("text", ""))
            user = users.get(str(item.get("author_id")), {})
            username = user.get("username")
            url = (f"https://x.com/{quote(str(username), safe='')}/status/"
                   f"{quote(str(item['id']), safe='')}") if username else (
                f"https://x.com/i/web/status/{quote(str(item['id']), safe='')}"
            )
            results.append(SearchResult(
                source=self.name, query=query, title=text[:160], url=url, snippet=text,
                published_at=_published(item.get("created_at")),
                author=self.clean(username or user.get("name", "")) or None,
                metadata={"post_id": str(item["id"]), "public_metrics": item.get("public_metrics", {}),
                          "access_method": "official_api", "search_window": "recent_7_days",
                          "effective_query": native_query,
                          "query_reduced": (native_query != " ".join(query.split()) and
                                            native_query != f"{' '.join(query.split())} {suffix}".strip())},
            ))
        return results[:limit]


class BilibiliAdapter(BaseAdapter):
    """Unsigned legacy public website endpoint; no WBI signing or challenge bypass."""

    name = "bilibili"
    required_env: tuple[str, ...] = ()
    endpoint = "https://api.bilibili.com/x/web-interface/search/type"
    _headers = {
        "User-Agent": "deep-websearch/0.2.0 (read-only public website research)",
        "Referer": "https://search.bilibili.com/",
    }

    def __init__(self, settings: Settings, http: HttpClient):
        super().__init__(settings, http)
        self._initialized = False

    async def initialize(self) -> SourceStatus:
        status = self.availability()
        if status.status != SourceState.enabled or self._initialized:
            return status
        if self.http.request_count >= self.http.max_requests:
            return SourceStatus(source=self.name, status=SourceState.unavailable,
                                reason="Research request budget exhausted")
        self.http.request_count += 1
        try:
            # Use only cookies supplied by the public site; never synthesize buvid,
            # import a user's browser session, calculate signatures, or log in.
            response = await self.http.client.get(
                "https://www.bilibili.com/", headers=self._headers, follow_redirects=False
            )
        except httpx.HTTPError:
            return SourceStatus(source=self.name, status=SourceState.error,
                                reason="Bilibili public session initialization failed.")
        if response.status_code == 429:
            return SourceStatus(source=self.name, status=SourceState.rate_limited,
                                reason="Bilibili public site rate limit.")
        if response.status_code >= 500:
            return SourceStatus(source=self.name, status=SourceState.error,
                                reason="Bilibili public site server error.")
        if response.status_code != 200:
            return SourceStatus(source=self.name, status=SourceState.unavailable,
                                reason="Bilibili public session blocked or unavailable; no bypass attempted.")
        self._initialized = True
        return status

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        _require(self)
        if limit <= 0:
            return []
        status = await self.initialize()
        if status.status != SourceState.enabled:
            raise AdapterError(status.status, status.reason)
        options = self.settings.sources[self.name].options
        payload = await self.http.request_json("GET", self.endpoint, headers=self._headers, params={
            "keyword": query, "search_type": "video", "page": 1,
            "page_size": min(limit, 20), "order": options.get("order", "totalrank"),
        })
        code = payload.get("code", 0)
        if code != 0:
            state = SourceState.rate_limited if code in (-429, -509) else SourceState.unavailable
            raise AdapterError(state, "Bilibili public web search rejected access; no signature or challenge bypass.")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise AdapterError(SourceState.error, "Bilibili public web search returned an unexpected response.")
        results = []
        for item in _result_list(data.get("result"), "Bilibili"):
            bvid = item.get("bvid")
            aid = item.get("aid")
            if not bvid and not aid:
                continue
            video_id = str(bvid) if bvid else f"av{aid}"
            results.append(SearchResult(
                source=self.name, query=query,
                title=self.clean(item.get("title", "")),
                url=f"https://www.bilibili.com/video/{quote(video_id, safe='')}/",
                snippet=self.clean(item.get("description", "")),
                published_at=_published(item.get("pubdate")),
                author=self.clean(item.get("author", "")) or None,
                metadata={"bvid": bvid, "aid": aid, "play": item.get("play"),
                          "access_method": "unofficial_public_web", "best_effort": True},
            ))
        return results[:limit]


class DouyinAdapter(BaseAdapter):
    name = "douyin"
    required_env = ("DOUYIN_CLIENT_KEY", "DOUYIN_CLIENT_SECRET")
    endpoint = "https://open.douyin.com/dy_open_api/v1/search/video/"
    token_endpoint = "https://open.douyin.com/oauth/client_token/"

    def __init__(self, settings: Settings, http: HttpClient):
        super().__init__(settings, http)
        self._token: str | None = None
        self._expires_at = 0.0

    def _device_id(self) -> int | None:
        value = self.settings.sources[self.name].options.get(
            "device_id", self.settings.env.get("DOUYIN_DEVICE_ID")
        )
        if isinstance(value, bool):
            return None
        try:
            device_id = int(str(value))
        except (TypeError, ValueError):
            return None
        return device_id if 0 < device_id < 2**63 else None

    def availability(self) -> SourceStatus:
        status = super().availability()
        if status.status != SourceState.enabled:
            return status
        if self.settings.sources[self.name].options.get("search_permission") is not True:
            return SourceStatus(source=self.name, status=SourceState.unavailable,
                                reason="Douyin requires approved aweme.dy.video_search permission; "
                                       "set options.search_permission=true only after approval.")
        if self._device_id() is None:
            return SourceStatus(source=self.name, status=SourceState.unavailable,
                                reason="Douyin video search requires a valid Int64 device_id "
                                       "in options.device_id or DOUYIN_DEVICE_ID.")
        return status

    @staticmethod
    def _check_error(payload: dict[str, Any], token_response: bool = False) -> None:
        body = payload.get("data", {}) if token_response else payload
        if not isinstance(body, dict):
            raise AdapterError(SourceState.error, "Douyin returned an unexpected response.")
        code = body.get("error_code", 0) if token_response else body.get("err_no", 0)
        if code == 0:
            return
        state = (
            SourceState.quota_exhausted if code == 28003017
            else SourceState.rate_limited if code == 10020
            else SourceState.error if code in (28001005, 28001006)
            else SourceState.unavailable
        )
        reason = (
            "Douyin video search quota is exhausted." if state == SourceState.quota_exhausted
            else "Douyin application lacks approved video search capability."
            if code in (28001014, 28001018, 28001019)
            else "Douyin API rejected access; check application permission, credentials and device_id."
        )
        raise AdapterError(state, reason)

    async def _access_token(self) -> str:
        _require(self)
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        payload = await self.http.request_json("POST", self.token_endpoint, json={
            "client_key": self.settings.env["DOUYIN_CLIENT_KEY"],
            "client_secret": self.settings.env["DOUYIN_CLIENT_SECRET"],
            "grant_type": "client_credential",
        }, headers={"Content-Type": "application/json"})
        self._check_error(payload, token_response=True)
        body = payload.get("data", {})
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise AdapterError(SourceState.unavailable, "Douyin did not grant a client token.")
        self._token = token
        self._expires_at = time.monotonic() + _ttl(body.get("expires_in"), 7200)
        return token

    async def initialize(self) -> SourceStatus:
        status = self.availability()
        if status.status != SourceState.enabled:
            return status
        try:
            await self._access_token()
        except AdapterError as error:
            return _status(self, error)
        return status

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        _require(self)
        if limit <= 0:
            return []
        options = self.settings.sources[self.name].options
        payload = await self.http.request_json("GET", self.endpoint, params={
            "keyword": query, "count": min(limit, 20), "device_id": self._device_id(),
            "cursor": 0, "sort_type": options.get("sort_type", 0),
            "publish_time": options.get("publish_time", 0),
        }, headers={"access-token": await self._access_token(), "Content-Type": "application/json"})
        self._check_error(payload)
        data = payload.get("data", {})
        body = data.get("data", {}) if isinstance(data, dict) else {}
        if not isinstance(body, dict):
            raise AdapterError(SourceState.error, "Douyin video search returned an unexpected response.")
        results = []
        for item in _result_list(body.get("video_list"), "Douyin"):
            item_id = item.get("item_id")
            url = item.get("link")
            if not url and item_id:
                url = f"https://www.douyin.com/video/{quote(str(item_id), safe='')}"
            if not url:
                continue
            results.append(SearchResult(
                source=self.name, query=query,
                title=self.clean(item.get("title", "")), url=str(url),
                snippet=self.clean(item.get("high_quality_text", "")),
                author=self.clean(item.get("nickname", "")) or None,
                published_at=_published(item.get("create_time")),
                metadata={"item_id": item_id, "statistics": item.get("statistics", {}),
                          "access_method": "official_permissioned_api"},
            ))
        return results[:limit]


def build_social_adapters(settings: Settings, http: HttpClient) -> dict[str, BaseAdapter]:
    return {adapter.name: adapter(settings, http) for adapter in (
        YouTubeAdapter, RedditAdapter, XAdapter, BilibiliAdapter, DouyinAdapter
    )}
