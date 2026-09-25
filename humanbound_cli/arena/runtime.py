# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Docker runtime for arena agents, a thin wrapper over the `docker` CLI.

Stateless on purpose: running agents are found through container labels, so the CLI
and the gateway process always see the same picture. Secrets reach containers only
through a 0600 env file, never through argv.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from .keys import parse_env_file, write_env_file
from .manifest import ArenaManifest, Health
from .paths import arena_dir

LABEL_ID = "io.humanbound.arena.id"
LABEL_VERSION = "io.humanbound.arena.version"
LABEL_KIND = "io.humanbound.arena.kind"
LABEL_PORT = "io.humanbound.arena.port"
COMPOSE_FILE = "docker-compose.yml"
OVERRIDE_FILE = "arena.override.yml"

DOCKER_MISSING = (
    "Docker is required for hb arena. Install Docker Desktop: https://docs.docker.com/get-docker/"
)
DOCKER_DOWN = "Docker is installed but not running. Start Docker Desktop and retry."
COMPOSE_MISSING = "This agent needs Docker Compose v2 ('docker compose'). Update Docker Desktop."


class DockerError(RuntimeError):
    """A docker operation failed. The message is ready to show."""


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


def _run(argv: list[str], capture: bool) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=capture, text=True)


def _docker(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = _run(["docker", *args], capture)
    except FileNotFoundError:
        raise DockerError(DOCKER_MISSING) from None
    if check and proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:500]
        raise DockerError(f"'docker {' '.join(args[:2])}' failed: {detail}")
    return proc


def _compose_args(agent_id: str, agent_dir: Path | None) -> list[str]:
    args = ["compose", "-p", resource_name(agent_id)]
    env_file = run_env_file(agent_id)
    if env_file.exists():
        args += ["--env-file", str(env_file)]
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


def _write_override(m: ArenaManifest, agent_dir: Path) -> None:
    """Label the talked-to service and publish only its port, on loopback."""
    service = {
        "labels": {
            LABEL_ID: m.id,
            LABEL_VERSION: m.version,
            LABEL_KIND: "compose",
            LABEL_PORT: str(m.runtime.port),
        },
        "ports": [f"127.0.0.1::{m.runtime.port}"],
        "security_opt": ["no-new-privileges:true"],
    }
    doc = {"services": {m.source.service: service}}
    (agent_dir / OVERRIDE_FILE).write_text(yaml.safe_dump(doc, sort_keys=False))


def pull(m: ArenaManifest, agent_dir: Path) -> None:
    if m.source.image:
        _docker("pull", m.source.image, capture=False)
        return
    _write_override(m, agent_dir)
    _docker(*_compose_args(m.id, agent_dir), "pull", "--ignore-buildable", capture=False)


def list_running() -> list[RunningAgent]:
    ids = _docker("ps", "-q", "--filter", f"label={LABEL_ID}").stdout.split()
    if not ids:
        return []
    agents: dict[str, RunningAgent] = {}
    for container in json.loads(_docker("inspect", *ids).stdout):
        labels = (container.get("Config") or {}).get("Labels") or {}
        agent_id = labels.get(LABEL_ID)
        if not agent_id:
            continue
        port = labels.get(LABEL_PORT, "")
        ports = (container.get("NetworkSettings") or {}).get("Ports") or {}
        bindings = ports.get(f"{port}/tcp") or []
        host_port = next((int(b["HostPort"]) for b in bindings if b.get("HostPort")), None)
        agents[agent_id] = RunningAgent(
            agent_id, labels.get(LABEL_VERSION, ""), labels.get(LABEL_KIND, "image"), host_port
        )
    return sorted(agents.values(), key=lambda a: a.id)


def find_running(agent_id: str) -> RunningAgent | None:
    return next((a for a in list_running() if a.id == agent_id), None)


def start(m: ArenaManifest, agent_dir: Path, env: dict[str, str]) -> RunningAgent:
    """(Re)create the agent's containers. Call wait_healthy afterwards."""
    name = resource_name(m.id)
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
        _write_override(m, agent_dir)
        _docker(
            *_compose_args(m.id, agent_dir), "up", "-d", "--force-recreate", "--renew-anon-volumes"
        )
    agent = find_running(m.id)
    if agent is None or agent.host_port is None:
        raise DockerError(
            f"{m.id} started but port {m.runtime.port} is not published "
            f"→ check 'hb arena logs {m.id}'"
        )
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
        _docker(*_compose_args(agent_id, None), "down", "-v", "--remove-orphans", check=False)
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
        _docker(*_compose_args(agent_id, None), "logs", *extra, check=False, capture=False)
    else:
        _docker("logs", *extra, resource_name(agent_id), check=False, capture=False)


def last_logs(agent_id: str, kind: str, lines: int = 50) -> str:
    if kind == "compose":
        proc = _docker(*_compose_args(agent_id, None), "logs", "--tail", str(lines), check=False)
    else:
        proc = _docker("logs", "--tail", str(lines), resource_name(agent_id), check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def remove_images(m: ArenaManifest, agent_dir: Path) -> None:
    if m.source.image:
        _docker("rmi", m.source.image, check=False)
    else:
        _docker(*_compose_args(m.id, agent_dir), "down", "--rmi", "all", "-v", check=False)
