"""Run the official tunnel-client in the foreground for this local stdio MCP server."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

if __package__:
    from .runtime_paths import select_runtime, shared_home
else:
    from runtime_paths import select_runtime, shared_home

ROOT = Path(__file__).resolve().parents[1]


class LauncherError(Exception):
    """An actionable launcher error whose message never includes credentials."""


def load_environment(root: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    from dotenv import dotenv_values

    supplied = os.environ if environ is None else environ
    path = root / ".env.tunnel"
    values = dotenv_values(path, encoding="utf-8") if path.is_file() else {}
    environment = {name: value for name, value in values.items() if value is not None}
    environment.update(supplied)
    missing = [name for name in ("CONTROL_PLANE_API_KEY", "CONTROL_PLANE_TUNNEL_ID")
               if not environment.get(name, "").strip()]
    if missing:
        raise LauncherError("Configure " + " and ".join(missing) + " in .env.tunnel or the process environment.")
    return environment


def resolve_client(explicit: str | None, environment: Mapping[str, str]) -> Path:
    chosen = explicit or environment.get("DEEP_WEBSEARCH_TUNNEL_CLIENT")
    if chosen:
        candidate = Path(chosen).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        located = shutil.which(chosen, path=environment.get("PATH", ""))
        if located:
            return Path(located).resolve()
        raise LauncherError("Configured tunnel-client executable was not found.")
    located = shutil.which("tunnel-client", path=environment.get("PATH", ""))
    if located:
        return Path(located).resolve()
    tools = shared_home(environ=environment) / "tools" / "tunnel-client"
    versions = []
    if tools.is_dir():
        for directory in tools.glob("v*"):
            match = re.fullmatch(r"v(\d+(?:\.\d+)*)", directory.name)
            executable = directory / "tunnel-client.exe"
            if match and executable.is_file():
                version = tuple(int(part) for part in match.group(1).split("."))
                versions.append((version, executable))
    if versions:
        return max(versions, key=lambda item: item[0])[1].resolve()
    raise LauncherError("Install the official tunnel-client, or supply --client or DEEP_WEBSEARCH_TUNNEL_CLIENT.")


def validate_profile(path: Path, tunnel_id: str) -> None:
    import yaml

    try:
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        # Parser exceptions can contain source lines; never echo them.
        raise LauncherError("Unable to read the existing tunnel profile as valid YAML; it was preserved.") from None
    control = profile.get("control_plane") if isinstance(profile, dict) else None
    configured_id = control.get("tunnel_id") if isinstance(control, dict) else None
    if configured_id != tunnel_id:
        raise LauncherError("Existing profile tunnel_id does not match CONTROL_PLANE_TUNNEL_ID; "
                            "the profile was preserved. Select its matching configuration or another profile.")


def ensure_profile(client: Path, profile: str, directory: Path, runtime: Path,
                   environment: dict[str, str]) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile):
        raise LauncherError("Profile names must contain letters, digits, dots, underscores or hyphens.")
    path = directory / f"{profile}.yaml"
    tunnel_id = environment["CONTROL_PLANE_TUNNEL_ID"].strip()
    if path.exists() or path.is_symlink():
        validate_profile(path, tunnel_id)
        return path
    command = [str(client), "init", "--profile", profile, "--profile-dir", str(directory),
               "--tunnel-id", tunnel_id, "--control-plane-api-key-ref", "env:CONTROL_PLANE_API_KEY",
               "--mcp-command", shlex.join([str(runtime), str(ROOT / "scripts" / "run_server.py")]),
               "--health-listen-addr", "127.0.0.1:8767"]
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, shell=False,
                                capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        raise LauncherError("Tunnel profile initialization could not complete.") from None
    if result.returncode != 0:
        # Keep external command output private, including a failed init command.
        raise LauncherError("Tunnel profile initialization failed; check the official tunnel-client setup.")
    validate_profile(path, tunnel_id)
    return path


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    runtime, configuration_home = select_runtime(ROOT)
    current = os.path.normcase(os.path.abspath(sys.executable))
    selected = os.path.normcase(os.path.abspath(runtime))
    if runtime.is_file() and selected != current:
        os.execv(str(runtime), [str(runtime), str(Path(__file__).resolve()), *arguments])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "doctor"))
    parser.add_argument("--client", help="Path to an already installed official tunnel-client executable")
    parser.add_argument("--profile", default="deep-websearch", help="Named tunnel-client profile")
    parser.add_argument("--profile-dir", type=Path, help="Directory for persistent tunnel-client profiles")
    args = parser.parse_args(arguments)
    try:
        environment = load_environment(ROOT)
        environment.setdefault("DEEP_WEBSEARCH_HOME", str(configuration_home))
        client = resolve_client(args.client, environment)
        directory = (args.profile_dir or (shared_home(environ=environment) / "tunnel-profiles"))
        directory = directory.expanduser().resolve()
        ensure_profile(client, args.profile, directory, runtime, environment)
        command = [str(client), args.mode, "--profile", args.profile, "--profile-dir", str(directory)]
        # Foreground invocation: no shell, service, scheduled task, or API key CLI argument.
        return subprocess.run(command, cwd=ROOT, env=environment, shell=False, check=False).returncode
    except ImportError:
        print("Launcher dependencies are unavailable; run scripts/bootstrap.py first.", file=sys.stderr)
        return 2
    except LauncherError as error:
        print(str(error), file=sys.stderr)
        return 2
    except OSError:
        print("Unable to launch the installed tunnel-client executable.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
