import httpx
import pytest

from deep_websearch.adapters import build_adapters
from deep_websearch.adapters.providers import ProviderAdapter
from deep_websearch.config import Settings, load_settings
from deep_websearch.http import HttpClient
from deep_websearch.models import AdapterError, SourceState
from deep_websearch.orchestrator import SearchOrchestrator


def test_user_existing_aliases_and_process_precedence(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TikHub_key=file-hub\nItkomni_key=file-omni\n", encoding="utf-8")
    monkeypatch.setenv("TikHub_key", "process-hub")
    settings = load_settings(env_file=path)
    assert settings.env["TIKHUB_API_KEY"] == "process-hub"
    assert settings.env["TIKOMNI_API_KEY"] == "file-omni"
    assert "file-omni" not in repr(settings)


def test_platform_auto_routing_uses_existing_provider_and_keeps_public_bilibili():
    settings = Settings(env={"Itkomni_key": "fixture"})
    adapters = build_adapters(settings, None)
    for name in ("youtube", "reddit", "x", "douyin"):
        assert adapters[name].provider == "tikomni"
        assert adapters[name].availability().status == SourceState.enabled
    assert not isinstance(adapters["bilibili"], ProviderAdapter)


def test_explicit_official_and_disabled_sources_are_respected():
    settings = Settings(env={"TikHub_key": "fixture"}, sources={
        "youtube": {"options": {"provider": "official"}}, "x": {"enabled": False}})
    adapters = build_adapters(settings, None)
    assert not isinstance(adapters["youtube"], ProviderAdapter)
    assert adapters["x"].availability().status == SourceState.unavailable


@pytest.mark.parametrize("platform,data,url", [
    ("youtube", {"videos": [{"video_id": "abc", "title": "Tutorial", "description_snippet": "Evidence"}]},
     "https://www.youtube.com/watch?v=abc"),
    ("douyin", {"data": [{"aweme_info": {"aweme_id": "123", "desc": "Evidence"}}]},
     "https://www.douyin.com/video/123"),
    ("x", {"instructions": [{"content": {"tweet_results": {"result": {
        "rest_id": "123", "legacy": {"full_text": "Evidence", "id_str": "123"}}}}}]},
     "https://x.com/i/status/123"),
    ("reddit", {"children": [{"post": {"postTitle": "Evidence", "permalink": "/r/test/comments/abc/",
                                          "content": {"markdown": "Full text"}}}]},
     "https://www.reddit.com/r/test/comments/abc/"),
])
async def test_provider_records_and_wire_contract(platform, data, url):
    settings = Settings(env={"TIKOMNI_API_KEY": "fixture-secret"})
    def handler(request):
        assert request.url.host == "api.tikomni.com"
        assert request.headers["Authorization"] == "Bearer fixture-secret"
        assert "fixture-secret" not in str(request.url)
        if platform == "douyin":
            assert request.method == "POST" and b'"keyword":"topic"' in request.content
        return httpx.Response(200, json={"code": 200, "data": data})
    async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
        results = await ProviderAdapter(settings, http, platform, "tikomni").search("topic", 1)
    assert len(results) == 1 and results[0].url == url
    assert results[0].metadata["provider"] == "tikomni"
    assert "fixture-secret" not in str(results)


async def test_provider_provenance_does_not_claim_official_native_search():
    settings = Settings(env={"Itkomni_key": "fixture-secret"}, search={"rounds": 1})
    data = {"code": 200, "data": {"videos": [{"video_id": "abc", "title": "Evidence"}]}}
    async with HttpClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as http:
        result = await SearchOrchestrator(settings, http).broad_search("topic", sources=["youtube"], notify=False)
    assert result["results"][0]["provenance"][0]["method"] == "provider_api"
    source = next(s for s in result["coverage"]["sources"] if s["source"] == "youtube")
    assert source["provider_successful_queries"] == 1
    assert not source["native_search_completed"]


@pytest.mark.parametrize("code,state", [(402, SourceState.quota_exhausted), (429, SourceState.rate_limited),
                                      (403, SourceState.unavailable)])
async def test_json_application_errors_are_not_success_and_do_not_echo_secrets(code, state):
    settings = Settings(env={"TIKHUB_API_KEY": "fixture-secret"})
    payload = {"code": code, "message": "fixture-secret", "data": {}}
    async with HttpClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        with pytest.raises(AdapterError) as error:
            await ProviderAdapter(settings, http, "youtube", "tikhub").search("topic", 1)
    assert error.value.state == state and "fixture-secret" not in str(error.value)
