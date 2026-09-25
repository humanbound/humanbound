# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Docker runtime for arena agents, a thin wrapper over the `docker` CLI.

Stateless on purpose: running agents are found through container labels, so the CLI
and the gateway process always see the same picture. Secrets never travel through argv:
image agents get them from a 0600 `--env-file`; compose agents get them through the
compose process environment, and only for the names the manifest declares. hb's own
credentials (HB_*, HUMANBOUND_*) are stripped from every docker subprocess we give an
environment to.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

# DockerError, COMPOSE_FILE and check_compose live in compose_safety; re-exported here.
from .compose_safety import COMPOSE_FILE, DockerError, check_compose
from .keys import is_reserved, parse_env_file, write_env_file
from .manifest import ArenaManifest, Health
from .paths import arena_dir

LABEL_ID = "io.humanbound.arena.id"
LABEL_VERSION = "io.humanbound.arena.version"
LABEL_KIND = "io.humanbound.arena.kind"
LABEL_PORT = "io.humanbound.arena.port"
OVERRIDE_FILE = "arena.override.yml"

DOCKER_MISSING = (
    "Docker is required for hb arena. Install Docker Desktop: https://docs.docker.com/get-docker/"
)
DOCKER_DOWN = "Docker is installed but not running. Start Docker Desktop and retry."
COMPOSE_MISSING = "This agent needs Docker Compose v2 ('docker compose'). Update Docker Desktop."
# Bound on the docker calls behind list_running (the gateway polls it per request).
LIST_TIMEOUT_S = 15.0


class HealthTimeout(RuntimeError):
    """The agent did not pass its health check in time."""


@dataclass(frozen=True)
class RunningAgent:
    id: str
    version: str
    kind: str  # image | compose
    host_port: int | None

    @property
    def base_url(self) -> str | None:
        return f"http://127.0.0.1:{self.host_port}" if self.host_port else None


def resource_name(agent_id: str) -> str:
    return f"arena-{agent_id}"


def run_env_file(agent_id: str) -> Path:
    return arena_dir() / "run" / f"{agent_id}.env"


def kind_of(m: ArenaManifest) -> str:
    return "compose" if m.source.compose else "image"


def _run(
    argv: list[str],
    capture: bool,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=capture, text=True, env=env, timeout=timeout)


# Base env for compose subprocesses: only vars docker/compose themselves need (shell,
# locale, TLS, proxy, docker/compose config), never arbitrary host secrets that a
# compose file's ${VAR} interpolation could otherwise read (e.g. AWS_*, GITHUB_TOKEN).
_ENV_ALLOWLIST_EXACT = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "SystemRoot", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "COMSPEC", "PATHEXT", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY", "DOCKER_API_VERSION", "DOCKER_DEFAULT_PLATFORM",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
}  # fmt: skip
_ENV_ALLOWLIST_PREFIXES = ("COMPOSE_", "BUILDKIT_")


def _allowlisted(name: str) -> bool:
    return name in _ENV_ALLOWLIST_EXACT or name.startswith(_ENV_ALLOWLIST_PREFIXES)


def _subprocess_env(extra: dict[str, str]) -> dict[str, str]:
    """An allowlisted base environment (never arbitrary host secrets), plus `extra`."""
    base = {k: v for k, v in os.environ.items() if _allowlisted(k) and not is_reserved(k)}
    return {**base, **extra}


def _docker(
    *args: str,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run docker. With `env`, the process gets _subprocess_env(env) instead of ours."""
    try:
        proc = _run(
            ["docker", *args],
            capture,
            None if env is None else _subprocess_env(env),
            timeout=timeout,
        )
    except FileNotFoundError:
        raise DockerError(DOCKER_MISSING) from None
    except subprocess.TimeoutExpired:
        raise DockerError(
            f"'docker {' '.join(args[:2])}': docker did not respond within {timeout:g}s"
        ) from None
    if check and proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:500]
        prefix = f"'docker {' '.join(args[:2])}' failed"
        raise DockerError(f"{prefix}: {detail}" if detail else f"{prefix} (see the output above)")
    return proc


def _compose_args(agent_id: str, agent_dir: Path | None) -> list[str]:
    args = ["compose", "-p", resource_name(agent_id)]
    if agent_dir is not None:
        args += ["-f", str(agent_dir / COMPOSE_FILE), "-f", str(agent_dir / OVERRIDE_FILE)]
    return args


def preflight(m: ArenaManifest | None = None) -> None:
    if shutil.which("docker") is None:
        raise DockerError(DOCKER_MISSING)
    if _docker("info", "--format", "{{.ServerVersion}}", check=False).returncode != 0:
        raise DockerError(DOCKER_DOWN)
    if m is not None and m.source.compose:
        if _docker("compose", "version", check=False).returncode != 0:
            raise DockerError(COMPOSE_MISSING)


def image_present(image: str) -> bool:
    return _docker("image", "inspect", image, check=False).returncode == 0


def _declared(m: ArenaManifest) -> list[str]:
    return list(dict.fromkeys([*m.runtime.env.required, *m.runtime.env.optional]))


def _write_override(m: ArenaManifest, agent_dir: Path, services: list[str]) -> None:
    """Harden every service; label the talked-to one and publish only its port, on loopback.

    `environment` lists names only: compose fills them from its own process env, which
    start() sets. Values never touch disk here or argv.
    """
    hardening = {"cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]}
    doc: dict = {"services": {name: dict(hardening) for name in services}}
    doc["services"][m.source.service] = {
        "labels": {
            LABEL_ID: m.id,
            LABEL_VERSION: m.version,
            LABEL_KIND: "compose",
            LABEL_PORT: str(m.runtime.port),
        },
        "ports": [f"127.0.0.1::{m.runtime.port}"],
        **hardening,
        "environment": _declared(m),
    }
    (agent_dir / OVERRIDE_FILE).write_text(yaml.safe_dump(doc, sort_keys=False))


def pull(m: ArenaManifest, agent_dir: Path) -> None:
    if m.source.image:
        _docker("pull", m.source.image, capture=False)
        return
    _write_override(m, agent_dir, check_compose(m, agent_dir))
    _docker(*_compose_args(m.id, agent_dir), "pull", "--ignore-buildable", capture=False, env={})


def list_running() -> list[RunningAgent]:
    ids = _docker(
        "ps", "-q", "--filter", f"label={LABEL_ID}", timeout=LIST_TIMEOUT_S
    ).stdout.split()
    if not ids:
        return []
    # A container can vanish between ps and inspect: inspect then exits 1 but still
    # prints the ones it found.
    out = (_docker("inspect", *ids, check=False, timeout=LIST_TIMEOUT_S).stdout or "").strip()
    try:
        containers = json.loads(out) if out else []
    except json.JSONDecodeError:
        containers = []
    if not isinstance(containers, list):
        containers = []
    agents: dict[str, RunningAgent] = {}
    for container in containers:
        if not isinstance(container, dict):
            continue
        labels = (container.get("Config") or {}).get("Labels") or {}
        agent_id = labels.get(LABEL_ID)
        if not agent_id:
            continue
        port = labels.get(LABEL_PORT, "")
        ports = (container.get("NetworkSettings") or {}).get("Ports") or {}
        bindings = ports.get(f"{port}/tcp") or []
        host_port = next(
            (int(b["HostPort"]) for b in bindings if str(b.get("HostPort", "")).isdigit()), None
        )
        agents[agent_id] = RunningAgent(
            agent_id, labels.get(LABEL_VERSION, ""), labels.get(LABEL_KIND, "image"), host_port
        )
    return sorted(agents.values(), key=lambda a: a.id)


def find_running(agent_id: str) -> RunningAgent | None:
    return next((a for a in list_running() if a.id == agent_id), None)


def start(m: ArenaManifest, agent_dir: Path, env: dict[str, str]) -> RunningAgent:
    """(Re)create the agent's containers. Call wait_healthy afterwards."""
    name = resource_name(m.id)
    declared = _declared(m)
    env = {k: v for k, v in env.items() if k in declared and not is_reserved(k)}
    services = [] if m.source.image else check_compose(m, agent_dir)
    env_file = run_env_file(m.id)
    write_env_file(env_file, env)
    if m.source.image:
        _docker("rm", "-f", "-v", name, check=False)
        if _docker("network", "inspect", name, check=False).returncode != 0:
            _docker("network", "create", name)
        _docker(
            "run", "-d", "--name", name,
            "--label", f"{LABEL_ID}={m.id}",
            "--label", f"{LABEL_VERSION}={m.version}",
            "--label", f"{LABEL_KIND}=image",
            "--label", f"{LABEL_PORT}={m.runtime.port}",
            "--network", name,
            "-p", f"127.0.0.1::{m.runtime.port}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--env-file", str(env_file),
            m.source.image,
        )  # fmt: skip
    else:
        _write_override(m, agent_dir, services)
        _docker(
            *_compose_args(m.id, agent_dir),
            "up", "-d", "--force-recreate", "--renew-anon-volumes",
            env=env,
        )  # fmt: skip
    agent = find_running(m.id)
    if agent is None or agent.host_port is None:
        message = f"{m.id} started but port {m.runtime.port} is not published"
        # Grab the logs before cleaning up (they go with the containers). Both steps are
        # best effort: the port error is what the user needs to see.
        with contextlib.suppress(Exception):
            tail = last_logs(m.id, kind_of(m), lines=20).strip()
            if tail:
                message += f". Last logs:\n{tail}"
        with contextlib.suppress(Exception):
            stop(m.id, kind_of(m))
        raise DockerError(message)
    return agent


def wait_healthy(
    agent: RunningAgent,
    health: Health,
    *,
    get: Callable[..., httpx.Response] = httpx.get,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    url = f"{agent.base_url}{health.path}"
    deadline = clock() + health.timeout_s
    while True:
        try:
            if get(url, timeout=2).is_success:
                return
        except httpx.HTTPError:
            pass
        if clock() >= deadline:
            raise HealthTimeout(f"{agent.id} did not become healthy within {health.timeout_s}s")
        sleep(1)


def stop(agent_id: str, kind: str) -> None:
    name = resource_name(agent_id)
    if kind == "compose":
        _docker(
            *_compose_args(agent_id, None), "down", "-v", "--remove-orphans", check=False, env={}
        )
    else:
        _docker("rm", "-f", "-v", name, check=False)
        _docker("network", "rm", name, check=False)
    run_env_file(agent_id).unlink(missing_ok=True)


def reset(m: ArenaManifest, agent_dir: Path) -> RunningAgent:
    """Recreate from the image (clean state), with the same env as the last start."""
    env_file = run_env_file(m.id)
    env = parse_env_file(env_file) if env_file.exists() else {}
    stop(m.id, kind_of(m))
    agent = start(m, agent_dir, env)
    wait_healthy(agent, m.runtime.health)
    return agent


def logs(agent_id: str, kind: str, *, follow: bool = False, tail: int = 200) -> None:
    extra = ["--tail", str(tail)] + (["-f"] if follow else [])
    if kind == "compose":
        _docker(*_compose_args(agent_id, None), "logs", *extra, check=False, capture=False, env={})
    else:
        _docker("logs", *extra, resource_name(agent_id), check=False, capture=False)


def last_logs(agent_id: str, kind: str, lines: int = 50) -> str:
    if kind == "compose":
        proc = _docker(
            *_compose_args(agent_id, None), "logs", "--tail", str(lines), check=False, env={}
        )
    else:
        proc = _docker("logs", "--tail", str(lines), resource_name(agent_id), check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def remove_images(m: ArenaManifest, agent_dir: Path) -> None:
    if m.source.image:
        _docker("rmi", m.source.image, check=False)
    else:
        _docker(*_compose_args(m.id, agent_dir), "down", "--rmi", "all", "-v", check=False, env={})
