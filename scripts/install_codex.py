"""Install the clean local plugin and reuse existing API credentials outside its cache."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

if __package__:
    from .runtime_paths import shared_home, venv_python, remember_shared_home
else:
    from runtime_paths import shared_home, venv_python, remember_shared_home

ROOT = Path(__file__).resolve().parents[1]


def merge_credentials(source: Path, target: Path) -> tuple[int, list[str]]:
    """Import nonempty fields into empty slots; never overwrite existing credentials."""
    from dotenv import dotenv_values, set_key
    if not source.is_file() or source.resolve() == target.resolve():
        return 0, []
    source_values = dotenv_values(source)
    target_values = dotenv_values(target)
    allowed = set(dotenv_values(ROOT / ".env.example")) | {
        "TikHub_key", "TIKHUB_KEY", "Itkomni_key", "TikOmni_key", "TIKOMNI_KEY"}
    count = 0
    conflicts = []
    for key, value in source_values.items():
        if key not in allowed or not value or not value.strip():
            continue
        existing = target_values.get(key)
        if existing and existing.strip():
            if existing != value:
                conflicts.append(key)
            continue
        set_key(str(target), key, value)
        count += 1
    if os.name != "nt":
        target.chmod(0o600)
    return count, conflicts


def find_codex() -> str:
    found = shutil.which("codex")
    if found:
        return found
    directory = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = list(directory.glob("*/codex.exe"))
    if candidates:
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    raise RuntimeError("Codex CLI not found. Install/open the Codex desktop app, then retry.")


def snapshot(home: Path) -> Path:
    """Register only a filtered source snapshot, never the folder containing .env."""
    if __package__:
        from .package_plugin import package
    else:
        from package_plugin import package
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    destination = home / "sources" / manifest["version"]
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deep-websearch-install-") as temporary:
        archive_path = package(Path(temporary) / "plugin.zip")
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                path = (destination / info.filename).resolve()
                if not path.is_relative_to(destination.resolve()):
                    raise RuntimeError("Invalid archive path")
            archive.extractall(destination)
    return destination / manifest["name"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Existing private .env to reuse locally")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare runtime/config without registering")
    parser.add_argument("--runtime-ready", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    home = shared_home().resolve()
    python = venv_python(home)
    if not args.runtime_ready:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "--shared"], check=True)
        subprocess.run([str(python), str(Path(__file__).resolve()), *sys.argv[1:], "--runtime-ready"], check=True)
        return
    source = (args.env_file or ROOT / ".env").expanduser().resolve()
    remember_shared_home(home)
    count, conflicts = merge_credentials(source, home / ".env")
    print(f"Imported {count} existing API fields; existing settings were preserved.")
    if conflicts:
        print("Existing nonempty fields kept: " + ", ".join(conflicts))
    print(f"API configuration: {home / '.env'}")
    if args.prepare_only:
        return
    codex = find_codex()
    plugin = snapshot(home)
    subprocess.run([codex, "plugin", "marketplace", "add", str(plugin)], check=True)
    subprocess.run([codex, "plugin", "add", "deep-websearch@deep-websearch-local", "--json"], check=True)
    print("Installed. Restart Codex once to load the new tools. After reboot, just open Codex.")
    print("Codex starts the local MCP automatically; no tunnel or separate terminal is required.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print arbitrary subprocess/request exception representations.
        print(f"Setup failed ({type(exc).__name__}). Check Python/network/Codex installation.", file=sys.stderr)
        raise SystemExit(1) from None
