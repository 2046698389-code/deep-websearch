"""Build a private distributable ZIP without secrets, caches or dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
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
CHATGPT_ROOT_FILES = {"README.md", "LICENSE"}
CHATGPT_DIRECTORIES = {"skills", "assets"}
APP_ID_PATTERN = re.compile(r"(?:asdk_app_|connector_|templated_apps_)[A-Za-z0-9][A-Za-z0-9_-]*")


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


def validate_chatgpt_app_id(value: str) -> str:
    """Validate shape only; account eligibility must be confirmed by the caller."""
    if not isinstance(value, str) or len(value) > 256 or not APP_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "Provide a verified registered MCP application ID beginning with "
            "asdk_app_, connector_, or templated_apps_; names, URLs and placeholders are not valid IDs."
        )
    return value


def chatgpt_manifests(manifest: dict, app_id: str) -> dict[str, dict]:
    """Derive a separate private account package without changing source files."""
    app_id = validate_chatgpt_app_id(app_id)
    portable = json.loads(json.dumps(manifest))
    openai = portable.setdefault("extensions", {}).setdefault("com.openai", {})
    openai["apps"] = "./.app.json"
    openai.pop("mcpServers", None)
    portable.pop("mcpServers", None)
    compatibility = {key: value for key, value in portable.items() if key not in {"$schema", "extensions"}}
    compatibility.update(openai)
    compatibility["skills"] = "./skills/"
    compatibility.pop("mcpServers", None)
    return {
        "plugin.json": portable,
        ".codex-plugin/plugin.json": compatibility,
        ".app.json": {"apps": {manifest["name"]: {"id": app_id}}},
    }


def package(destination: Path, *, chatgpt_app_id: str | None = None) -> Path:
    if not contained_regular_path(ROOT / "plugin.json"):
        raise ValueError("plugin.json must be a regular file inside the plugin source directory.")
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    generated = chatgpt_manifests(manifest, chatgpt_app_id) if chatgpt_app_id is not None else {}
    root_files = CHATGPT_ROOT_FILES if generated else ROOT_FILES
    directories = CHATGPT_DIRECTORIES if generated else DIRECTORIES
    target = destination.expanduser().resolve()
    if target.is_relative_to(ROOT):
        raise ValueError("Write the archive outside the plugin source directory.")
    files = []
    candidates = [ROOT / name for name in root_files]
    for name in sorted(directories):
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
        if len(relative.parts) == 1 and relative.name not in root_files:
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in directories:
            continue
        if sensitive_file(relative):
            continue
        files.append((path, relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, contents in generated.items():
            archive.writestr(
                f"{manifest['name']}/{relative}",
                json.dumps(contents, ensure_ascii=False, indent=2) + "\n",
            )
        for path, relative in files:
            archive.write(path, str(Path(manifest["name"]) / relative))
    return target


def main() -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
    )
    parser.add_argument(
        "--chatgpt-app-id",
        help="Build a separate private ChatGPT package bound to an already registered, eligible MCP app",
    )
    args = parser.parse_args()
    suffix = "-chatgpt" if args.chatgpt_app_id is not None else ""
    destination = args.output or ROOT.parent / f"{manifest['name']}-{manifest['version']}{suffix}.zip"
    try:
        print(package(destination, chatgpt_app_id=args.chatgpt_app_id))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
