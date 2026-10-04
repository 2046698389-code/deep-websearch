import httpx
import logging
import pytest

from deep_websearch.config import Settings, load_settings
from deep_websearch.extraction import PageFetcher, resolve_public
from deep_websearch.http import HttpClient
from deep_websearch.models import AdapterError, SourceState


@pytest.mark.parametrize("code,state", [(429, SourceState.rate_limited), (402, SourceState.quota_exhausted),
                                      (432, SourceState.quota_exhausted), (433, SourceState.quota_exhausted),
                                      (403, SourceState.unavailable)])
async def test_http_states_are_redacted(code, state):
    settings = Settings()
    def handler(request):
        return httpx.Response(code, json={"error": "secret-key-should-not-leak"})
    async with HttpClient(settings, transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AdapterError) as error:
            await http.request_json("GET", "https://example.com")
        assert error.value.state == state
        assert "secret-key" not in str(error.value)


async def test_transient_retries_bounded_by_actual_request_budget():
    settings = Settings(search={"max_requests": 2, "retries": 3})
    async with HttpClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(503))) as http:
        with pytest.raises(AdapterError, match="budget"):
            await http.request_json("GET", "https://example.com")
        assert http.request_count == 2


async def test_provider_specific_quotas():
    for code, payload in [(429, {"error": {"code": "QUOTA_LIMITED"}}),
                          (403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})]:
        async with HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(code, json=payload))) as http:
            with pytest.raises(AdapterError) as error:
                await http.request_json("GET", "https://example.com")
            assert error.value.state == SourceState.quota_exhausted


async def test_http_library_logs_do_not_expose_query_credentials(caplog):
    with caplog.at_level(logging.INFO):
        async with HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as http:
            await http.request_json("GET", "https://example.com/search", params={"api_key": "secret-value"})
    assert "secret-value" not in caplog.text


def test_yaml_and_env_loading_preserve_process_env_and_hide_secrets(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("sources:\n  x:\n    enabled: false\nsearch:\n  rounds: 3\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("X_BEARER_TOKEN=file-secret\n", encoding="utf-8")
    monkeypatch.setenv("X_BEARER_TOKEN", "process-secret")
    settings = load_settings(config, env)
    assert settings.search.rounds == 3
    assert settings.env["X_BEARER_TOKEN"] == "process-secret"
    assert settings.sources["x"].enabled is False
    assert len(settings.sources) == 11
    assert "secret" not in str(settings) and "env" not in settings.model_dump()


def test_unknown_config_source_rejected():
    with pytest.raises(ValueError):
        Settings(sources={"typo": {"enabled": True}})


async def test_extraction_pins_dns_and_strips_active_content():
    async def resolver(host, port):
        assert host == "example.com"
        return "93.184.216.34"
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, text="<title>Evidence</title><main><p>Fact</p><script>secret()</script></main>",
                              headers={"content-type": "text/html"})
    result = await PageFetcher(transport=httpx.MockTransport(handler), resolver=resolver).fetch("https://example.com")
    assert result["title"] == "Evidence" and result["text"] == "Fact"
    assert result["untrusted_content"]


async def test_private_redirect_is_rejected_before_request():
    calls = []
    async def resolver(host, port):
        if host == "127.0.0.1":
            raise ValueError("Only public Internet addresses may be fetched")
        return "93.184.216.34"
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    with pytest.raises(ValueError, match="public"):
        await PageFetcher(transport=httpx.MockTransport(handler), resolver=resolver).fetch("https://example.com")
    assert len(calls) == 1


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.1"])
async def test_private_dns_rejected(host):
    with pytest.raises(ValueError, match="public"):
        await resolve_public(host, 80)


async def test_fetch_size_and_mime_limits():
    async def resolver(host, port):
        return "93.184.216.34"
    with pytest.raises(ValueError, match="binary/PDF"):
        await PageFetcher(resolver=resolver, transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}))).fetch(
                "https://example.com")
    with pytest.raises(ValueError, match="2 MiB"):
        await PageFetcher(resolver=resolver, transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"a" * (2 * 1024 * 1024 + 1),
                                     headers={"content-type": "text/plain"}))).fetch("https://example.com")
