"""Portable MCP entry point; stdout is reserved for the MCP protocol."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys

if __package__:
    from .runtime_paths import select_runtime
else:
    from runtime_paths import select_runtime

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    runtime, configuration_home = select_runtime(ROOT)
    # Do not resolve symlinks: a Unix venv points at its base interpreter but
    # must still be launched through the venv path to load its site-packages.
    current_executable = os.path.normcase(os.path.abspath(sys.executable))
    runtime_executable = os.path.normcase(os.path.abspath(runtime))
    if runtime.is_file() and runtime_executable != current_executable:
        os.execv(str(runtime), [str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]])
    os.environ.setdefault("DEEP_WEBSEARCH_HOME", str(configuration_home))
    sys.path.insert(0, str(ROOT / "src"))
    sys.argv = ["deep-websearch", "serve"]
    runpy.run_module("deep_websearch", run_name="__main__")


if __name__ == "__main__":
    main()
