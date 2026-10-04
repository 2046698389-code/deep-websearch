import asyncio
import logging

import httpx

from .models import AdapterError, SourceState


class HttpClient:
    def __init__(self, settings=None, *, transport=None):
        # httpx INFO logs include full query-string credentials (YouTube/SerpAPI).
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self.settings = settings
        search = settings.search if settings else None
        self.max_requests = search.max_requests if search else 200
        self.retries = search.retries if search else 1
        self.request_count = 0
        self.client = httpx.AsyncClient(
            timeout=search.timeout_seconds if search else 20,
            transport=transport, follow_redirects=False,
            headers={"User-Agent": "deep-websearch/0.1 (+https://github.com/2046698389-code/deep-websearch)"},
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request_json(self, method, url, *, params=None, headers=None, json=None, data=None):
        for attempt in range(self.retries + 1):
            if self.request_count >= self.max_requests:
                raise AdapterError(SourceState.unavailable, "Research request budget exhausted")
            self.request_count += 1
            try:
                response = await self.client.request(method, url, params=params, headers=headers,
                                                     json=json, data=data)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < self.retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                raise AdapterError(SourceState.error, "Search endpoint timed out or could not be reached") from None
            if response.status_code >= 500 and attempt < self.retries:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            if response.status_code == 429:
                try:
                    limited = response.json().get("error", {}).get("code") == "QUOTA_LIMITED"
                except (ValueError, AttributeError, TypeError):
                    limited = False
                if limited:
                    raise AdapterError(SourceState.quota_exhausted, "Provider search quota exhausted")
                raise AdapterError(SourceState.rate_limited, "Provider rate limit reached")
            if response.status_code in (402, 432, 433):
                raise AdapterError(SourceState.quota_exhausted, "Provider quota or billing allowance exhausted")
            if response.status_code in (401, 403):
                # Only parse known error identifiers, never echo remote messages containing keys.
                try:
                    payload = response.json()
                    errors = payload.get("error", {}).get("errors", [])
                    exhausted = any(x.get("reason") in ("quotaExceeded", "dailyLimitExceeded") for x in errors)
                    rate_limited = any(x.get("reason") in ("rateLimitExceeded", "userRateLimitExceeded") for x in errors)
                except (ValueError, AttributeError, TypeError):
                    exhausted = False
                    rate_limited = False
                if exhausted:
                    raise AdapterError(SourceState.quota_exhausted, "Provider daily quota exhausted")
                if rate_limited:
                    raise AdapterError(SourceState.rate_limited, "Provider rate limit reached")
                raise AdapterError(SourceState.unavailable, "Provider rejected credentials or required permissions")
            if response.is_error or response.is_redirect:
                raise AdapterError(SourceState.error, f"Provider HTTP status {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                raise AdapterError(SourceState.error, "Provider returned non-JSON data") from None
            if not isinstance(payload, dict):
                raise AdapterError(SourceState.error, "Provider returned an unexpected JSON shape")
            return payload
        raise AdapterError(SourceState.error, "Search request failed")
