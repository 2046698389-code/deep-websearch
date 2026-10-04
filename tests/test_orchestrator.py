from unittest.mock import Mock

import pytest

from deep_websearch.adapters.base import BaseAdapter
from deep_websearch.config import Settings
from deep_websearch.http import HttpClient
from deep_websearch.models import AdapterError, SearchResult, SourceState
from deep_websearch.orchestrator import SearchOrchestrator, canonical_url


class Stub(BaseAdapter):
    def __init__(self, name, settings, http, *, required=(), failure=None):
        super().__init__(settings, http)
        self.name = name
        self.required_env = required
        self.calls = []
        self.initialized = 0
        self.failure = failure

    async def initialize(self):
        self.initialized += 1
        return self.availability()

    async def search(self, query, limit):
        self.calls.append(query)
        self.http.request_count += 1
        if self.failure:
            raise AdapterError(self.failure, "Provider limit")
        return [SearchResult(source=self.name, query=query, title="Evidence",
                             url="https://example.com/evidence?utm_source=" + self.name, snippet="Documented fact")]


async def test_missing_sources_skipped_and_one_reminder(monkeypatch):
    reminder = Mock(return_value=False)
    monkeypatch.setattr("deep_websearch.orchestrator.notify_missing", reminder)
    settings = Settings(env={"YOUTUBE_API_KEY": "test"})
    async with HttpClient(settings) as http:
        youtube = Stub("youtube", settings, http, required=("YOUTUBE_API_KEY",))
        x = Stub("x", settings, http, required=("X_BEARER_TOKEN",))
        result = await SearchOrchestrator(settings, http, adapters={"youtube": youtube, "x": x}).broad_search(
            "AI video", rounds=2)
        assert youtube.initialized == 1 and x.initialized == 0
        assert len(youtube.calls) == 6 and not x.calls
        reminder.assert_called_once()
        assert result["missing_sources"][0]["source"] == "x"
        assert result["coverage"]["unique_results"] == 1
        assert len(result["results"][0]["provenance"]) == 6
        assert result["coverage"]["raw_results"] == 6
        assert result["coverage"]["http_requests"] == 6
        assert result["results"][0]["citation_id"] == "S1"


async def test_source_failure_trips_circuit_but_other_source_continues():
    settings = Settings()
    async with HttpClient(settings) as http:
        x = Stub("x", settings, http, failure=SourceState.rate_limited)
        reddit = Stub("reddit", settings, http)
        result = await SearchOrchestrator(settings, http, adapters={"x": x, "reddit": reddit}).broad_search(
            "AI", queries=["AI tests", "AI pricing"], rounds=2, notify=False)
        assert len(x.calls) == 1
        assert len(reddit.calls) == 8
        assert result["coverage"]["enabled_and_searched"] == ["reddit"]
        assert result["errors"][0]["status"] == "rate_limited"
        assert result["unavailable_sources"][0]["status"] == "rate_limited"


async def test_explicit_platform_fallback_never_counts_as_native():
    settings = Settings()
    async with HttpClient(settings) as http:
        x = Stub("x", settings, http, required=("X_BEARER_TOKEN",))
        brave = Stub("brave", settings, http)
        result = await SearchOrchestrator(settings, http, adapters={"x": x, "brave": brave}).broad_search(
            "AI", sources=["x"], rounds=1, web_index_fallback=True, notify=False)
        assert brave.calls == ["site:x.com AI"]
        assert not x.calls
        assert result["coverage"]["enabled_and_searched"] == []
        assert result["results"][0]["provenance"][0]["method"] == "web_index_fallback"
        assert result["results"][0]["metadata"]["target_platform"] == "x"
        assert all(not source["native_search_completed"] for source in result["coverage"]["sources"])


async def test_budget_and_config_disabled_override_credentials():
    settings = Settings(env={"X_BEARER_TOKEN": "test"}, sources={"x": {"enabled": False}},
                        search={"max_queries": 2, "max_requests": 1})
    async with HttpClient(settings) as http:
        x = Stub("x", settings, http, required=("X_BEARER_TOKEN",))
        brave = Stub("brave", settings, http)
        result = await SearchOrchestrator(settings, http, adapters={"x": x, "brave": brave}).broad_search(
            "AI", queries=["query 2", "query 3"], rounds=4, notify=False)
        assert not x.calls and x.initialized == 0
        assert len(brave.calls) == 1
        assert result["coverage"]["request_budget_exhausted"]
        assert result["coverage"]["query_count"] == 1
        assert result["coverage"]["planned_query_count"] == 2


async def test_empty_configuration_returns_actionable_coverage():
    settings = Settings()
    async with HttpClient(settings) as http:
        x = Stub("x", settings, http, required=("X_BEARER_TOKEN",))
        result = await SearchOrchestrator(settings, http, adapters={"x": x}).broad_search("AI", notify=False)
        assert result["status"] == "no_available_sources"
        assert result["coverage"]["http_requests"] == 0
        assert result["coverage"]["not_searched"][0]["source"] == "x"


async def test_invalid_explicit_sources_rejected():
    settings = Settings()
    async with HttpClient(settings) as http:
        orchestrator = SearchOrchestrator(settings, http, adapters={})
        with pytest.raises(ValueError):
            await orchestrator.broad_search("AI", sources=["unknown"])


def test_canonical_url_removes_tracking_without_removing_identity():
    assert canonical_url("https://EXAMPLE.com/a?v=123&utm_source=x#section") == "https://example.com/a?v=123"
    assert not canonical_url("javascript:alert(1)")
    assert not canonical_url("https://secret@example.com/")
