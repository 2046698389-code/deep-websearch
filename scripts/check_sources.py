"""Open a readable source readiness check using the same runtime as Codex."""

import os
from pathlib import Path
import runpy
import sys

from runtime_paths import select_runtime

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime, home = select_runtime(ROOT)
    if os.path.normcase(os.path.abspath(runtime)) != os.path.normcase(os.path.abspath(sys.executable)):
        os.execv(str(runtime), [str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]])
    os.environ.setdefault("DEEP_WEBSEARCH_HOME", str(home))
    sys.path.insert(0, str(ROOT / "src"))
    sys.argv = ["deep-websearch", "status"]
    runpy.run_module("deep_websearch", run_name="__main__")


if __name__ == "__main__":
    main()
