"""Verify MCP initialization, discovery and configuration checks without API calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def smoke() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "scripts" / "run_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            response = await session.list_tools()
            names = {tool.name for tool in response.tools}
            required = {"source_status", "broad_search", "fetch_page"}
            if not required.issubset(names):
                raise RuntimeError(f"Missing MCP tools: {sorted(required - names)}")
            status = await session.call_tool("source_status", {"probe": False})
            if status.isError:
                raise RuntimeError("source_status returned an MCP error")
            if not status.content:
                raise RuntimeError("source_status returned no content")
    print(f"MCP smoke passed: {', '.join(sorted(names))}; source_status(probe=False).")


if __name__ == "__main__":
    asyncio.run(smoke())
