# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Docker runtime for arena agents, a thin wrapper over the `docker` CLI.

Stateless on purpose: running agents are found through container labels, so the CLI
and the gateway process always see the same picture. Everything is scoped to an owner
(paths.arena_owner(), one per arena dir), so several HOMEs sharing one Docker daemon
never see, replace or stop each other's agents. Secrets never go through argv:
image agents get a 0600 --env-file; compose agents get key *names* in an override and
the values through an allowlisted subprocess environment. `docker compose` always gets its
files and project directory explicitly, so it never reads a compose file from the current
directory; without the agent's compose file, its project is removed by label instead.

Network: an agent's networks have no route out (`--internal`), so an agent can reach its own
services and nothing else, not even the host. Next to each agent hb runs a door (door.py), a
small container of its own on the agent's networks and on one ordinary network: it carries
calls from 127.0.0.1 on the host in to the agent, and is the HTTP proxy the agent's
containers are pointed at, which lets through the destinations of egress.py only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

import httpx
import yaml

from . import baseline, egress
from . import door as door_program
from .baseline import BaselineError, Violation
from .catalog import ImagePin, read_provenance, repository_of
from .compose_safety import (
    COMPOSE_FILE,
    DockerError,
    check_compose,
    checked_services,
    network_names,
)
from .keys import is_reserved, parse_env_file, write_env_file
from .manifest import AGENT_ID_RE, ArenaManifest, Health, has_control_chars
from .paths import arena_dir, arena_owner

__all__ = [
    "COMPOSE_FILE",
    "DOOR_IMAGE",
    "BaselineError",
    "DockerError",
    "DockerInfo",
    "HealthTimeout",
    "ImageMismatch",
    "RunningAgent",
    "agent_containers",
    "agent_networks",
    "allowed_destinations",
    "check_baseline",
    "check_compose",
    "checked_services",
    "door_logs",
    "find_running",
    "image_present",
    "kind_of",
    "last_logs",
    "legacy_agents",
    "list_running",
    "logs",
    "loopback_ports_exposed",
    "preflight",
    "pull",
    "published_images",
    "pull_door_image",
    "refused_destinations",
    "remove_doors",
    "remove_images",
    "reset",
    "resource_name",
    "run_env_file",
    "start",
    "stop",
    "wait_healthy",
]

LABEL_ID = "io.humanbound.arena.id"
LABEL_VERSION = "io.humanbound.arena.version"
LABEL_KIND = "io.humanbound.arena.kind"
LABEL_PORT = "io.humanbound.arena.port"
LABEL_OWNER = "io.humanbound.arena.owner"
LABEL_SERVICE = "io.humanbound.arena.service"  # compose: the talked-to service
LABEL_DOOR = "io.humanbound.arena.door"  # on a door's container: the id of its agent
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
KINDS = ("image", "compose")

# The image the door runs in: the official Python image, by digest. The door needs a Python
# interpreter and nothing else.
DOOR_IMAGE = (
    "python:3.13-alpine@sha256:79e7a9b9ff1cbceff819f856fb374477792a5967759d94df266de7b7b4120e6f"
)
DOOR_USER = "65534:65534"
DOOR_PIDS_LIMIT = 128
DOOR_MEMORY_LIMIT = "256m"
DOOR_CPU_LIMIT = 1
HOST_GATEWAY_NAME = "host.docker.internal"
# Without an address on the bridge, the Docker host can't be reached through a network's
# gateway address either. Not every Docker knows the option.
NO_BRIDGE_ADDRESS = "com.docker.network.bridge.inhibit_ipv4"
# Containment for every agent container (compose services keep lower limits of their own).
PIDS_LIMIT = 512
MEMORY_LIMIT = "2g"
CPU_LIMIT = 2
MAX_NAME_LEN = 63
OVERRIDE_FILE = "arena.override.yml"
LIST_TIMEOUT_S = 15.0

DOCKER_MISSING = (
    "Docker is required for hb arena, and 'docker' is not on your PATH. Install Docker "
    "Desktop (https://docs.docker.com/get-docker/) or, on Linux, Docker Engine "
    "(https://docs.docker.com/engine/install/)."
)
COMPOSE_MISSING = (
    "This agent needs Docker Compose v2 ('docker compose'). Update Docker Desktop or, on "
    "Linux with Docker Engine, install the compose plugin (e.g. the docker-compose-plugin "
    "package: https://docs.docker.com/compose/install/linux/)."
)
# Docker Engine before 28 on Linux: a port published on 127.0.0.1 can be reached from other
# machines on the local network (they can route to it through the host).
LOOPBACK_SAFE_ENGINE = 28


def _is_linux(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith("linux")


def docker_down_message(platform: str | None = None) -> str:
    if _is_linux(platform):
        return (
            "Docker is installed but its daemon is not running. Start it (Docker Engine: "
            "sudo systemctl start docker; Docker Desktop: start the app) and retry."
        )
    return "Docker is installed but not running. Start Docker Desktop and retry."


def docker_permission_message(platform: str | None = None) -> str:
    base = "Docker is running, but hb got permission denied on the Docker socket."
    if _is_linux(platform):
        return (
            f"{base} Add your user to the docker group (sudo usermod -aG docker $USER, then "
            "log out and in again), or for rootless Docker set "
            "DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock."
        )
    return f"{base} Make sure Docker Desktop is running for your user, then retry."


DOCKER_DOWN = docker_down_message()

# What `docker compose` needs to find the daemon and reach registries on every OS.
# Nothing else from the user's shell is passed, so ${VAR} interpolation in a compose
# file can't read host secrets (cloud credentials, tokens, hb's own keys).
_ENV_ALLOWLIST_EXACT = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "COMSPEC",
        "PATHEXT",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
        "DOCKER_API_VERSION",
        "DOCKER_DEFAULT_PLATFORM",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        # Harmless compose/buildkit tuning only. Never COMPOSE_FILE, COMPOSE_PROFILES,
        # COMPOSE_ENV_FILES, COMPOSE_PROJECT_NAME and the like: they change what compose runs.
        "COMPOSE_HTTP_TIMEOUT",
        "COMPOSE_PARALLEL_LIMIT",
        "COMPOSE_ANSI",
        "BUILDKIT_PROGRESS",
    }
)


class HealthTimeout(RuntimeError):
    """The agent did not pass its health check in time."""


@dataclass(frozen=True)
class DockerInfo:
    server_version: str  # e.g. "27.5.1"; "" if Docker didn't say
    operating_system: str  # e.g. "Ubuntu 24.04 LTS" or "Docker Desktop"


def loopback_ports_exposed(info: DockerInfo) -> bool:
    """Docker Engine < 28 on Linux (not Docker Desktop, which runs in a VM): other machines
    on the local network may reach ports published on 127.0.0.1. False when unsure."""
    if not _is_linux() or "docker desktop" in info.operating_system.lower():
        return False
    major = info.server_version.split(".", 1)[0]
    return major.isdigit() and int(major) < LOOPBACK_SAFE_ENGINE


@dataclass(frozen=True)
class RunningAgent:
    id: str
    version: str
    kind: str  # image | compose
    host_port: int | None
    # Who started it (paths.arena_owner()); "" for containers from before owners existed.
    owner: str = field(default="", compare=False)
    # The container name (image) or compose project (compose) Docker reports: what `stop`
    # uses for another owner's or a legacy agent instead of recomputing it.
    name: str = field(default="", compare=False)
    # Set by start() only: this Docker could not take the gateway address off the agent's
    # networks, so the agent may reach what the Docker host serves on all interfaces.
    gateway_reachable: bool = field(default=False, compare=False)

    @property
    def base_url(self) -> str | None:
        return f"http://127.0.0.1:{self.host_port}" if self.host_port else None


# ── process plumbing (tests replace _run) ──


def _run(
    argv: list[str], capture: bool, env: dict[str, str] | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess:
    # Docker's output is UTF-8; an image's logs may hold anything: never fail on decoding.
    return subprocess.run(
        argv,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def _docker(
    *args: str,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    try:
        result = _run(["docker", *args], capture, env=env, timeout=timeout)
    except FileNotFoundError:
        raise DockerError(DOCKER_MISSING) from None
    except subprocess.TimeoutExpired:
        raise DockerError(f"docker did not respond within {timeout:g}s") from None
    if check and result.returncode != 0:
        words = [a for a in args[:3] if not a.startswith("-")][:2]
        what = " ".join(["docker", *words])
        detail = (result.stderr or "").strip() if capture else ""
        if detail:
            raise DockerError(f"{what} failed: {detail}")
        raise DockerError(f"{what} failed (see the output above)")
    return result


def _subprocess_env(agent_env: dict[str, str], declared: Iterable[str] = ()) -> dict[str, str]:
    """Allowlisted host env plus the agent's keys.

    Names the manifest declares never come from the host: a compose file may reference
    them as ${NAME}, so an unset declared key must stay unset rather than fall through to
    the user's own value (e.g. a manifest declaring HTTPS_PROXY or HOME).
    """
    skip = set(declared)
    base = {
        k: v
        for k, v in os.environ.items()
        if k in _ENV_ALLOWLIST_EXACT and not is_reserved(k) and k not in skip
    }
    return base | agent_env


# ── naming ──


def resource_name(agent_id: str, owner: str | None = None) -> str:
    """Container, network and compose project name: arena-<owner>-<id>, at most 63 chars.

    `owner` defaults to this arena's owner; "" gives the pre-owner name arena-<id> (used
    only to clean up old containers). A too-long id is cut and suffixed with "_" and a hash
    of the full id ("_" never appears in an id, so a cut name can't equal a full one), so
    two long ids with a shared prefix still get different names; the id label stays the
    authority on which agent a container is.
    """
    owner = arena_owner() if owner is None else owner
    prefix = f"arena-{owner}-" if owner else "arena-"
    name = prefix + agent_id
    if len(name) <= MAX_NAME_LEN:
        return name
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:8]
    keep = MAX_NAME_LEN - len(prefix) - len(digest) - 1
    return f"{prefix}{agent_id[:keep].rstrip('-')}_{digest}"


def door_name(name: str) -> str:
    """The door's container of the agent whose resources are called `name`. "_" never ends
    a resource name this way, so it is never another agent's name."""
    return f"{name}_door"


def outside_network(name: str) -> str:
    """The ordinary network of that agent's door (the door is the only container on it)."""
    return f"{name}_out"


def run_env_file(agent_id: str) -> Path:
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
        raise ValueError(f"invalid agent id {agent_id!r}")
    return arena_dir() / "run" / f"{agent_id}.env"


def kind_of(m: ArenaManifest) -> str:
    return "compose" if m.source.compose else "image"


def _declared(m: ArenaManifest) -> list[str]:
    return [*m.runtime.env.required, *m.runtime.env.optional]


# ── checks ──


def docker_cli() -> str | None:
    """Where the docker CLI is, or None when it isn't on PATH."""
    return shutil.which("docker")


def preflight(m: ArenaManifest | None = None) -> DockerInfo:
    """Docker is usable (and, for a compose agent, compose v2 is there); what the daemon is."""
    if docker_cli() is None:
        raise DockerError(DOCKER_MISSING)
    try:
        info = _docker(
            "info",
            "--format",
            "{{.ServerVersion}}|{{.OperatingSystem}}",
            check=False,
            timeout=LIST_TIMEOUT_S,
        )
    except DockerError as e:
        if str(e) == DOCKER_MISSING:
            raise
        raise DockerError(docker_down_message()) from None
    version, _, system = (info.stdout or "").strip().partition("|")
    # Some docker CLIs exit 0 when the daemon is unreachable and leave the server fields
    # empty, so a missing server version counts as unusable too.
    if info.returncode != 0 or not version.strip():
        if "permission denied" in (info.stderr or "").lower():
            raise DockerError(docker_permission_message())
        raise DockerError(docker_down_message())
    if m is not None and m.source.compose:
        if _docker("compose", "version", check=False, timeout=LIST_TIMEOUT_S).returncode != 0:
            raise DockerError(COMPOSE_MISSING)
    return DockerInfo(version.strip(), system.strip())


def image_present(image: str) -> bool:
    return _docker("image", "inspect", image, check=False).returncode == 0


# ── discovery ──


def _host_port(container: dict, port: str | None) -> tuple[bool, int | None]:
    """(ok, host_port). ok is False when a binding exists but its HostPort is malformed."""
    ports = (container.get("NetworkSettings") or {}).get("Ports") or {}
    if not isinstance(ports, dict) or not port:
        return True, None
    bindings = ports.get(f"{port}/tcp") or []
    if not isinstance(bindings, list) or not bindings:
        return True, None
    for binding in bindings:
        try:
            host_port = int(binding.get("HostPort"))
        except (AttributeError, TypeError, ValueError):
            return False, None
        if 0 < host_port < 65536:
            return True, host_port
        return False, None
    return True, None


def list_running(*, include_stopped: bool = False, any_owner: bool = False) -> list[RunningAgent]:
    """This owner's arena agents with a running container. `include_stopped` adds stopped or
    exited ones (a crash, `docker stop`, a Docker restart), which still need `stop` to clean
    them up. `any_owner` lists every owner's agents (and pre-owner ones) on this Docker."""
    every = ("-a",) if include_stopped else ()
    owner = None if any_owner else arena_owner()
    filters = ["--filter", f"label={LABEL_ID}"]
    if owner is not None:
        filters += ["--filter", f"label={LABEL_OWNER}={owner}"]
    ps = _docker("ps", *every, "-q", *filters, timeout=LIST_TIMEOUT_S)
    ids = ps.stdout.split()
    if not ids:
        return []
    # check=False: a container that vanished between ps and inspect makes rc=1, but
    # the others are still printed.
    inspected = _docker("inspect", *ids, check=False, timeout=LIST_TIMEOUT_S)
    data: object = []
    if (inspected.stdout or "").strip():
        try:
            data = json.loads(inspected.stdout)
        except ValueError:
            data = []
    if not isinstance(data, list):
        data = []
    agents = []
    doors: dict[tuple[str, str], int | None] | None = None
    for container in data:
        if not isinstance(container, dict):
            continue
        labels = (container.get("Config") or {}).get("Labels") or {}
        if not isinstance(labels, dict) or not _is_agent(labels):
            continue
        container_owner = labels.get(LABEL_OWNER) or ""
        if owner is not None and container_owner != owner:
            continue
        # The way in is the door's port: the agent's networks can't publish one.
        if doors is None:
            doors = _door_ports(owner)
        host_port = doors.get((container_owner, labels[LABEL_ID]))
        kind = labels[LABEL_KIND]
        if kind == "compose":
            name = labels.get(COMPOSE_PROJECT_LABEL) or ""
        else:
            name = str(container.get("Name") or "").lstrip("/")
        agents.append(
            RunningAgent(
                id=labels[LABEL_ID],
                version=labels.get(LABEL_VERSION, ""),
                kind=kind,
                host_port=host_port,
                owner=container_owner,
                name=name,
            )
        )
    return agents


def _inspect_all(ids: list[str]) -> list[dict]:
    """`docker inspect` data of `ids` (the objects only); [] when it can't be read."""
    if not ids:
        return []
    # check=False: an object that vanished since it was listed makes rc=1, but the others
    # are still printed.
    inspected = _docker("inspect", *ids, check=False, timeout=LIST_TIMEOUT_S)
    try:
        data = json.loads(inspected.stdout or "")
    except ValueError:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _doors(owner: str | None, *, include_stopped: bool = False) -> list[dict]:
    """Inspect data of the door containers of `owner` (None: of every owner)."""
    every = ("-a",) if include_stopped else ()
    filters = ["--filter", f"label={LABEL_DOOR}"]
    if owner is not None:
        filters += ["--filter", f"label={LABEL_OWNER}={owner}"]
    ids = _docker("ps", *every, "-q", *filters, timeout=LIST_TIMEOUT_S).stdout.split()
    found = []
    for container in _inspect_all(ids):
        labels = (container.get("Config") or {}).get("Labels") or {}
        if not isinstance(labels, dict):
            continue
        # An agent's own containers carry the label too, empty: only a door names an agent.
        agent_id = labels.get(LABEL_DOOR)
        if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
            continue
        if _is_agent(labels) or COMPOSE_PROJECT_LABEL in labels:
            continue
        if owner is not None and labels.get(LABEL_OWNER) != owner:
            continue
        found.append(container)
    return found


def _door_ports(owner: str | None) -> dict[tuple[str, str], int | None]:
    """{(owner, agent id): the port on 127.0.0.1 of the agent's running door}."""
    ports: dict[tuple[str, str], int | None] = {}
    for container in _doors(owner):
        labels = container["Config"]["Labels"]
        ok, host_port = _host_port(container, str(door_program.IN_PORT))
        ports[(labels.get(LABEL_OWNER) or "", labels[LABEL_DOOR])] = host_port if ok else None
    return ports


def _is_agent(labels: dict) -> bool:
    """A container hb started as an agent: a valid id, a known kind and a real port; for
    compose, the service hb labelled (sidecars get empty arena labels in the override)."""
    agent_id, kind, port = labels.get(LABEL_ID), labels.get(LABEL_KIND), labels.get(LABEL_PORT)
    if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
        return False
    if kind not in KINDS or not isinstance(port, str) or not re.fullmatch(r"[0-9]{1,5}", port):
        return False
    if not 1 <= int(port) <= 65535:
        return False
    if kind == "compose":
        service = labels.get(COMPOSE_SERVICE_LABEL)
        if not service:
            return False
        labelled = labels.get(LABEL_SERVICE)  # missing on containers from an older hb
        if labelled is not None and labelled != service:
            return False
    return True


def legacy_agents() -> list[RunningAgent]:
    """Arena agents from an hb before owners existed (no owner label), running or not."""
    return [a for a in list_running(include_stopped=True, any_owner=True) if not a.owner]


def find_running(agent_id: str, *, include_stopped: bool = False) -> RunningAgent | None:
    agents = list_running(include_stopped=include_stopped)
    return next((a for a in agents if a.id == agent_id), None)


# ── container baseline ──


def agent_containers(agent_id: str) -> list[dict]:
    """`docker inspect` data of every container of this owner's agent, running or not: an
    image agent's container, or every container of a compose agent's project (side services
    included). Raises DockerError when Docker fails or the inspect output can't be read."""
    owner = arena_owner()
    project = resource_name(agent_id)
    listing = ("ps", "-a", "-q", "--no-trunc")
    ids = _ids(*listing, "--filter", f"label={LABEL_ID}={agent_id}",
               "--filter", f"label={LABEL_OWNER}={owner}")  # fmt: skip
    ids += _ids(*listing, "--filter", _project_label(project))
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    # check=False: a container that vanished between ps and inspect makes rc=1, but the
    # others are still printed.
    inspected = _docker("inspect", *ids, check=False, timeout=LIST_TIMEOUT_S)
    try:
        data = json.loads(inspected.stdout or "")
    except ValueError:
        data = None
    if not isinstance(data, list):
        detail = (inspected.stderr or "").strip() or "unreadable output"
        raise DockerError(f"docker inspect failed: {detail}")
    mine = []
    for container in data:
        labels = (
            (container.get("Config") or {}).get("Labels") if isinstance(container, dict) else None
        )
        if not isinstance(labels, dict):
            continue
        own = labels.get(LABEL_ID) == agent_id and labels.get(LABEL_OWNER) == owner
        if own or labels.get(COMPOSE_PROJECT_LABEL) == project:
            mine.append(container)
    return mine


def agent_networks(containers: list[dict]) -> list[dict]:
    """`docker network inspect` data of every network those containers are attached to.
    Whatever can't be read is left out (the baseline then can't confirm that network)."""
    names: dict[str, None] = {}
    for container in containers:
        settings = container.get("NetworkSettings") if isinstance(container, dict) else None
        attached = settings.get("Networks") if isinstance(settings, dict) else None
        for name in attached if isinstance(attached, dict) else ():
            if isinstance(name, str) and name and not name.startswith("-"):
                names[name] = None
    if not names:
        return []
    inspected = _docker("network", "inspect", *names, check=False, timeout=LIST_TIMEOUT_S)
    try:
        data = json.loads(inspected.stdout or "")
    except ValueError:
        return []
    return [net for net in data if isinstance(net, dict)] if isinstance(data, list) else []


def check_baseline(agent_id: str) -> list[Violation]:
    """The container baseline violations of every container of this owner's agent, and of
    the networks they are on."""
    containers = agent_containers(agent_id)
    return baseline.check(containers, agent_networks(containers))


def _enforce_baseline(m: ArenaManifest, agent_dir: Path) -> None:
    """Stop the agent and raise unless every one of its containers meets the baseline."""
    try:
        violations = check_baseline(m.id)
        error: DockerError | None = BaselineError(m.id, violations) if violations else None
    except DockerError as e:
        error = DockerError(
            f"refusing {m.id}: could not check its containers against the container "
            f"baseline ({e}), so hb stopped it"
        )
    if error is None:
        return
    try:
        stop(m.id, kind_of(m), agent_dir=agent_dir)
    except DockerError:
        run_env_file(m.id).unlink(missing_ok=True)
    raise error


# ── compose ──


_MEMORY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([bkmgt]?)b?\s*$", re.IGNORECASE)
_MEMORY_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def _memory_bytes(value: object) -> int | None:
    """A compose memory size ("512m", "2g", 1048576) in bytes; None if not understood."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = _MEMORY_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    return int(float(match.group(1)) * _MEMORY_UNITS[match.group(2).lower()])


def _lower_cpus(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        cpus = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return 0 < cpus < CPU_LIMIT


def _limits(spec: dict) -> dict:
    """restart "no" and our limits, except a lower memory or CPU limit the service sets."""
    out: dict = {"restart": "no", "pids_limit": PIDS_LIMIT}
    own = _memory_bytes(spec.get("mem_limit"))
    if own is None or not 0 < own < _memory_bytes(MEMORY_LIMIT):  # type: ignore[operator]
        out["mem_limit"] = MEMORY_LIMIT
    if not _lower_cpus(spec.get("cpus")):
        out["cpus"] = CPU_LIMIT
    return out


def _write_override(
    m: ArenaManifest,
    agent_dir: Path,
    services_in: dict[str, dict],
    env_names: Iterable[str] | None = None,
    *,
    networks: Iterable[str] = (),
    hide_gateway: bool = False,
) -> Path:
    """Harden and limit every service; label and pass keys to the talked-to one.

    `networks` are the networks the compose file declares: each of them, and the default
    one, gets no route out, and every service is pointed at the door. No service publishes
    a port (their networks can't): the door is the way in.

    `environment` lists key *names* only (compose takes the values from the subprocess
    env). With env_names given, only declared names that have a value are listed, so an
    unset optional key doesn't null a default from the agent's own compose file.
    Other services get the arena labels explicitly empty, so labels baked into their
    images can't make them look like agents.
    """
    names = _declared(m)
    if env_names is not None:
        present = set(env_names)
        names = [n for n in names if n in present]
    owner = arena_owner()
    proxy = [f"{k}={v}" for k, v in egress.proxy_env(services_in).items()]
    services = {}
    for svc, base in services_in.items():
        spec: dict = {
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            **_limits(base if isinstance(base, dict) else {}),
            "labels": {
                LABEL_ID: "",
                LABEL_VERSION: "",
                LABEL_KIND: "",
                LABEL_PORT: "",
                LABEL_SERVICE: "",
                LABEL_OWNER: owner,
                LABEL_DOOR: "",
            },
        }
        environment = list(proxy)
        if svc == m.source.service:
            spec["labels"] = {
                LABEL_ID: m.id,
                LABEL_VERSION: m.version,
                LABEL_KIND: "compose",
                LABEL_PORT: str(m.runtime.port),
                LABEL_SERVICE: svc,
                LABEL_OWNER: owner,
                LABEL_DOOR: "",
            }
            environment = [*names, *proxy]
        spec["environment"] = environment
        services[svc] = spec
    network: dict = {"internal": True}
    if hide_gateway:
        network["driver_opts"] = {NO_BRIDGE_ADDRESS: "true"}
    document = {
        "services": services,
        "networks": {name: dict(network) for name in dict.fromkeys(["default", *networks])},
    }
    path = Path(agent_dir) / OVERRIDE_FILE
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _compose_files(agent_dir: Path | None, *, override: bool = True) -> list[str] | None:
    """`-f <compose> [-f <override>] --project-directory <dir>`, or None without the agent's
    compose file (then compose must not run: it would look in the current directory)."""
    if agent_dir is None:
        return None
    agent_dir = Path(agent_dir)
    base = agent_dir / COMPOSE_FILE
    if not base.is_file():
        return None
    files = ["-f", str(base)]
    if override and (agent_dir / OVERRIDE_FILE).is_file():
        files += ["-f", str(agent_dir / OVERRIDE_FILE)]
    return [*files, "--project-directory", str(agent_dir)]


def _compose(
    m: ArenaManifest,
    agent_dir: Path,
    *args: str,
    env: dict[str, str],
    override: bool = True,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    files = ["-f", str(Path(agent_dir) / COMPOSE_FILE)]
    if override:
        files += ["-f", str(Path(agent_dir) / OVERRIDE_FILE)]
    files += ["--project-directory", str(agent_dir)]
    return _docker(
        "compose",
        "-p",
        resource_name(m.id),
        *files,
        *args,
        env=_subprocess_env(env, _declared(m)),
        capture=capture,
        check=check,
    )


# ── images the catalog published with a digest ──


class ImageMismatch(DockerError):
    """A local image tag isn't the image the catalog published. The message says how to fix it."""


def _agent_images(m: ArenaManifest, services: dict[str, dict]) -> list[str]:
    if m.source.image:
        return [m.source.image]
    return list(dict.fromkeys(spec["image"] for spec in services.values()))


def _pins(m: ArenaManifest, agent_dir: Path, services: dict[str, dict]) -> list[ImagePin]:
    """The index's {ref, digest} entries for images this agent uses (in the install record).
    Images the index doesn't list keep the usual tag behaviour."""
    provenance = read_provenance(Path(agent_dir))
    if provenance is None or not provenance.images:
        return []
    used = set(_agent_images(m, services))
    return [pin for pin in provenance.images if pin.ref in used]


def _repo_digests(ref: str) -> list[str] | None:
    """The RepoDigests of the local image tagged `ref` ([] for a local build), or None when
    no such image is present."""
    result = _docker(
        "image", "inspect", "--format", "{{json .RepoDigests}}", ref,
        check=False, timeout=LIST_TIMEOUT_S,
    )  # fmt: skip
    if result.returncode != 0:
        return None
    try:
        data = json.loads((result.stdout or "").strip() or "null")
    except ValueError:
        data = None
    return [d for d in data if isinstance(d, str)] if isinstance(data, list) else []


def _canonical(repo_digest: str) -> str:
    """repository@digest with Docker Hub's implicit parts dropped (docker.io/library/x == x)."""
    repo, _, digest = repo_digest.partition("@")
    repo = repository_of(repo)
    for prefix in ("docker.io/", "index.docker.io/", "registry-1.docker.io/"):
        if repo.startswith(prefix):
            repo = repo[len(prefix) :]
            break
    if repo.startswith("library/") and repo.count("/") == 1:
        repo = repo[len("library/") :]
    return f"{repo}@{digest}"


def _mismatch(m: ArenaManifest, pin: ImagePin, found: list[str]) -> ImageMismatch:
    shown = ", ".join(found) if found else "locally built, no registry digest"
    return ImageMismatch(
        f"refusing {m.id}: the local image {pin.ref} is not the one the catalog published "
        f"(expected {pin.digest}, found {shown}). Remove the stale local image "
        f"(docker rmi {pin.ref}) so hb pulls the published one, or run from a local catalog "
        "(HB_ARENA_INDEX=<checkout>) to use your local build."
    )


def published_images(
    m: ArenaManifest, agent_dir: Path, services: dict[str, dict] | None = None
) -> set[str]:
    """Make sure every image the catalog index lists with a digest is exactly that image.

    A tag already present locally must carry <repository>@<digest> among its RepoDigests,
    else ImageMismatch (a stale pull or a local build under the published tag). A missing
    tag is pulled by digest and tagged, so `docker run` and compose find it under its tag.
    Returns the refs checked (none when the index lists no digests: tags as usual).
    """
    pins = _pins(m, agent_dir, services or {})
    for pin in pins:
        found = _repo_digests(pin.ref)
        if found is None:
            _docker("pull", pin.by_digest, capture=False)
            _docker("tag", pin.by_digest, pin.ref)
            found = _repo_digests(pin.ref) or []
        want = _canonical(pin.by_digest)
        if not any(_canonical(d) == want for d in found):
            raise _mismatch(m, pin, found)
    return {pin.ref for pin in pins}


# ── lifecycle ──


def pull_door_image() -> None:
    """Fetch the door's image unless it is here already. Streams output."""
    image = DOOR_IMAGE
    if not image_present(image):
        _docker("pull", image, capture=False)


def pull(m: ArenaManifest, agent_dir: Path) -> None:
    """Fetch the agent's images (compose agents use prebuilt images only). Streams output.

    Images the catalog index lists with a digest are fetched (and checked) by digest; the
    others by tag."""
    if m.source.image:
        if not published_images(m, agent_dir):
            _docker("pull", m.source.image, capture=False)
        return
    services = checked_services(m, agent_dir)
    pinned = published_images(m, agent_dir, services)
    if not pinned:
        _compose(m, agent_dir, "pull", env={}, override=False, capture=False)
        return
    rest = [svc for svc, spec in services.items() if spec["image"] not in pinned]
    if rest:  # only the services whose images the index doesn't pin
        _compose(m, agent_dir, "pull", *rest, env={}, override=False, capture=False)


def allowed_destinations(m: ArenaManifest, env: dict[str, str]) -> list[egress.Destination]:
    """What the door lets through for this agent started with `env`. Raises DockerError."""
    try:
        return egress.allowed(_declared(m), m.runtime.egress, env)
    except ValueError as e:
        raise DockerError(f"cannot start {m.id}: {e}") from None


def _quietly(*argvs: tuple[str, ...]) -> None:
    """Best-effort clean-up: run each docker command, whatever happens."""
    for argv in argvs:
        try:
            _docker(*argv, check=False)
        except DockerError:
            pass


def _start_door(
    m: ArenaManifest,
    name: str,
    target: str,
    networks: Iterable[str],
    destinations: list[egress.Destination],
) -> None:
    """Run the agent's door on a network of its own, publish its way in on 127.0.0.1, and
    put it on the agent's `networks` under the name the agent's proxy variables use.
    `target` is the agent's name on those networks."""
    door, outside = door_name(name), outside_network(name)
    _quietly(("rm", "-f", "-v", door), ("network", "rm", outside))
    owner = f"{LABEL_OWNER}={arena_owner()}"
    _docker("network", "create", "--label", owner, outside)
    # The model on the user's machine (a local model): the name needs this on Linux.
    to_host = any(d.host == HOST_GATEWAY_NAME for d in destinations)
    host_gateway = ["--add-host", f"{HOST_GATEWAY_NAME}:host-gateway"] if to_host else []
    source = Path(door_program.__file__).read_text(encoding="utf-8")
    _docker(
        "run", "-d", "--name", door,
        "--label", f"{LABEL_DOOR}={m.id}", "--label", owner,
        "--network", outside, "-p", f"127.0.0.1::{door_program.IN_PORT}",
        "--user", DOOR_USER, "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", str(DOOR_PIDS_LIMIT), "--memory", DOOR_MEMORY_LIMIT,
        "--cpus", str(DOOR_CPU_LIMIT), "--restart", "no",
        *host_gateway,
        "-e", f"DOOR_TARGET={target}:{m.runtime.port}",
        "-e", f"DOOR_ALLOW={egress.door_config(destinations)}",
        "--entrypoint", "python3", DOOR_IMAGE, "-I", "-c", source,
    )  # fmt: skip
    for network in networks:
        _docker("network", "connect", "--alias", egress.DOOR_ALIAS, network, door)


def _can_hide_gateway(name: str) -> bool:
    """This Docker can make a network whose bridge has no address (tried on a network that
    is removed again)."""
    probe = f"{name}_probe"
    _quietly(("network", "rm", probe))
    made = _docker(
        "network", "create", "--internal", "-o", f"{NO_BRIDGE_ADDRESS}=true", probe, check=False
    )
    _quietly(("network", "rm", probe))
    return made.returncode == 0


def _project_networks(name: str) -> list[str]:
    """The names of the networks of the compose project `name`."""
    listed = _docker(
        "network", "ls", "--filter", _project_label(name), "--format", "{{.Name}}",
        timeout=LIST_TIMEOUT_S,
    )  # fmt: skip
    return [n for n in listed.stdout.split() if not n.startswith("-")]


def _start_image(
    m: ArenaManifest,
    env_file: Path,
    destinations: list[egress.Destination],
    hide_gateway: bool,
) -> None:
    name = resource_name(m.id)
    door, outside = door_name(name), outside_network(name)
    clean_up = (
        ("rm", "-f", "-v", name),
        ("rm", "-f", "-v", door),
        ("network", "rm", name),
        ("network", "rm", outside),
    )
    # From scratch: whatever an earlier start left is not what this one needs.
    _quietly(*clean_up)
    try:
        hidden = ["-o", f"{NO_BRIDGE_ADDRESS}=true"] if hide_gateway else []
        _docker("network", "create", "--internal", *hidden, name)
        _start_door(m, name, name, [name], destinations)
        proxy = [x for k, v in egress.proxy_env([name]).items() for x in ("-e", f"{k}={v}")]
        _docker(
            "run", "-d", "--name", name,
            "--label", f"{LABEL_ID}={m.id}", "--label", f"{LABEL_VERSION}={m.version}",
            "--label", f"{LABEL_KIND}=image", "--label", f"{LABEL_PORT}={m.runtime.port}",
            "--label", f"{LABEL_OWNER}={arena_owner()}", "--label", f"{LABEL_DOOR}=",
            "--network", name, *proxy,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(PIDS_LIMIT), "--memory", MEMORY_LIMIT,
            "--cpus", str(CPU_LIMIT), "--restart", "no",
            "--env-file", str(env_file), m.source.image,
        )  # fmt: skip
    except DockerError:
        # Don't leave the keys file, the door or the networks behind (best effort).
        env_file.unlink(missing_ok=True)
        _quietly(*clean_up)
        raise


def _start_compose(
    m: ArenaManifest,
    agent_dir: Path,
    services: dict[str, dict],
    env: dict[str, str],
    destinations: list[egress.Destination],
    hide_gateway: bool,
) -> None:
    name = resource_name(m.id)
    if egress.DOOR_ALIAS in services:
        raise DockerError(
            f"refusing to run {m.id}: a service may not be called {egress.DOOR_ALIAS} "
            "(the name of hb's proxy on the agent's networks)"
        )
    _write_override(
        m,
        agent_dir,
        services,
        env_names=env,
        networks=network_names(agent_dir),
        hide_gateway=hide_gateway,
    )
    try:
        # From scratch, but for the named volumes: the old door holds on to the networks.
        _quietly(("rm", "-f", "-v", door_name(name)))
        _compose(m, agent_dir, "down", "--remove-orphans", env=env, check=False)
        # Containers and networks first, then the door, then the start: the agent's way
        # out is there when it starts.
        _compose(
            m, agent_dir, "up", "--no-start", "--force-recreate", "--renew-anon-volumes", env=env
        )
        _start_door(m, name, m.source.service, _project_networks(name), destinations)
        _compose(m, agent_dir, "up", "-d", env=env)
    except DockerError:
        # Don't leave half-started containers or the keys file behind (best effort).
        try:
            stop(m.id, "compose", agent_dir=agent_dir)
        except DockerError:
            run_env_file(m.id).unlink(missing_ok=True)
        raise


def start(m: ArenaManifest, agent_dir: Path, env: dict[str, str]) -> RunningAgent:
    """Start the agent with no way out of its networks but the door (see egress.py for what
    the door lets through)."""
    declared = set(_declared(m))
    env = {k: v for k, v in env.items() if k in declared}
    destinations = allowed_destinations(m, env)
    services = checked_services(m, agent_dir) if m.source.compose else {}
    published_images(m, agent_dir, services)
    hide_gateway = _can_hide_gateway(resource_name(m.id))
    env_file = run_env_file(m.id)
    write_env_file(env_file, env)
    if m.source.image:
        _start_image(m, env_file, destinations, hide_gateway)
    else:
        _start_compose(m, agent_dir, services, env, destinations, hide_gateway)
    agent = find_running(m.id)
    if agent is None or agent.host_port is None:
        kind = kind_of(m)
        tail = last_logs(m.id, kind, 20, agent_dir=agent_dir)
        try:
            stop(m.id, kind, agent_dir=agent_dir)
        except DockerError:
            pass
        message = (
            f"{m.id} started but its port {m.runtime.port} can't be reached from this "
            "machine; stopped it."
        )
        if tail.strip():
            message += f"\nLast log lines:\n{tail.rstrip()}"
        raise DockerError(message)
    _enforce_baseline(m, agent_dir)
    return replace(agent, gateway_reachable=not hide_gateway)


def _loopback_get(url: str, **kwargs) -> httpx.Response:
    """GET a 127.0.0.1 URL, ignoring any proxy configured in the environment."""
    return httpx.get(url, trust_env=False, **kwargs)


def wait_healthy(
    agent: RunningAgent,
    health: Health,
    *,
    get: Callable[..., httpx.Response] = _loopback_get,
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


def _project_label(name: str) -> str:
    return f"label={COMPOSE_PROJECT_LABEL}={name}"


def _ids(*args: str) -> list[str]:
    return _docker(*args, timeout=LIST_TIMEOUT_S).stdout.split()


def _remove_project(name: str) -> None:
    """What `compose down -v --remove-orphans` does, by the compose project label, with plain
    docker commands (no compose file needed)."""
    label = _project_label(name)
    containers = _ids("ps", "-a", "-q", "--filter", label)
    if containers:
        _docker("rm", "-f", "-v", *containers, check=False)
    networks = _ids("network", "ls", "-q", "--filter", label)
    if networks:
        _docker("network", "rm", *networks, check=False)
    volumes = _ids("volume", "ls", "-q", "--filter", label)
    if volumes:
        _docker("volume", "rm", "-f", *volumes, check=False)


def stop(
    agent_id: str,
    kind: str,
    owner: str | None = None,
    name: str | None = None,
    *,
    agent_dir: Path | None = None,
) -> None:
    """Remove an agent's containers, network (and compose volumes) and saved keys. `owner`
    (default: this one) names another owner's agent (`stop --all --any-owner`); its keys file
    lives under that owner's HOME and is left alone. `name` is the container name / compose
    project Docker reported (RunningAgent.name); without it the name is computed from id and
    owner. `agent_dir` holds our compose agent's files: with them, `compose down` runs on
    them; without them (manifest gone, another owner's agent) the project is removed by label.

    A legacy agent (owner "", from an hb before owners) used our run/<id>.env: that file is
    removed too, unless an agent of ours with that id still exists."""
    name = name or resource_name(agent_id, owner)
    ours = owner is None or owner == arena_owner()
    # The door first: it holds on to the agent's networks.
    _docker("rm", "-f", "-v", door_name(name), check=False)
    if kind == "compose":
        files = _compose_files(agent_dir) if ours else None
        if files is None:
            _remove_project(name)
        else:
            _docker(
                "compose", "-p", name, *files, "down", "-v", "--remove-orphans",
                check=False, env=_subprocess_env({}),
            )  # fmt: skip
    else:
        _docker("rm", "-f", "-v", name, check=False)
        _docker("network", "rm", name, check=False)
    _docker("network", "rm", outside_network(name), check=False)
    if ours:
        run_env_file(agent_id).unlink(missing_ok=True)
    elif owner == "":
        try:
            ours = find_running(agent_id, include_stopped=True)
        except DockerError:
            return
        if ours is None:
            run_env_file(agent_id).unlink(missing_ok=True)


def remove_doors(*, any_owner: bool = False) -> None:
    """Remove every door of this owner (any_owner: of every owner) and its network: what
    `stop --all` does for doors whose agent is gone. Best effort."""
    try:
        doors = _doors(None if any_owner else arena_owner(), include_stopped=True)
    except DockerError:
        return
    for container in doors:
        door = str(container.get("Name") or "").lstrip("/")
        if not door.endswith("_door") or door.startswith("-"):
            continue
        outside = outside_network(door.removesuffix("_door"))
        _quietly(("rm", "-f", "-v", door), ("network", "rm", outside))


def reset(m: ArenaManifest, agent_dir: Path) -> RunningAgent:
    """Fresh containers and volumes, same keys as the last start."""
    path = run_env_file(m.id)
    if not path.exists() and m.runtime.env.required:
        # Restarting without the keys would silently break the agent; stop instead.
        raise DockerError(f"no saved keys for {m.id} → hb arena run {m.id} again")
    try:
        env = parse_env_file(path) if path.exists() else {}
    except (OSError, UnicodeDecodeError) as e:
        # Restarting without the keys would silently break the agent; stop instead.
        raise DockerError(
            f"cannot read the saved keys for {m.id} ({path}: {e}); run hb arena run {m.id} again"
        ) from None
    stop(m.id, kind_of(m), agent_dir=agent_dir)
    agent = start(m, agent_dir, env)
    wait_healthy(agent, m.runtime.health)
    return agent


def _agent_container(agent_id: str) -> str:
    """The compose agent's own (talked-to) container, found by label."""
    ids = _ids(
        "ps", "-a", "-q", "--filter", _project_label(resource_name(agent_id)),
        "--filter", f"label={LABEL_ID}={agent_id}",
    )  # fmt: skip
    if not ids:
        raise DockerError(f"no container found for {agent_id}")
    return ids[0]


def logs(
    agent_id: str,
    kind: str,
    *,
    follow: bool = False,
    tail: int = 200,
    agent_dir: Path | None = None,
) -> None:
    """Stream logs to the terminal. A compose agent without its compose file (`agent_dir`)
    shows its own service's container only."""
    name = resource_name(agent_id)
    follow_flag = ["-f"] if follow else []
    files = _compose_files(agent_dir) if kind == "compose" else None
    if files is not None:
        _docker(
            "compose", "-p", name, *files, "logs", "--tail", str(tail), *follow_flag,
            capture=False, env=_subprocess_env({}),
        )  # fmt: skip
        return
    target = _agent_container(agent_id) if kind == "compose" else name
    _docker("logs", "--tail", str(tail), *follow_flag, target, capture=False)


def door_logs(agent_id: str, *, follow: bool = False, tail: int = 200) -> None:
    """Stream the log of the agent's door: what it let through ("allowed host:port"), what
    it refused ("blocked host:port") and what it could not reach ("failed host:port")."""
    follow_flag = ["-f"] if follow else []
    door = door_name(resource_name(agent_id))
    _docker("logs", "--tail", str(tail), *follow_flag, door, capture=False)


def refused_destinations(agent_id: str, lines: int = 500) -> list[str]:
    """The destinations (host:port) the agent's door refused or could not reach, from the
    end of its log, each once, in order. Never raises."""
    try:
        door = door_name(resource_name(agent_id))
        result = _docker("logs", "--tail", str(lines), door, check=False, timeout=LIST_TIMEOUT_S)
    except DockerError:
        return []
    found: dict[str, None] = {}
    for line in (result.stdout or "").splitlines():
        verdict, _, rest = line.partition(" ")
        where = rest.split(" ", 1)[0]
        if verdict in ("blocked", "failed") and where and not has_control_chars(where):
            found[where[:300]] = None
    return list(found)


def last_logs(agent_id: str, kind: str, lines: int = 50, *, agent_dir: Path | None = None) -> str:
    """The last log lines as text (stdout + stderr). Never raises."""
    name = resource_name(agent_id)
    try:
        files = _compose_files(agent_dir) if kind == "compose" else None
        if files is not None:
            result = _docker(
                "compose", "-p", name, *files, "logs", "--no-color", "--tail", str(lines),
                check=False, env=_subprocess_env({}), timeout=LIST_TIMEOUT_S,
            )  # fmt: skip
        else:
            target = _agent_container(agent_id) if kind == "compose" else name
            result = _docker(
                "logs", "--tail", str(lines), target, check=False, timeout=LIST_TIMEOUT_S
            )
    except DockerError:
        return ""
    return "".join(part for part in (result.stdout, result.stderr) if part)


def _used_outside_arena(image: str) -> bool:
    """Some container that isn't arena's (no owner label) uses `image`. True when unsure."""
    base = ("ps", "-a", "-q", "--no-trunc", "--filter", f"ancestor={image}")
    try:
        everyone = _docker(*base, check=False, timeout=LIST_TIMEOUT_S)
        arena = _docker(
            *base, "--filter", f"label={LABEL_OWNER}", check=False, timeout=LIST_TIMEOUT_S
        )
    except DockerError:
        return True
    if everyone.returncode != 0 or arena.returncode != 0:
        return True
    return bool(set(everyone.stdout.split()) - set(arena.stdout.split()))


def _remove_image(image: str) -> None:
    if not _used_outside_arena(image):
        _docker("rmi", image, check=False)


def remove_images(m: ArenaManifest, agent_dir: Path) -> None:
    """Remove the images the manifest names (and compose volumes). Best effort.

    Only the agent's own images: `source.image`, or the `image` of each of its compose
    services, and none that a non-arena container uses (the user may have pulled it)."""
    if m.source.image:
        _remove_image(m.source.image)
        return
    try:
        services = checked_services(m, agent_dir)
    except DockerError:
        return
    files = _compose_files(agent_dir)
    if files is None:
        _remove_project(resource_name(m.id))
    else:
        _docker(
            "compose", "-p", resource_name(m.id), *files, "down", "-v",
            check=False, env=_subprocess_env({}),
        )  # fmt: skip
    for image in dict.fromkeys(spec["image"] for spec in services.values()):
        _remove_image(image)
