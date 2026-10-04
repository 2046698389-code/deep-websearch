"""Exercise the real stdio protocol against a local deterministic search backend."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_mcp_search_reports_missing_platform_without_calling_it(tmp_path):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(parse_qs(urlsplit(self.path).query)["q"][0])
            body = json.dumps({"results": [{"title": "Local evidence", "url": "https://example.com/evidence",
                                           "content": "A reproducible search result"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "config.yaml"
    config.write_text("sources:\n  bilibili:\n    enabled: false\nnotifications:\n  desktop: false\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(command=sys.executable, args=[str(root / "scripts/run_server.py")],
        cwd=str(root), env={"DEEP_WEBSEARCH_CONFIG": str(config), "DEEP_WEBSEARCH_HOME": str(tmp_path),
                           "DEEP_WEBSEARCH_HEADLESS": "1", "SEARXNG_URL": f"http://127.0.0.1:{backend.server_port}"})
    try:
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                discovered = await session.list_tools()
                assert all(tool.annotations and tool.annotations.readOnlyHint for tool in discovered.tools)
                response = await session.call_tool("broad_search", {"topic": "AI video", "sources": ["searxng", "x"],
                    "rounds": 2, "notify": False})
                assert not response.isError
                payload = json.loads(response.content[0].text)
                assert payload["status"] == "completed"
                assert payload["coverage"]["raw_results"] == 6
                assert payload["coverage"]["unique_results"] == 1
                assert payload["coverage"]["enabled_and_searched"] == ["searxng"]
                assert payload["missing_sources"][0]["source"] == "x"
                assert len(received) == 6
                assert payload["coverage"]["http_requests"] == 6
    finally:
        await asyncio.to_thread(backend.shutdown)
        backend.server_close()
        thread.join(timeout=2)
