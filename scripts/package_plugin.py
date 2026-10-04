"""Build a private distributable ZIP without secrets, caches or dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "plugin.json", "mcp.json", ".mcp.json", "README.md", "LICENSE", "pyproject.toml",
    "config.example.yaml", ".env.example", ".gitignore", "requirements.txt",
}
DIRECTORIES = {
    "src", "skills", "scripts", "assets", "tests", "docs", ".codex-plugin", ".github", ".agents"
}
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv"}


def contained_regular_path(path: Path) -> bool:
    """Reject escaped paths and links/reparse points anywhere in their ancestry."""
    try:
        if not path.resolve().is_relative_to(ROOT.resolve()):
            return False
        current = ROOT
        for part in path.relative_to(ROOT).parts:
            current /= part
            details = current.lstat()
            if stat.S_ISLNK(details.st_mode):
                return False
            # Detect Windows junctions as well, including on Python 3.11.
            if getattr(details, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                return False
        return True
    except (OSError, ValueError):
        return False


def sensitive_file(relative: Path) -> bool:
    name = relative.name.lower()
    if relative == Path(".env.example"):
        return False
    return name == ".env" or name.startswith(".env.") or name == "config.yaml"


def package(destination: Path) -> Path:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    target = destination.expanduser().resolve()
    if target.is_relative_to(ROOT):
        raise ValueError("Write the archive outside the plugin source directory.")
    files = []
    candidates = [ROOT / name for name in ROOT_FILES]
    for name in sorted(DIRECTORIES):
        directory = ROOT / name
        if directory.is_dir() and contained_regular_path(directory):
            candidates.extend(directory.rglob("*"))
    for path in sorted(candidates):
        if not path.is_file() or not contained_regular_path(path):
            continue
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if len(relative.parts) == 1 and relative.name not in ROOT_FILES:
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in DIRECTORIES:
            continue
        if sensitive_file(relative):
            continue
        files.append((path, relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            archive.write(path, str(Path(manifest["name"]) / relative))
    return target


def main() -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT.parent / f"{manifest['name']}-{manifest['version']}.zip",
    )
    args = parser.parse_args()
    print(package(args.output))


if __name__ == "__main__":
    main()
