"""Resolve source-development and stable installed-plugin runtime locations."""

from __future__ import annotations

from collections.abc import Mapping
import os
import json
from pathlib import Path
import sys


def shared_home(
    *, platform: str | None = None, environ: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    user_home = Path.home() if user_home is None else user_home
    explicit = environ.get("DEEP_WEBSEARCH_DATA_HOME", "")
    if explicit:
        if not Path(explicit).is_absolute():
            raise ValueError("DEEP_WEBSEARCH_DATA_HOME must be absolute")
        return Path(explicit)
    if platform == "win32":
        # A packaged Windows app may redirect LOCALAPPDATA. Remember its real
        # runtime path so ordinary shells and Codex reuse exactly the same config.
        pointer = user_home / ".codex" / "deep-websearch-runtime.json"
        if pointer.is_file():
            value = json.loads(pointer.read_text(encoding="utf-8"))
            home = Path(value["home"])
            if not home.is_absolute():
                raise ValueError("Shared runtime home must be absolute")
            return home
        configured = environ.get("LOCALAPPDATA", "")
        base = Path(configured) if configured and Path(configured).is_absolute() else (
            user_home / "AppData" / "Local"
        )
    else:
        # XDG requires an absolute path; ignore an invalid relative override.
        configured = environ.get("XDG_DATA_HOME", "")
        base = Path(configured) if configured and Path(configured).is_absolute() else (
            user_home / ".local" / "share"
        )
    return base / "deep-websearch"


def remember_shared_home(home: Path) -> None:
    if sys.platform != "win32":
        return
    pointer = Path.home() / ".codex" / "deep-websearch-runtime.json"
    home = home.resolve()
    if pointer.is_file():
        value = json.loads(pointer.read_text(encoding="utf-8"))
        if Path(value["home"]).resolve() != home:
            raise ValueError("Existing runtime location differs; preserve it")
        return
    pointer.parent.mkdir(parents=True, exist_ok=True)
    with pointer.open("x", encoding="utf-8") as stream:
        json.dump({"home": str(home)}, stream)


def venv_python(home: Path, *, platform: str | None = None) -> Path:
    executable = "Scripts/python.exe" if (platform or sys.platform) == "win32" else "bin/python"
    return home / ".venv" / executable


def select_runtime(root: Path) -> tuple[Path, Path]:
    """Prefer an explicit source venv, then the user's stable runtime."""
    source_python = venv_python(root)
    if source_python.is_file():
        return source_python, root
    shared = shared_home()
    shared_python = venv_python(shared)
    if shared_python.is_file():
        return shared_python, shared
    # An already provisioned host interpreter supports CI/manual MCP use.
    return Path(sys.executable), root
