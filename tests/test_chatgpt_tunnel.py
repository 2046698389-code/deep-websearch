"""Offline launcher regressions for credentials, quoting, and profile preservation."""

import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from scripts import chatgpt_tunnel


def environment(**extra):
    return {"CONTROL_PLANE_API_KEY": "private-fixture-key",
            "CONTROL_PLANE_TUNNEL_ID": "tunnel_fixture_id", **extra}


def write_profile(path, tunnel_id="tunnel_fixture_id"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"control_plane": {
        "tunnel_id": tunnel_id, "api_key": "env:CONTROL_PLANE_API_KEY",
    }, "health": {"listen_addr": "127.0.0.1:9000"}}), encoding="utf-8")


def test_dotenv_loading_preserves_process_environment_precedence(tmp_path):
    (tmp_path / ".env.tunnel").write_text(
        "CONTROL_PLANE_API_KEY=file-fixture-key\nCONTROL_PLANE_TUNNEL_ID=tunnel_file\n",
        encoding="utf-8",
    )
    loaded = chatgpt_tunnel.load_environment(tmp_path, {"CONTROL_PLANE_API_KEY": "env-fixture-key"})
    assert loaded["CONTROL_PLANE_API_KEY"] == "env-fixture-key"
    assert loaded["CONTROL_PLANE_TUNNEL_ID"] == "tunnel_file"


def test_missing_key_does_not_launch_or_echo_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(chatgpt_tunnel, "ROOT", tmp_path)
    monkeypatch.setattr(chatgpt_tunnel, "select_runtime", lambda root: (Path(sys.executable), root))
    monkeypatch.setattr(chatgpt_tunnel.os, "environ", {"CONTROL_PLANE_TUNNEL_ID": "private-fixture-id"})
    def never(*args, **kwargs):
        pytest.fail("missing runtime key must stop before the client is invoked")
    monkeypatch.setattr(chatgpt_tunnel.subprocess, "run", never)
    assert chatgpt_tunnel.main(["doctor"]) == 2
    output = capsys.readouterr()
    assert "CONTROL_PLANE_API_KEY" in output.err
    assert "private-fixture-id" not in output.out + output.err


def test_existing_profile_is_preserved_and_client_arguments_are_safe(tmp_path, monkeypatch):
    root = tmp_path / "plugin with spaces"
    root.mkdir()
    profile_dir = tmp_path / "profiles with spaces"
    profile_path = profile_dir / "deep-websearch.yaml"
    write_profile(profile_path)
    before = profile_path.read_bytes()
    executable = tmp_path / "client with spaces.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(chatgpt_tunnel, "ROOT", root)
    monkeypatch.setattr(chatgpt_tunnel, "select_runtime", lambda root: (Path(sys.executable), root))
    monkeypatch.setattr(chatgpt_tunnel.os, "environ", environment())
    calls = []
    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(chatgpt_tunnel.subprocess, "run", invoke)
    assert chatgpt_tunnel.main(["doctor", "--client", str(executable),
                              "--profile-dir", str(profile_dir)]) == 0
    assert profile_path.read_bytes() == before
    assert len(calls) == 1
    command, options = calls[0]
    assert command == [str(executable.resolve()), "doctor", "--profile", "deep-websearch",
                       "--profile-dir", str(profile_dir.resolve())]
    assert options["shell"] is False
    assert options["env"]["CONTROL_PLANE_API_KEY"] == "private-fixture-key"
    assert "private-fixture-key" not in " ".join(command)


def test_profile_mismatch_is_rejected_without_values_or_mutation(tmp_path, monkeypatch, capsys):
    root = tmp_path / "plugin"
    root.mkdir()
    directory = tmp_path / "profiles"
    path = directory / "deep-websearch.yaml"
    write_profile(path, tunnel_id="private-old-fixture-id")
    before = path.read_bytes()
    client = tmp_path / "client.exe"
    client.write_bytes(b"fixture")
    monkeypatch.setattr(chatgpt_tunnel, "ROOT", root)
    monkeypatch.setattr(chatgpt_tunnel, "select_runtime", lambda root: (Path(sys.executable), root))
    monkeypatch.setattr(chatgpt_tunnel.os, "environ", environment())
    def never(*args, **kwargs):
        pytest.fail("mismatched profile must not initialize or launch the client")
    monkeypatch.setattr(chatgpt_tunnel.subprocess, "run", never)
    assert chatgpt_tunnel.main(["run", "--client", str(client), "--profile-dir", str(directory)]) == 2
    output = capsys.readouterr()
    assert "private-old-fixture-id" not in output.out + output.err
    assert "tunnel_fixture_id" not in output.out + output.err
    assert "private-fixture-key" not in output.out + output.err
    assert path.read_bytes() == before


def test_new_profile_init_quotes_mcp_command_and_uses_environment_reference(tmp_path, monkeypatch):
    root = tmp_path / "plugin with spaces"
    root.mkdir()
    directory = tmp_path / "profile directory"
    runtime = tmp_path / "runtime with spaces" / "python.exe"
    client = tmp_path / "client.exe"
    calls = []
    monkeypatch.setattr(chatgpt_tunnel, "ROOT", root)
    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        write_profile(directory / "deep-websearch.yaml")
        return subprocess.CompletedProcess(command, 0, stdout="private-fixture-key", stderr="")
    monkeypatch.setattr(chatgpt_tunnel.subprocess, "run", invoke)
    path = chatgpt_tunnel.ensure_profile(client, "deep-websearch", directory, runtime, environment())
    assert path == directory / "deep-websearch.yaml"
    command, options = calls[0]
    assert "--force" not in command
    assert "private-fixture-key" not in " ".join(command)
    assert command[command.index("--control-plane-api-key-ref") + 1] == "env:CONTROL_PLANE_API_KEY"
    assert command[command.index("--tunnel-id") + 1] == "tunnel_fixture_id"
    assert command[command.index("--health-listen-addr") + 1] == "127.0.0.1:8767"
    assert shlex.split(command[command.index("--mcp-command") + 1]) == [
        str(runtime), str(root / "scripts" / "run_server.py"),
    ]
    assert options["shell"] is False
    assert options["capture_output"] is True


def test_invalid_yaml_error_does_not_echo_source_lines(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("control_plane: [\napi_key: private-fixture-key\n", encoding="utf-8")
    with pytest.raises(chatgpt_tunnel.LauncherError) as error:
        chatgpt_tunnel.validate_profile(path, "tunnel_fixture_id")
    assert "private-fixture-key" not in str(error.value)


def test_resolve_client_priority_and_newest_numeric_version(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    monkeypatch.setattr(chatgpt_tunnel, "shared_home", lambda **kwargs: storage)
    monkeypatch.setattr(chatgpt_tunnel.shutil, "which", lambda name, path=None: None)
    executables = {}
    for version in ("v0.0.9", "v0.0.15", "v0.0.15-preview", "v0.0.8"):
        executable = storage / "tools" / "tunnel-client" / version / "tunnel-client.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fixture")
        executables[version] = executable
    assert chatgpt_tunnel.resolve_client(None, {}) == executables["v0.0.15"]
    explicit = tmp_path / "explicit.exe"
    explicit.write_bytes(b"fixture")
    path_client = tmp_path / "path.exe"
    path_client.write_bytes(b"fixture")
    monkeypatch.setattr(chatgpt_tunnel.shutil, "which", lambda name, path=None: str(path_client))
    assert chatgpt_tunnel.resolve_client(str(explicit), {}) == explicit
    assert chatgpt_tunnel.resolve_client(None, {"DEEP_WEBSEARCH_TUNNEL_CLIENT": str(explicit)}) == explicit
    assert chatgpt_tunnel.resolve_client(None, {}) == path_client


def test_nonzero_init_output_is_private_and_existing_partial_profile_is_not_replaced(tmp_path, monkeypatch):
    directory = tmp_path / "profiles"
    path = directory / "deep-websearch.yaml"
    def invoke(command, **kwargs):
        write_profile(path)
        return subprocess.CompletedProcess(command, 1, stdout="private-fixture-key", stderr="tunnel_fixture_id")
    monkeypatch.setattr(chatgpt_tunnel.subprocess, "run", invoke)
    with pytest.raises(chatgpt_tunnel.LauncherError) as error:
        chatgpt_tunnel.ensure_profile(Path("client.exe"), "deep-websearch", directory,
                                    Path(sys.executable), environment())
    assert "private-fixture-key" not in str(error.value)
    assert "tunnel_fixture_id" not in str(error.value)
    assert path.is_file()
