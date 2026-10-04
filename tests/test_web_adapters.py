import json

import httpx
import pytest

from deep_websearch.adapters.base import AdapterError
from deep_websearch.adapters.web import build_web_adapters
from deep_websearch.config import Settings, SourceConfig
from deep_websearch.http import HttpClient
from deep_websearch.models import SourceState


KEYS = {
    "brave": "BRAVE_SEARCH_API_KEY",
    "searxng": "SEARXNG_URL",
    "exa": "EXA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
}


@pytest.mark.parametrize("source", KEYS)
async def test_missing_credential_never_calls_network(source):
    def unexpected_request(request):
        pytest.fail("Missing credentials must not result in an HTTP request")

    settings = Settings(env={})
    async with HttpClient(settings, transport=httpx.MockTransport(unexpected_request)) as http:
        adapter = build_web_adapters(settings, http)[source]
        assert adapter.availability().status == SourceState.missing_credentials
        assert adapter.availability().missing_credentials == [KEYS[source]]
        with pytest.raises(AdapterError) as raised:
            await adapter.search("test", 5)
        assert raised.value.state == SourceState.missing_credentials
        assert http.request_count == 0


CASES = [
    (
        "brave", "GET", "https://api.search.brave.com/res/v1/web/search",
        {"web": {"results": [
            {"title": "<b>Brave title</b>", "url": "https://example.com/brave", "description": "<em>Evidence</em>", "page_age": "2026-10-01"},
            {"title": "Missing URL"}, None,
        ]}},
        "Brave title", "Evidence", "2026-10-01",
    ),
    (
        "searxng", "GET", "http://localhost:8080/prefix/search",
        {"results": [
            {"title": "Searx title", "url": "https://example.com/searx", "content": "<p>Federated result</p>", "publishedDate": "2026-10-02", "engines": ["bing", "google"]},
            {"title": "Unsafe URL", "url": "javascript:alert(1)"},
        ]},
        "Searx title", "Federated result", "2026-10-02",
    ),
    (
        "exa", "POST", "https://api.exa.ai/search",
        {"results": [
            {"title": "Exa title", "url": "https://example.com/exa", "highlights": ["First", "<b>Second</b>", None], "publishedDate": "2026-10-03T01:00:00Z", "author": "Author", "score": 0.8},
            {"title": "No network URL", "url": "file:///secret.txt"},
        ]},
        "Exa title", "First Second", "2026-10-03T01:00:00Z",
    ),
    (
        "tavily", "POST", "https://api.tavily.com/search",
        {"results": [
            {"title": "Tavily title", "url": "https://example.com/tavily", "content": "<b>Relevant snippet</b>", "published_date": "2026-10-02", "score": 0.95},
            {"title": ["Unexpected type"], "url": "https://example.com/bad"},
        ]},
        "Tavily title", "Relevant snippet", "2026-10-02",
    ),
    (
        "serper", "POST", "https://google.serper.dev/search",
        {"organic": [
            {"title": "Serper title", "link": "https://example.com/serper", "snippet": "Search result", "date": "2 days ago", "position": 1},
            {"title": "Embedded secret", "link": "https://user:secret@example.com/"},
        ]},
        "Serper title", "Search result", "2 days ago",
    ),
    (
        "serpapi", "GET", "https://serpapi.com/search.json",
        {"search_metadata": {"status": "Success"}, "search_parameters": {"api_key": "test-only-key"}, "organic_results": [
            {"title": "SerpAPI title", "link": "https://example.com/serpapi", "snippet": "Organic result", "date": "Oct 1, 2026", "position": 1},
            {"title": "Malformed port", "link": "https://example.com:bad/"},
        ]},
        "SerpAPI title", "Organic result", "Oct 1, 2026",
    ),
]


@pytest.mark.parametrize("source,method,endpoint,payload,title,snippet,date", CASES)
async def test_provider_protocol_and_invalid_rows(source, method, endpoint, payload, title, snippet, date):
    seen = []

    def respond(request):
        seen.append(request)
        assert request.method == method
        assert str(request.url).split("?")[0] == endpoint
        if source == "brave":
            assert request.headers["X-Subscription-Token"] == "test-only-key"
            assert request.url.params["count"] == "20"
            assert request.url.params["q"] == "research topic"
            assert request.url.params["text_decorations"] == "false"
        elif source == "searxng":
            assert request.url.params["format"] == "json"
            assert request.url.params["q"] == "research topic"
        elif source == "exa":
            assert request.headers["x-api-key"] == "test-only-key"
            body = json.loads(request.content)
            assert body["numResults"] == 100
            assert body["query"] == "research topic"
            assert "contents" not in body
        elif source == "tavily":
            assert request.headers["Authorization"] == "Bearer test-only-key"
            body = json.loads(request.content)
            assert body["max_results"] == 20
            assert body["search_depth"] == "basic"
            assert body["auto_parameters"] is False
            assert body["include_answer"] is False
        elif source == "serper":
            assert request.headers["X-API-KEY"] == "test-only-key"
            assert json.loads(request.content)["num"] == 100
        elif source == "serpapi":
            assert request.url.params["engine"] == "google"
            assert request.url.params["api_key"] == "test-only-key"
            assert "num" not in request.url.params
        return httpx.Response(200, json=payload)

    value = "http://localhost:8080/prefix/" if source == "searxng" else "test-only-key"
    settings = Settings(env={KEYS[source]: value})
    async with HttpClient(settings, transport=httpx.MockTransport(respond)) as http:
        results = await build_web_adapters(settings, http)[source].search("research topic", 500)
    assert len(seen) == 1
    assert len(results) == 1
    result = results[0]
    assert result.title == title
    assert result.snippet == snippet
    assert result.published_at == date
    assert result.query == "research topic"
    assert result.source == source
    assert result.provenance == [{"source": source, "query": "research topic", "url": result.url}]
    assert "test-only-key" not in result.model_dump_json()


@pytest.mark.parametrize("source", KEYS)
async def test_result_limit_does_not_count_malformed_rows(source):
    row = {"title": "Valid", "url": "https://example.com/one", "link": "https://example.com/one"}
    second = {**row, "title": "Second", "url": "https://example.com/two", "link": "https://example.com/two"}
    rows = [{"title": "Invalid"}, row, second]
    payload = {"web": {"results": rows}, "results": rows, "organic": rows, "organic_results": rows}
    settings = Settings(env={KEYS[source]: "https://search.example.com" if source == "searxng" else "test-only-key"})
    async with HttpClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        results = await build_web_adapters(settings, http)[source].search("topic", 1)
    assert [result.title for result in results] == ["Valid"]


@pytest.mark.parametrize("source", KEYS)
async def test_disabled_source_never_calls_network(source):
    settings = Settings(
        env={KEYS[source]: "https://search.example.com" if source == "searxng" else "test-only-key"},
        sources={source: SourceConfig(enabled=False)},
    )
    async with HttpClient(settings, transport=httpx.MockTransport(lambda request: pytest.fail("Disabled source called"))) as http:
        with pytest.raises(AdapterError) as raised:
            await build_web_adapters(settings, http)[source].search("topic", 10)
        assert raised.value.state == SourceState.unavailable
        assert http.request_count == 0


@pytest.mark.parametrize("payload,state", [
    ({"error": "Credit limit exceeded test-only-key"}, SourceState.quota_exhausted),
    ({"error": {"code": "RATE_LIMITED", "detail": "test-only-key"}}, SourceState.rate_limited),
    ({"error": "Invalid API key test-only-key"}, SourceState.unavailable),
    ({"error": "Unexpected internal failure test-only-key"}, SourceState.error),
])
async def test_api_errors_are_classified_without_echoing_credentials(payload, state):
    settings = Settings(env={"SERPAPI_API_KEY": "test-only-key"})
    async with HttpClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        with pytest.raises(AdapterError) as raised:
            await build_web_adapters(settings, http)["serpapi"].search("topic", 10)
    assert raised.value.state == state
    assert "test-only-key" not in str(raised.value)


@pytest.mark.parametrize("instance,expected", [
    ("http://localhost:8080/", "http://localhost:8080/search"),
    ("http://192.168.1.2/searx/", "http://192.168.1.2/searx/search"),
    ("https://search.example.com/search", "https://search.example.com/search"),
])
async def test_explicit_self_hosted_searxng_supported(instance, expected):
    def respond(request):
        assert str(request.url).split("?")[0] == expected
        return httpx.Response(200, json={"results": []})

    settings = Settings(env={"SEARXNG_URL": instance})
    async with HttpClient(settings, transport=httpx.MockTransport(respond)) as http:
        adapter = build_web_adapters(settings, http)["searxng"]
        assert adapter.availability().status == SourceState.enabled
        assert await adapter.search("topic", 10) == []


@pytest.mark.parametrize("instance", ["file:///tmp/search", "not-a-url", "https://example.com:bad/", "https://user:secret@example.com/"])
async def test_invalid_searxng_url_reported_before_request(instance):
    settings = Settings(env={"SEARXNG_URL": instance})
    async with HttpClient(settings, transport=httpx.MockTransport(lambda request: pytest.fail("Invalid backend called"))) as http:
        adapter = build_web_adapters(settings, http)["searxng"]
        assert adapter.availability().status == SourceState.unavailable
        with pytest.raises(AdapterError):
            await adapter.search("topic", 10)
        assert http.request_count == 0


async def test_exa_highlights_requires_explicit_opt_in_and_ignores_secret_override():
    def respond(request):
        body = json.loads(request.content)
        assert body["contents"] == {"highlights": True}
        assert body["query"] == "actual query"
        assert "api_key" not in body
        assert request.headers["x-api-key"] == "test-only-key"
        return httpx.Response(200, json={"results": []})

    settings = Settings(
        env={"EXA_API_KEY": "test-only-key"},
        sources={"exa": SourceConfig(options={"include_highlights": True, "query": "bad override", "api_key": "bad key"})},
    )
    async with HttpClient(settings, transport=httpx.MockTransport(respond)) as http:
        assert await build_web_adapters(settings, http)["exa"].search("actual query", 5) == []
