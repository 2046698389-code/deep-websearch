"""Hermetic provider contract tests; no real credentials or external queries."""

import asyncio
import base64
import json

import httpx
import pytest

from deep_websearch.adapters.base import AdapterError
from deep_websearch.adapters.social import (
    BilibiliAdapter, DouyinAdapter, RedditAdapter, XAdapter, YouTubeAdapter,
    build_social_adapters,
)
from deep_websearch.config import Settings
from deep_websearch.http import HttpClient
from deep_websearch.models import SourceState
from deep_websearch.orchestrator import SearchOrchestrator


def run(coroutine):
    return asyncio.run(coroutine)


def settings_for(name, env=None, options=None, enabled="auto"):
    return Settings(env=env or {}, sources={name: {"enabled": enabled, "options": options or {}}},
                    search={"retries": 0})


def test_social_registry_and_missing_credentials_are_offline():
    async def scenario():
        def never(request):
            pytest.fail("availability must not contact providers")
        async with HttpClient(Settings(), transport=httpx.MockTransport(never)) as http:
            adapters = build_social_adapters(Settings(), http)
            assert set(adapters) == {"youtube", "reddit", "x", "bilibili", "douyin"}
            for name in ("youtube", "reddit", "x", "douyin"):
                status = adapters[name].availability()
                assert status.status == SourceState.missing_credentials
                assert status.missing_credentials
            assert adapters["bilibili"].availability().status == SourceState.enabled
    run(scenario())


@pytest.mark.parametrize("adapter,env", [
    (YouTubeAdapter, {"YOUTUBE_API_KEY": "test"}),
    (RedditAdapter, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
    (XAdapter, {"X_BEARER_TOKEN": "test"}),
    (BilibiliAdapter, {}),
    (DouyinAdapter, {"DOUYIN_CLIENT_KEY": "id", "DOUYIN_CLIENT_SECRET": "secret"}),
])
def test_explicit_disabled_prevents_initialization_and_search(adapter, env):
    async def scenario():
        settings = settings_for(adapter.name, env, enabled=False)
        def never(request):
            pytest.fail("disabled adapter must make no requests")
        async with HttpClient(settings, transport=httpx.MockTransport(never)) as http:
            instance = adapter(settings, http)
            assert (await instance.initialize()).status == SourceState.unavailable
            with pytest.raises(AdapterError) as error:
                await instance.search("offline query", 2)
            assert error.value.state == SourceState.unavailable
    run(scenario())


def test_youtube_maps_video_snippet_and_caps_page_size():
    async def scenario():
        settings = settings_for("youtube", {"YOUTUBE_API_KEY": "dummy-key"},
                                {"relevance_language": "zh-Hans"})
        def handler(request):
            assert request.url.host == "www.googleapis.com"
            assert request.url.params["key"] == "dummy-key"
            assert request.url.params["maxResults"] == "50"
            assert request.url.params["relevanceLanguage"] == "zh-Hans"
            assert request.url.params["type"] == "video"
            return httpx.Response(200, json={"items": [{
                "id": {"videoId": "video123"},
                "snippet": {"title": "Search &amp; evidence", "description": "<b>Summary</b>",
                            "channelTitle": "Research channel", "publishedAt": "2025-01-01T00:00:00Z"},
            }]})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            results = await YouTubeAdapter(settings, http).search("offline query", 70)
            assert len(results) == 1
            assert results[0].url == "https://www.youtube.com/watch?v=video123"
            assert results[0].title == "Search & evidence"
            assert results[0].snippet == "Summary"
            assert results[0].metadata["access_method"] == "official_api"
    run(scenario())


def test_youtube_quota_error_is_truthful_and_redacted():
    async def scenario():
        settings = settings_for("youtube", {"YOUTUBE_API_KEY": "private-test-key"})
        def handler(request):
            return httpx.Response(403, json={"error": {"message": "private-test-key",
                "errors": [{"reason": "quotaExceeded"}]}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError) as error:
                await YouTubeAdapter(settings, http).search("offline query", 1)
            assert error.value.state == SourceState.quota_exhausted
            assert "private-test-key" not in error.value.reason
    run(scenario())


@pytest.mark.parametrize("refresh", [False, True])
def test_reddit_oauth_token_cache_and_search_mapping(refresh):
    async def scenario():
        env = {"REDDIT_CLIENT_ID": "dummy-id", "REDDIT_CLIENT_SECRET": "dummy-secret",
               "REDDIT_USER_AGENT": "python:offline-tests:1 (contact test)"}
        if refresh:
            env["REDDIT_REFRESH_TOKEN"] = "dummy-refresh"
        settings = settings_for("reddit", env, {"subreddit": "science", "time_filter": "month"})
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path == "/api/v1/access_token":
                expected = base64.b64encode(b"dummy-id:dummy-secret").decode()
                assert request.headers["Authorization"] == f"Basic {expected}"
                body = request.content.decode()
                assert f"grant_type={'refresh_token' if refresh else 'client_credentials'}" in body
                if refresh:
                    assert "refresh_token=dummy-refresh" in body
                return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
            assert request.url.host == "oauth.reddit.com"
            assert request.url.path == "/r/science/search"
            assert request.url.params["restrict_sr"] == "true"
            assert request.headers["Authorization"] == "Bearer mock-token"
            return httpx.Response(200, json={"data": {"children": [{"data": {
                "title": "Evidence", "permalink": "/r/science/comments/123/evidence/",
                "selftext": "<b>Details</b>", "author": "researcher", "created_utc": 1735689600,
                "subreddit": "science", "score": 10,
            }}]}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            adapter = RedditAdapter(settings, http)
            assert (await adapter.initialize()).status == SourceState.enabled
            results = await adapter.search("offline query", 2)
            await adapter.search("second offline query", 2)
            assert sum(request.url.path == "/api/v1/access_token" for request in calls) == 1
            assert results[0].url == "https://www.reddit.com/r/science/comments/123/evidence/"
            assert results[0].published_at == "2025-01-01T00:00:00+00:00"
            assert results[0].snippet == "Details"
    run(scenario())


def test_reddit_failed_token_is_unavailable():
    async def scenario():
        settings = settings_for("reddit", {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"})
        def handler(request):
            return httpx.Response(200, json={"error": "invalid_client"})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            status = await RedditAdapter(settings, http).initialize()
            assert status.status == SourceState.unavailable
    run(scenario())


def test_x_recent_search_maps_user_and_trims_api_minimum():
    async def scenario():
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"})
        def handler(request):
            assert request.url.path == "/2/tweets/search/recent"
            assert request.url.params["max_results"] == "10"
            assert request.url.params["query"] == "offline query -is:retweet"
            assert request.headers["Authorization"] == "Bearer mock-bearer"
            return httpx.Response(200, json={
                "data": [{"id": str(i), "text": "A post", "author_id": "user-id",
                          "created_at": "2025-01-01T00:00:00Z"} for i in range(3)],
                "includes": {"users": [{"id": "user-id", "username": "researcher"}]},
            })
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            results = await XAdapter(settings, http).search("offline query", 1)
            assert len(results) == 1
            assert results[0].url == "https://x.com/researcher/status/0"
            assert results[0].metadata["search_window"] == "recent_7_days"
    run(scenario())


def test_x_permission_and_rate_limits_are_separate():
    async def scenario():
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"})
        for code, state in ((403, SourceState.unavailable), (429, SourceState.rate_limited)):
            def handler(request):
                return httpx.Response(code, json={"detail": "Do not leak server text"})
            async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
                with pytest.raises(AdapterError) as error:
                    await XAdapter(settings, http).search("offline query", 1)
                assert error.value.state == state
    run(scenario())


def test_x_documented_empty_result_is_success():
    async def scenario():
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"})
        def handler(request):
            return httpx.Response(200, json={"meta": {"result_count": 0}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            assert await XAdapter(settings, http).search("offline query", 1) == []
    run(scenario())


@pytest.mark.parametrize("query", [
    "e" * 700,
    "检索证据" * 175,
    ("research " * 70) + "-misinformation -is:reply lang:en",
])
@pytest.mark.parametrize("include_retweets", [False, True])
def test_x_long_actual_query_fits_limit_and_keeps_constraints(query, include_retweets):
    async def scenario():
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"},
                                {"include_retweets": include_retweets})
        actual = []
        def handler(request):
            effective = request.url.params["query"]
            actual.append(effective)
            assert 0 < len(effective) <= 512
            assert ("-is:retweet" in effective.split()) is (not include_retweets)
            if "-misinformation" in query:
                assert "-misinformation" in effective.split()
                assert "-is:reply" in effective.split()
                assert "lang:en" in effective.split()
            return httpx.Response(200, json={"data": [{"id": "123", "text": "Evidence"}]})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            results = await XAdapter(settings, http).search(query, 1)
            assert results[0].query == query
            assert results[0].metadata["effective_query"] == actual[0]
            assert results[0].metadata["query_reduced"] is True
    run(scenario())


def test_x_existing_retweet_exclusion_is_not_duplicated():
    async def scenario():
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"})
        def handler(request):
            assert request.url.params["query"] == "evidence -is:retweet"
            return httpx.Response(200, json={"data": [{"id": "123", "text": "Evidence"}]})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            result = (await XAdapter(settings, http).search("evidence -is:retweet", 1))[0]
            assert result.metadata["query_reduced"] is False
    run(scenario())


@pytest.mark.parametrize("adapter,env", [
    (XAdapter, {"X_BEARER_TOKEN": "mock-bearer"}),
    (RedditAdapter, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
])
@pytest.mark.parametrize("query", [
    '"' + "keyword " * 70 + '" -misinformation',
    "(first OR second) " + "keyword " * 70,
    "keyword " * 70 + " AND -misinformation",
])
def test_overlong_complex_native_query_fails_before_request(adapter, env, query):
    async def scenario():
        settings = settings_for(adapter.name, env)
        def never(request):
            pytest.fail("local query constraint must be checked before auth or search HTTP")
        async with HttpClient(settings, transport=httpx.MockTransport(never)) as http:
            with pytest.raises(AdapterError) as error:
                await adapter(settings, http).search(query, 1)
            assert error.value.state == SourceState.error
            assert "512" in error.value.reason
            assert http.request_count == 0
    run(scenario())


def test_reddit_actual_query_fits_documented_limit_and_retains_filters():
    async def scenario():
        query = "research " * 70 + " -misinformation subreddit:science"
        settings = settings_for("reddit", {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"})
        actual = []
        def handler(request):
            if request.url.path == "/api/v1/access_token":
                return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
            effective = request.url.params["q"]
            actual.append(effective)
            assert len(effective) <= 512
            assert "-misinformation" in effective.split()
            assert "subreddit:science" in effective.split()
            return httpx.Response(200, json={"data": {"children": [{"data": {
                "title": "Evidence", "permalink": "/r/science/comments/123/",
            }}]}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            result = (await RedditAdapter(settings, http).search(query, 1))[0]
            assert result.query == query
            assert result.metadata["effective_query"] == actual[0]
            assert result.metadata["query_reduced"] is True
    run(scenario())


def test_x_orchestrator_reports_actual_query_and_preserves_planned_query():
    async def scenario():
        original = "证" * 550
        settings = settings_for("x", {"X_BEARER_TOKEN": "mock-bearer"})
        actual = []
        def handler(request):
            actual.append(request.url.params["query"])
            return httpx.Response(200, json={"data": [{"id": "123", "text": "Evidence"}]})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            adapter = XAdapter(settings, http)
            report = await SearchOrchestrator(settings, http, adapters={"x": adapter}).broad_search(
                original, sources=["x"], rounds=1, notify=False)
            result = report["results"][0]
            assert result["query"] == actual[0]
            assert result["metadata"]["effective_query"] == actual[0]
            assert result["provenance"][0]["query"] == actual[0]
            assert result["provenance"][0]["planned_query"] == original
            assert report["coverage"]["queries"][0]["query"] == original
            assert len(actual[0]) <= 512
    run(scenario())


def test_bilibili_public_cookie_initialization_is_counted_once():
    async def scenario():
        settings = settings_for("bilibili")
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.host == "www.bilibili.com":
                return httpx.Response(200, text="<html>Public home</html>",
                    headers={"set-cookie": "buvid3=site-issued-cookie; Domain=.bilibili.com; Path=/"})
            assert request.headers["Cookie"] == "buvid3=site-issued-cookie"
            assert "w_rid" not in request.url.params
            return httpx.Response(200, json={"code": 0, "data": {"result": [{
                "bvid": "BV123", "title": '<em class="keyword">Evidence</em>',
                "description": "Video summary", "author": "Researcher", "pubdate": 1735689600,
            }]}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            adapter = BilibiliAdapter(settings, http)
            assert (await adapter.initialize()).status == SourceState.enabled
            results = await adapter.search("offline query", 1)
            assert len(calls) == 2
            assert http.request_count == 2
            assert results[0].title == "Evidence"
            assert results[0].url == "https://www.bilibili.com/video/BV123/"
            assert results[0].metadata["best_effort"] is True
    run(scenario())


def test_bilibili_challenge_is_not_bypassed():
    async def scenario():
        settings = settings_for("bilibili")
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(412, text="challenge")
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            adapter = BilibiliAdapter(settings, http)
            with pytest.raises(AdapterError) as error:
                await adapter.search("offline query", 1)
            assert error.value.state == SourceState.unavailable
            assert len(calls) == 1
    run(scenario())


@pytest.mark.parametrize("options,env_extra", [
    ({}, {}), ({"search_permission": True}, {}),
    ({"search_permission": True, "device_id": "invalid"}, {}),
    ({"search_permission": True, "device_id": True}, {}),
    ({"search_permission": True}, {"DOUYIN_DEVICE_ID": "9223372036854775808"}),
])
def test_douyin_keys_alone_or_invalid_device_remain_unavailable(options, env_extra):
    async def scenario():
        env = {"DOUYIN_CLIENT_KEY": "id", "DOUYIN_CLIENT_SECRET": "secret", **env_extra}
        settings = settings_for("douyin", env, options)
        def never(request):
            pytest.fail("incomplete Douyin access must be decided without network")
        async with HttpClient(settings, transport=httpx.MockTransport(never)) as http:
            adapter = DouyinAdapter(settings, http)
            assert adapter.availability().status == SourceState.unavailable
            assert (await adapter.initialize()).status == SourceState.unavailable
    run(scenario())


def test_douyin_documented_permissioned_endpoint_and_token_cache():
    async def scenario():
        settings = settings_for("douyin", {"DOUYIN_CLIENT_KEY": "id", "DOUYIN_CLIENT_SECRET": "secret",
                                          "DOUYIN_DEVICE_ID": "8241677744935186821"},
                                {"search_permission": True})
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path == "/oauth/client_token/":
                assert json.loads(request.content) == {
                    "client_key": "id", "client_secret": "secret", "grant_type": "client_credential"
                }
                return httpx.Response(200, json={"data": {"error_code": 0,
                    "access_token": "mock-token", "expires_in": 7200}})
            assert request.url.path == "/dy_open_api/v1/search/video/"
            assert request.headers["access-token"] == "mock-token"
            assert request.url.params["device_id"] == "8241677744935186821"
            assert request.url.params["keyword"] == "offline query"
            return httpx.Response(200, json={"err_no": 0, "data": {"data": {"video_list": [{
                "item_id": "1234", "title": "Evidence", "nickname": "Researcher",
                "create_time": 1735689600, "link": "https://www.douyin.com/video/1234",
                "high_quality_text": "Detailed text", "statistics": {"digg_count": 5},
            }]}}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            adapter = DouyinAdapter(settings, http)
            assert (await adapter.initialize()).status == SourceState.enabled
            results = await adapter.search("offline query", 1)
            assert len(calls) == 2
            assert results[0].snippet == "Detailed text"
            assert results[0].metadata["access_method"] == "official_permissioned_api"
    run(scenario())


@pytest.mark.parametrize("code,state", [
    (28001018, SourceState.unavailable), (28003017, SourceState.quota_exhausted),
    (28001005, SourceState.error),
])
def test_douyin_http200_business_error_is_not_empty_success(code, state):
    async def scenario():
        settings = settings_for("douyin", {"DOUYIN_CLIENT_KEY": "id", "DOUYIN_CLIENT_SECRET": "secret"},
                                {"search_permission": True, "device_id": "12345"})
        def handler(request):
            if request.url.path == "/oauth/client_token/":
                return httpx.Response(200, json={"data": {"error_code": 0,
                    "access_token": "mock-token", "expires_in": 7200}})
            return httpx.Response(200, json={"err_no": code, "err_msg": "secret", "data": {}})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError) as error:
                await DouyinAdapter(settings, http).search("offline query", 1)
            assert error.value.state == state
            assert "secret" not in error.value.reason
    run(scenario())


@pytest.mark.parametrize("adapter,env,options", [
    (YouTubeAdapter, {"YOUTUBE_API_KEY": "test"}, {}),
    (RedditAdapter, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}, {}),
    (XAdapter, {"X_BEARER_TOKEN": "test"}, {}),
    (BilibiliAdapter, {}, {}),
    (DouyinAdapter, {"DOUYIN_CLIENT_KEY": "id", "DOUYIN_CLIENT_SECRET": "secret"},
     {"search_permission": True, "device_id": "12345"}),
])
def test_malformed_search_shape_is_error_not_false_empty_success(adapter, env, options):
    async def scenario():
        settings = settings_for(adapter.name, env, options)
        def handler(request):
            if request.url.host == "www.bilibili.com":
                return httpx.Response(200, text="<html>Public home</html>")
            if request.url.path == "/api/v1/access_token":
                return httpx.Response(200, json={"access_token": "mock", "expires_in": 3600})
            if request.url.path == "/oauth/client_token/":
                return httpx.Response(200, json={"data": {"error_code": 0, "access_token": "mock"}})
            return httpx.Response(200, json={})
        async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError) as error:
                await adapter(settings, http).search("offline query", 1)
            assert error.value.state == SourceState.error
    run(scenario())
