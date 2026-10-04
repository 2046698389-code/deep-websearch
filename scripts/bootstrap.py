"""Create an isolated runtime without changing host MCP/plugin settings."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

if __package__:
    from .runtime_paths import shared_home, venv_python
else:
    from runtime_paths import shared_home, venv_python

ROOT = Path(__file__).resolve().parents[1]


def initialize_configs(home: Path) -> None:
    """Create example-based files, preserving every existing user setting."""
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source_name, target_name in (("config.example.yaml", "config.yaml"), (".env.example", ".env")):
        source = ROOT / source_name
        target = home / target_name
        contents = source.read_text(encoding="utf-8")
        try:
            # O_EXCL also protects existing files during concurrent setup.
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true", help="Also install test and lint tools")
    parser.add_argument(
        "--shared", action="store_true",
        help="Use a stable user runtime and config directory outside plugin installation caches",
    )
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    home = shared_home() if args.shared else ROOT
    if args.shared:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = home / ".venv"
    executable = venv_python(home)
    if not executable.is_file():
        print(f"Creating isolated Python runtime: {runtime}")
        venv.EnvBuilder(with_pip=True).create(runtime)
    target = str(ROOT) + ("[dev]" if args.dev else "")
    arguments = [str(executable), "-m", "pip", "install"]
    if not args.shared:
        arguments.append("-e")
    subprocess.run([*arguments, target], check=True)
    if args.shared:
        initialize_configs(home)
        print(f"Ready. Configure API access in: {home / '.env'}")
        print(f"Source settings: {home / 'config.yaml'}")
        print("Existing configuration was preserved; no plugin cache or host settings were changed.")
        print(
            f'Check sources: "{executable}" -m deep_websearch '
            f'--config "{home / "config.yaml"}" --env-file "{home / ".env"}" status'
        )
    else:
        print("Ready. Copy config.example.yaml to config.yaml and .env.example to .env as needed.")
        print(f"Check sources: {executable} -m deep_websearch status")


if __name__ == "__main__":
    main()
