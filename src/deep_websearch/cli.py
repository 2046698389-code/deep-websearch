import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_settings
from .http import HttpClient
from .orchestrator import SearchOrchestrator


def main():
    # JSON and Chinese text must remain readable when Windows pipes use a legacy code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Configuration-driven deep websearch MCP and CLI")
    parser.add_argument("--config", help="YAML configuration path")
    parser.add_argument("--env-file", help="Credential .env path")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="Show source readiness, no network calls by default")
    status.add_argument("--probe", action="store_true")
    search = sub.add_parser("search", help="Perform bounded multi-source research")
    search.add_argument("topic")
    search.add_argument("--sources", nargs="+", help="Explicit native platform list")
    search.add_argument("--query", dest="queries", action="append")
    search.add_argument("--rounds", type=int)
    search.add_argument("--limit", type=int, dest="per_query_limit")
    search.add_argument("--max-results", type=int)
    search.add_argument("--web-index-fallback", action="store_true")
    search.add_argument("--no-popup", action="store_true")
    search.add_argument("--output", help="Write JSON results to an explicitly selected file")
    sub.add_parser("serve", help="Run the MCP stdio server")
    args = parser.parse_args()
    if args.command == "serve":
        import os
        if args.config:
            os.environ["DEEP_WEBSEARCH_CONFIG"] = str(Path(args.config).resolve())
        if args.env_file:
            os.environ["DEEP_WEBSEARCH_ENV_FILE"] = str(Path(args.env_file).resolve())
        from .server import serve
        serve()
        return

    async def run():
        settings = load_settings(args.config, args.env_file)
        async with HttpClient(settings) as http:
            orchestrator = SearchOrchestrator(settings, http)
            if args.command == "status":
                return await orchestrator.source_status(args.probe)
            return await orchestrator.broad_search(
                topic=args.topic, queries=args.queries, sources=args.sources, rounds=args.rounds,
                per_query_limit=args.per_query_limit, max_results=args.max_results,
                web_index_fallback=args.web_index_fallback, notify=False if args.no_popup else None)
    try:
        result = asyncio.run(run())
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if args.command == "search" and args.output:
            Path(args.output).resolve().write_text(payload + "\n", encoding="utf-8")
        print(payload)
    except (ValueError, OSError) as exc:
        # Validation errors may include input credentials; never echo their raw representation.
        print(f"deep-websearch: configuration or input error ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
