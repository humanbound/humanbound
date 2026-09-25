# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Compose safety: an agent's own docker-compose.yml must not reach the host.

Allowlists, not denylists: compose grows new host-reaching keys over time
(use_api_socket, provider, models, ...), so anything not known to be harmless is
refused. hb adds what the agent needs itself in the generated override (the
talked-to service's loopback port, labels and declared env names, plus
cap_drop/no-new-privileges on every service).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .manifest import ArenaManifest

COMPOSE_FILE = "docker-compose.yml"


class DockerError(RuntimeError):
    """A docker operation failed. The message is ready to show."""


# Service keys that cannot publish ports, share host namespaces, mount host paths,
# add privileges or pull in other files. `volumes`, `networks`, `labels`, `logging`
# and `build` are further checked below.
SERVICE_KEYS = frozenset(
    {
        "image", "build", "command", "entrypoint", "environment", "expose",
        "healthcheck", "depends_on", "restart", "working_dir", "user", "volumes",
        "networks", "tmpfs", "read_only", "labels", "stop_signal",
        "stop_grace_period", "init", "mem_limit", "cpus", "shm_size", "ulimits",
        "logging", "platform", "hostname",
    }
)  # fmt: skip
BUILD_KEYS = frozenset({"context", "dockerfile", "args", "target"})
# `version` is obsolete and ignored by compose v2, but still common in the wild.
TOP_LEVEL_KEYS = frozenset({"services", "volumes", "networks", "version"})
RESERVED_LABEL_PREFIX = "io.humanbound."
_VOLUME_TYPES = ("volume", "tmpfs")
_LOG_DRIVERS = ("json-file", "local", "none")
_NETWORK_DRIVERS_FORBIDDEN = ("host", "none", "macvlan", "ipvlan")


def _unsafe(where: str, field: str, why: str) -> DockerError:
    return DockerError(
        f"refusing to run this agent: {COMPOSE_FILE} {where} sets '{field}' ({why}). "
        "Arena agents may not publish ports or reach the host; hb publishes the agent's "
        "port itself, on 127.0.0.1."
    )


def _invalid(where: str, kind: type) -> DockerError:
    return DockerError(f"invalid {COMPOSE_FILE}: {where} must be a {kind.__name__}")


def _items(value: object, where: str, kind: type) -> list | dict:
    """`value` as a list/dict (None → empty), or an 'invalid compose file' error."""
    if value is None:
        return kind()
    if not isinstance(value, kind):
        raise _invalid(where, kind)
    return value


def _leaves_dir(path: object) -> bool:
    """A file/context path that is absolute, home-relative, interpolated or climbs out."""
    if not isinstance(path, str):
        return True
    return path.startswith(("/", "~", "\\")) or "$" in path or ".." in Path(path).parts


def _is_remote(context: str) -> bool:
    """A build context compose would fetch (URL, git remote, git ref) instead of a dir."""
    return ":" in context or "#" in context or context.startswith(("github.com/", "git@"))


def _bind_source(volume: object) -> str | None:
    """Why a service volume entry is a host mount, or None when it is not."""
    if isinstance(volume, str):
        parts = volume.split(":")
        if len(parts) >= 2 and parts[0].startswith(("/", ".", "~", "$")):
            return f"bind mount of {parts[0]}"
        return None
    if isinstance(volume, dict):
        vtype = volume.get("type", "volume")
        if vtype not in _VOLUME_TYPES:
            return f"volume type {vtype!r}"
        return None
    return "unrecognised volume entry"


def _label_keys(labels: object, where: str) -> list[str]:
    if labels is None:
        return []
    if isinstance(labels, dict):
        return [str(k) for k in labels]
    if isinstance(labels, list):
        return [str(item).split("=", 1)[0] for item in labels]
    raise _invalid(f"{where} labels", dict)


def _check_build(where: str, build: object) -> None:
    if isinstance(build, str):
        build = {"context": build}
    if not isinstance(build, dict):
        raise _invalid(f"{where} build", dict)
    for key in build:
        if key not in BUILD_KEYS:
            raise _unsafe(where, f"build.{key}", "not allowed")
    context = build.get("context", ".")
    if _leaves_dir(context) or _is_remote(context):
        raise _unsafe(where, "build.context", f"{context!r} is not a directory inside the agent")
    if "dockerfile" in build and _leaves_dir(build["dockerfile"]):
        raise _unsafe(where, "build.dockerfile", "outside the agent directory")


def _check_service(name: str, svc: object) -> None:
    where = f"service '{name}'"
    if not isinstance(svc, dict):
        raise DockerError(f"invalid {COMPOSE_FILE}: {where} must be a mapping")
    for key in svc:
        if key not in SERVICE_KEYS:
            raise _unsafe(where, str(key), "not allowed")
    for volume in _items(svc.get("volumes"), f"{where} volumes", list):
        why = _bind_source(volume)
        if why:
            raise _unsafe(where, "volumes", why)
    for key in _label_keys(svc.get("labels"), where):
        if key.lower().startswith(RESERVED_LABEL_PREFIX):
            raise _unsafe(where, "labels", f"{key!r} is reserved for hb")
    logging = svc.get("logging")
    if logging is not None:
        if not isinstance(logging, dict):
            raise _invalid(f"{where} logging", dict)
        driver = logging.get("driver", "json-file")
        if driver not in _LOG_DRIVERS:
            raise _unsafe(where, "logging", f"driver {driver!r} sends logs off the container")
    if "build" in svc:
        _check_build(where, svc["build"])


def _check_top_level(doc: dict) -> None:
    for key in doc:
        if str(key).startswith("x-"):
            continue
        if key not in TOP_LEVEL_KEYS:
            why = "hb sets the project name" if key == "name" else "not allowed"
            raise _unsafe("top level", str(key), why)
    for section in ("volumes", "networks"):
        for name, spec in _items(doc.get(section), section, dict).items():
            if not isinstance(spec, dict):
                continue
            if spec.get("external"):
                raise _unsafe(f"{section} '{name}'", "external", "uses a pre-existing resource")
            if section == "volumes" and spec.get("driver_opts"):
                raise _unsafe(f"volumes '{name}'", "driver_opts", "may bind a host path")
            if section == "networks" and spec.get("driver") in _NETWORK_DRIVERS_FORBIDDEN:
                raise _unsafe(f"networks '{name}'", "driver", f"{spec['driver']!r}")


def check_compose(m: ArenaManifest, agent_dir: Path) -> list[str]:
    """Reject compose files that could publish ports or reach the host. Raises DockerError.

    Returns the compose file's service names.
    """
    if (agent_dir / ".env").exists():
        raise DockerError(
            f"refusing to run {m.id}: a .env file is present next to {COMPOSE_FILE}. "
            "'docker compose' reads it automatically for ${VAR} interpolation, which "
            "could leak host secrets; hb only passes the agent's declared env vars."
        )
    path = agent_dir / COMPOSE_FILE
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise DockerError(f"cannot read {COMPOSE_FILE} for {m.id}: {e}") from None
    services = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services, dict) or not services:
        raise DockerError(f"invalid {COMPOSE_FILE} for {m.id}: no 'services' mapping")
    _check_top_level(doc)
    for name, svc in services.items():
        _check_service(str(name), svc)
    if m.source.service not in services:
        raise DockerError(
            f"invalid {COMPOSE_FILE} for {m.id}: no service '{m.source.service}' "
            "(arena.yaml source.service)"
        )
    return [str(name) for name in services]
