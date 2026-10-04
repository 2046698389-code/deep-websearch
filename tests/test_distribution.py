"""Offline distribution regressions: stable runtime, preserved config and clean ZIPs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile

import pytest

from scripts import bootstrap, package_plugin, runtime_paths


def test_shared_paths_follow_platform_user_storage(tmp_path):
    assert runtime_paths.shared_home(
        platform="win32", environ={"LOCALAPPDATA": str(tmp_path / "local")}, user_home=tmp_path
    ) == tmp_path / "local" / "deep-websearch"
    assert runtime_paths.shared_home(
        platform="linux", environ={"XDG_DATA_HOME": str(tmp_path / "data")}, user_home=tmp_path
    ) == tmp_path / "data" / "deep-websearch"
    assert runtime_paths.shared_home(
        platform="linux", environ={"XDG_DATA_HOME": "relative-location"}, user_home=tmp_path
    ) == tmp_path / ".local" / "share" / "deep-websearch"


def test_shared_setup_creates_examples_and_preserves_user_config(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.example.yaml").write_text("notifications: {desktop: false}\n", encoding="utf-8")
    (source / ".env.example").write_text("YOUTUBE_API_KEY=\n", encoding="utf-8")
    # A source's private config must never be copied into shared installation.
    (source / ".env").write_text("PRIVATE_SOURCE_ONLY=fixture-value\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", source)
    shared = tmp_path / "shared"
    bootstrap.initialize_configs(shared)
    assert (shared / ".env").read_text(encoding="utf-8") == "YOUTUBE_API_KEY=\n"
    user_settings = b"sources:\n  x: {enabled: false}\n"
    user_credentials = b"USER_SETTING=keep-this-fixture\n"
    (shared / "config.yaml").write_bytes(user_settings)
    (shared / ".env").write_bytes(user_credentials)
    bootstrap.initialize_configs(shared)
    assert (shared / "config.yaml").read_bytes() == user_settings
    assert (shared / ".env").read_bytes() == user_credentials
    if os.name != "nt":
        assert (shared / ".env").stat().st_mode & 0o077 == 0


def test_cached_launcher_uses_shared_runtime_and_cached_source(tmp_path):
    cached = tmp_path / "cache" / "deep-websearch"
    scripts = cached / "scripts"
    scripts.mkdir(parents=True)
    source_scripts = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("run_server.py", "runtime_paths.py"):
        shutil.copyfile(source_scripts / name, scripts / name)
    package = cached / "src" / "deep_websearch"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'home':os.environ['DEEP_WEBSEARCH_HOME'],"
        "'prefix':sys.prefix,'code':__file__,'argv':sys.argv}))\n",
        encoding="utf-8",
    )
    storage = tmp_path / "user-storage"
    shared = storage / "deep-websearch"
    # No pip or network: verify a real venv interpreter launch, not a mock.
    venv.EnvBuilder(with_pip=False).create(shared / ".venv")
    environment = dict(os.environ)
    environment.pop("DEEP_WEBSEARCH_HOME", None)
    environment["LOCALAPPDATA"] = str(storage)
    environment["XDG_DATA_HOME"] = str(storage)
    response = subprocess.run(
        [sys.executable, str(scripts / "run_server.py")],
        env=environment, text=True, capture_output=True, timeout=30, check=True,
    )
    actual = json.loads(response.stdout)
    assert Path(actual["home"]) == shared
    assert Path(actual["prefix"]) == shared / ".venv"
    assert Path(actual["code"]) == package / "__main__.py"
    assert actual["argv"][-1] == "serve"
    # Installing a newer cache copy keeps the same stable runtime and home.
    # A new installed version is a separate copy. Renaming a just-executed
    # directory can fail transiently on Windows while OS scanners hold it.
    renamed_cache = cached.with_name("deep-websearch-new-version")
    shutil.copytree(cached, renamed_cache)
    response = subprocess.run(
        [sys.executable, str(renamed_cache / "scripts" / "run_server.py")],
        env=environment, text=True, capture_output=True, timeout=30, check=True,
    )
    actual = json.loads(response.stdout)
    assert Path(actual["home"]) == shared
    assert Path(actual["prefix"]) == shared / ".venv"


def test_source_runtime_overrides_shared_runtime(tmp_path, monkeypatch):
    source = tmp_path / "source"
    shared = tmp_path / "shared"
    for home in (source, shared):
        executable = runtime_paths.venv_python(home)
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fixture")
    monkeypatch.setattr(runtime_paths, "shared_home", lambda: shared)
    assert runtime_paths.select_runtime(source) == (runtime_paths.venv_python(source), source)


def distribution_fixture(tmp_path, monkeypatch):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"name": "deep-websearch", "version": "0.1.0"}), encoding="utf-8"
    )
    (source / "assets").mkdir()
    (source / "assets" / "icon.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(package_plugin, "ROOT", source)
    return source, tmp_path / "delivery.zip"


def test_archive_excludes_nested_secrets_and_keeps_public_template(tmp_path, monkeypatch):
    source, destination = distribution_fixture(tmp_path, monkeypatch)
    (source / ".env.example").write_text("BRAVE_SEARCH_API_KEY=\n", encoding="utf-8")
    for name in (".env", ".env.local", ".ENV.PRODUCTION", "config.yaml"):
        (source / "assets" / name).write_text("private-fixture", encoding="utf-8")
    package_plugin.package(destination)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
    assert "deep-websearch/.env.example" in names
    assert "deep-websearch/assets/icon.svg" in names
    assert not any("private-fixture" in name or "/.env" in name.lower()
                   for name in names - {"deep-websearch/.env.example"})
    assert "deep-websearch/assets/config.yaml" not in names


def test_archive_excludes_links_and_linked_directory_contents(tmp_path, monkeypatch):
    source, destination = distribution_fixture(tmp_path, monkeypatch)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "outside.txt").write_text("outside-fixture", encoding="utf-8")
    try:
        (source / "assets" / "linked").symlink_to(external, target_is_directory=True)
        (source / "README.md").symlink_to(external / "outside.txt")
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    package_plugin.package(destination)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
    assert "deep-websearch/README.md" not in names
    assert not any("linked" in name or "outside.txt" in name for name in names)


def test_chatgpt_package_binds_verified_id_without_local_runtime(tmp_path, monkeypatch):
    source, destination = distribution_fixture(tmp_path, monkeypatch)
    manifest = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    manifest["description"] = "Private research plugin"
    manifest["extensions"] = {"com.openai": {"interface": {"displayName": "Deep Websearch"}}}
    (source / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / ".codex-plugin").mkdir()
    overlay = {"name": "deep-websearch", "version": "0.1.0", "mcpServers": "./.mcp.json"}
    (source / ".codex-plugin" / "plugin.json").write_text(json.dumps(overlay), encoding="utf-8")
    for name in ("mcp.json", ".mcp.json", "pyproject.toml", "config.example.yaml", ".env.example"):
        (source / name).write_text("local-only fixture", encoding="utf-8")
    (source / ".env.tunnel").write_text("CONTROL_PLANE_API_KEY=private-test-fixture\n", encoding="utf-8")
    for directory in ("src", "scripts", "tests", ".agents", ".github", "skills/research"):
        target = source / directory
        target.mkdir(parents=True)
        (target / "fixture.txt").write_text("fixture", encoding="utf-8")
    (source / "README.md").write_text("Local source setup and private connection guide", encoding="utf-8")
    (source / "LICENSE").write_text("MIT", encoding="utf-8")
    before = {name: (source / name).read_bytes() for name in ("plugin.json", ".codex-plugin/plugin.json")}
    app_id = "asdk_app_offline_test_fixture"
    package_plugin.package(destination, chatgpt_app_id=app_id)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        portable = json.loads(archive.read("deep-websearch/plugin.json"))
        compatibility = json.loads(archive.read("deep-websearch/.codex-plugin/plugin.json"))
        applications = json.loads(archive.read("deep-websearch/.app.json"))
    assert applications == {"apps": {"deep-websearch": {"id": app_id}}}
    assert portable["extensions"]["com.openai"]["apps"] == "./.app.json"
    assert compatibility["apps"] == "./.app.json"
    assert compatibility["skills"] == "./skills/"
    assert "mcpServers" not in compatibility
    assert portable["version"] == compatibility["version"] == manifest["version"]
    assert "deep-websearch/skills/research/fixture.txt" in names
    assert "deep-websearch/assets/icon.svg" in names
    assert not any(
        name.startswith(tuple(f"deep-websearch/{part}/" for part in ("src", "scripts", "tests", ".agents", ".github")))
        for name in names
    )
    assert not any(name.endswith(("mcp.json", "pyproject.toml", "config.example.yaml", ".env.example", ".env.tunnel"))
                   for name in names)
    assert before == {name: (source / name).read_bytes() for name in before}
    assert not (source / ".app.json").exists()


@pytest.mark.parametrize("app_id", ["", "deep-websearch", "https://mcp.example.test", "asdk_app_",
                                       "connector_value/../../", "asdk_app_value\n"])
def test_chatgpt_package_rejects_malformed_ids_without_writing(tmp_path, monkeypatch, app_id):
    _, destination = distribution_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="registered MCP application ID"):
        package_plugin.package(destination, chatgpt_app_id=app_id)
    assert not destination.exists()


def test_chatgpt_cli_default_output_is_separate(tmp_path, monkeypatch, capsys):
    source, _ = distribution_fixture(tmp_path, monkeypatch)
    local_archive = source.parent / "deep-websearch-0.1.0.zip"
    local_archive.write_bytes(b"existing-local-package-fixture")
    monkeypatch.setattr(sys, "argv", ["package_plugin.py", "--chatgpt-app-id", "connector_offline_fixture"])
    package_plugin.main()
    assert local_archive.read_bytes() == b"existing-local-package-fixture"
    assert (source.parent / "deep-websearch-0.1.0-chatgpt.zip").is_file()
    assert "deep-websearch-0.1.0-chatgpt.zip" in capsys.readouterr().out
