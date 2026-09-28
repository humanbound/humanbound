# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Allowlist check for a compose agent's docker-compose.yml.

Compose files from any catalog run on the user's machine, so anything that could reach the
host (ports, host namespaces, bind mounts, devices, privileges, builds, external
networks/volumes) is refused before `docker compose` ever sees the file.

The check runs on the raw file, before compose interpolates `${...}`, so interpolation
is refused everywhere (keys and values). The one exception is a service environment
value that is exactly `${NAME}` for a key the manifest declares: that is how a compose
agent receives the user's keys.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .catalog import COMPOSE_FILE
from .manifest import (
    ArenaManifest,
    ManifestError,
    load_yaml,
    read_text_limited,
)


class DockerError(RuntimeError):
    """A docker/compose problem. The message is ready to show."""


TOP_LEVEL_KEYS = frozenset({"services", "volumes", "networks", "version"})
SERVICE_KEYS = frozenset(
    {
        "image",
        "command",
        "entrypoint",
        "environment",
        "expose",
        "healthcheck",
        "depends_on",
        "restart",
        "working_dir",
        "user",
        "volumes",
        "networks",
        "tmpfs",
        "read_only",
        "labels",
        "stop_signal",
        "stop_grace_period",
        "init",
        "mem_limit",
        "cpus",
        "shm_size",
        "ulimits",
        "logging",
        "platform",
        "hostname",
    }
)
LOGGING_DRIVERS = frozenset({"json-file", "local", "none"})
NETWORK_DRIVERS = frozenset({"bridge"})
NETWORK_KEYS = frozenset({"driver", "internal", "labels"})
VOLUME_DRIVERS = frozenset({"local"})
VOLUME_KEYS = frozenset({"driver", "labels"})
VOLUME_MOUNT_TYPES = frozenset({"volume", "tmpfs"})
RESERVED_LABEL_PREFIX = "io.humanbound."
# A named volume: what `docker volume create` accepts. Anything else is a host path.
_VOLUME_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# The only interpolation allowed: a whole environment value naming a declared key.
_ENV_PASSTHROUGH_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
BUILD_UNSUPPORTED = (
    "compose agents must reference prebuilt images (image: …); build is not supported "
    "for installed agents"
)


def _fail(where: str, why: str) -> None:
    raise DockerError(f"unsafe docker-compose.yml: {where}: {why}")


def _check_labels(svc: str, labels: Any) -> None:
    if isinstance(labels, dict):
        keys = [str(k) for k in labels]
    elif isinstance(labels, list):
        keys = [str(item).partition("=")[0] for item in labels]
    else:
        _fail(f"service '{svc}'", "'labels' must be a list or a mapping")
    for key in keys:
        if key.strip().lower().startswith(RESERVED_LABEL_PREFIX):
            _fail(f"service '{svc}'", f"label '{key}' uses the reserved io.humanbound.* prefix")


def _check_logging(svc: str, logging: Any) -> None:
    if not isinstance(logging, dict):
        _fail(f"service '{svc}'", "'logging' must be a mapping")
    driver = logging.get("driver")
    if driver is not None and driver not in LOGGING_DRIVERS:
        _fail(
            f"service '{svc}'",
            f"logging driver '{driver}' is not allowed (use one of {', '.join(sorted(LOGGING_DRIVERS))})",
        )


def _check_service_volumes(svc: str, volumes: Any) -> None:
    if not isinstance(volumes, list):
        _fail(f"service '{svc}'", "'volumes' must be a list")
    for item in volumes:
        if isinstance(item, str):
            if "$" in item:
                _fail(f"service '{svc}'", f"volume '{item}' uses variable interpolation")
            parts = item.split(":")
            if re.match(r"^[A-Za-z]:[\\/]", item):
                # compose reads a leading "x:/" or "x:\\" as a Windows drive: "C:/x:/d" is
                # a bind mount, and even "v:/data" is not the named volume 'v'.
                _fail(
                    f"service '{svc}'",
                    f"volume '{item}' starts with what compose reads as a Windows drive "
                    "letter (a host path); use a named volume of two or more characters",
                )
            if len(parts) >= 2:
                source = parts[0]
                if source.startswith(("/", ".", "~", "$")) or not _VOLUME_NAME_RE.fullmatch(source):
                    _fail(
                        f"service '{svc}'", f"volume '{item}' is a bind mount; use a named volume"
                    )
        elif isinstance(item, dict):
            kind = item.get("type", "volume")
            if kind not in VOLUME_MOUNT_TYPES:
                _fail(
                    f"service '{svc}'",
                    f"volume of type '{kind}' is not allowed; use a named volume",
                )
            source = item.get("source")
            if (
                kind == "volume"
                and source is not None
                and not _VOLUME_NAME_RE.fullmatch(str(source))
            ):
                _fail(
                    f"service '{svc}'",
                    f"volume source '{source}' is a host path; use a named volume",
                )
        else:
            _fail(f"service '{svc}'", f"volume entry {item!r} is not understood")


def _check_environment(svc: str, environment: Any, declared: frozenset[str]) -> None:
    """Entries without a value (`- NAME`, `NAME:` / `NAME: null`) make compose copy NAME from
    its own process environment. Only names the manifest declares may do that: those are the
    keys hb puts there (and only those)."""
    where = f"service '{svc}' environment"
    if isinstance(environment, dict):
        items = [(k, v is None) for k, v in environment.items()]
    elif isinstance(environment, list):
        items = []
        for entry in environment:
            if not isinstance(entry, str):
                _fail(where, f"entry {entry!r} is not a string")
            key, sep, _ = entry.partition("=")
            items.append((key, not sep))
    else:
        _fail(where, "must be a list or a mapping")
    for key, passthrough in items:
        if not isinstance(key, str) or not key.strip():
            _fail(where, f"entry {key!r} has no variable name")
        if passthrough and key not in declared:
            _fail(
                where,
                f"'{key}' has no value, so compose would copy it from the host environment; "
                "give it a value or declare it in runtime.env",
            )


def _check_service(svc: str, spec: Any) -> None:
    if not isinstance(spec, dict):
        _fail(f"service '{svc}'", "must be a mapping")
    if "build" in spec:
        _fail(f"service '{svc}'", BUILD_UNSUPPORTED)
    for key in spec:
        if key not in SERVICE_KEYS:
            _fail(f"service '{svc}'", f"key '{key}' is not allowed")
    if "labels" in spec:
        _check_labels(svc, spec["labels"])
    if "logging" in spec:
        _check_logging(svc, spec["logging"])
    if "volumes" in spec:
        _check_service_volumes(svc, spec["volumes"])
    image = spec.get("image")
    if not isinstance(image, str) or not image.strip():
        _fail(f"service '{svc}'", "needs 'image' (a prebuilt image reference)")


def _check_top_level_networks(networks: Any) -> None:
    if not isinstance(networks, dict):
        _fail("networks", "must be a mapping")
    for name, spec in networks.items():
        if spec is None:
            continue
        if not isinstance(spec, dict):
            _fail(f"network '{name}'", "must be a mapping")
        for key in spec:
            if key not in NETWORK_KEYS:
                _fail(f"network '{name}'", f"'{key}' is not allowed")
        driver = spec.get("driver")
        if driver is not None and driver not in NETWORK_DRIVERS:
            _fail(f"network '{name}'", f"driver '{driver}' is not allowed (only 'bridge')")


def network_names(agent_dir: Path | str, compose_file: Path | str | None = None) -> list[str]:
    """The networks a compose file declares at the top level (after checked_services has
    accepted the file). Raises DockerError when the file can't be read."""
    path = Path(compose_file) if compose_file is not None else Path(agent_dir) / COMPOSE_FILE
    try:
        data = load_yaml(read_text_limited(path), str(path))
    except (OSError, UnicodeDecodeError) as e:
        raise DockerError(f"cannot read {path}: {e}") from None
    except ManifestError as e:
        raise DockerError(str(e)) from None
    networks = data.get("networks") if isinstance(data, dict) else None
    return [n for n in networks if isinstance(n, str)] if isinstance(networks, dict) else []


def _check_top_level_volumes(volumes: Any) -> None:
    if not isinstance(volumes, dict):
        _fail("volumes", "must be a mapping")
    for name, spec in volumes.items():
        if spec is None:
            continue
        if not isinstance(spec, dict):
            _fail(f"volume '{name}'", "must be a mapping")
        for key in spec:
            if key not in VOLUME_KEYS:
                _fail(f"volume '{name}'", f"'{key}' is not allowed")
        driver = spec.get("driver")
        if driver is not None and driver not in VOLUME_DRIVERS:
            _fail(f"volume '{name}'", f"driver '{driver}' is not allowed (only 'local')")


def _has_interpolation(text: str) -> bool:
    return "$" in text.replace("$$", "")


def _env_passthrough_ok(path: tuple, value: str, declared: frozenset[str]) -> bool:
    """A service environment value that is exactly ${NAME} for a declared NAME."""
    if len(path) != 4 or path[0] != "services" or path[2] != "environment":
        return False
    if isinstance(path[3], int):  # list form: KEY=value
        key, sep, value = value.partition("=")
        if not sep or _has_interpolation(key):
            return False
    match = _ENV_PASSTHROUGH_RE.fullmatch(value)
    return match is not None and match.group(1) in declared


def _show(path: tuple) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "top level"


def _check_interpolation(node: Any, declared: frozenset[str], path: tuple = ()) -> None:
    """Refuse `$` (other than the `$$` escape) in every key and value."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _has_interpolation(key):
                _fail(_show(path), f"key {key!r} uses variable interpolation")
            _check_interpolation(value, declared, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _check_interpolation(value, declared, (*path, i))
    elif (
        isinstance(node, str)
        and _has_interpolation(node)
        and not _env_passthrough_ok(path, node, declared)
    ):
        _fail(
            _show(path),
            f"{node!r} uses variable interpolation; only an environment value of exactly "
            "${NAME} for a key declared in runtime.env is allowed (write $$ for a literal $)",
        )


def check_compose(
    m: ArenaManifest,
    agent_dir: Path,
    compose_file: Path | None = None,
    *,
    allow_dotenv: bool = False,
) -> list[str]:
    """Validate a compose file against the allowlist; return its service names.

    See checked_services for the arguments."""
    return list(checked_services(m, agent_dir, compose_file, allow_dotenv=allow_dotenv))


def checked_services(
    m: ArenaManifest,
    agent_dir: Path,
    compose_file: Path | None = None,
    *,
    allow_dotenv: bool = False,
) -> dict[str, dict]:
    """Validate a compose file against the allowlist; return its services (name -> spec).

    The file is `agent_dir/docker-compose.yml` (how installed agents are cached) unless
    `compose_file` names another one (e.g. `source.compose` next to an arena.yaml being
    validated).

    `allow_dotenv` skips the `.env` refusal. Only `hb arena validate` sets it: an author's
    folder may hold a local-dev `.env`, while installed agents never get one and
    `run`/`start` keep refusing it.
    """
    agent_dir = Path(agent_dir)
    path = Path(compose_file) if compose_file is not None else agent_dir / COMPOSE_FILE
    if not allow_dotenv and (agent_dir / ".env").exists():
        raise DockerError(
            f"refusing to run {m.id}: {agent_dir / '.env'} exists and docker compose would "
            "read it for interpolation. Remove it."
        )
    try:
        data = load_yaml(read_text_limited(path), str(path))
    except (OSError, UnicodeDecodeError) as e:
        raise DockerError(f"cannot read {path}: {e}") from None
    except ManifestError as e:
        raise DockerError(str(e)) from None
    if not isinstance(data, dict):
        raise DockerError(f"{path} must be a YAML mapping")
    for key in data:
        if key not in TOP_LEVEL_KEYS and not str(key).startswith("x-"):
            _fail("top level", f"key '{key}' is not allowed")
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise DockerError(f"{path} has no 'services' mapping")
    for name in services:
        if not isinstance(name, str):
            _fail(
                "services",
                f"service name {name!r} is not a string (quote it; YAML reads unquoted "
                "true/false/yes/no/null and numbers as other types)",
            )
    if m.source.service not in services:
        raise DockerError(
            f"source.service '{m.source.service}' is not a service in {path} "
            f"(services: {', '.join(str(s) for s in services)})"
        )
    declared = frozenset([*m.runtime.env.required, *m.runtime.env.optional])
    for name, spec in services.items():
        _check_service(name, spec)
        if "environment" in spec:
            _check_environment(name, spec["environment"], declared)
    _check_interpolation(data, declared)
    if "networks" in data and data["networks"] is not None:
        _check_top_level_networks(data["networks"])
    if "volumes" in data and data["volumes"] is not None:
        _check_top_level_volumes(data["volumes"])
    return services
