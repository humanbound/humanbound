# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""What an arena agent may reach on the network.

By default an agent's networks have no route out, and the agent's web traffic goes through
the door (door.py), which lets through only:

  - the model: the host and port of OPENAI_BASE_URL (api.openai.com:443 when unset), for
    agents that declare an OPENAI_* key;
  - the destinations the manifest lists under runtime.egress.

This module works those destinations out. It is pure: no Docker, no network.

Limits, so nothing here is read as more than it is: an allowed destination is still a way
out (whatever the agent sends there leaves the machine); only traffic of clients that honour
the proxy variables passes the door, everything else simply fails; and a container is not a
virtual machine.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = [
    "DEFAULT_MODEL_URL",
    "DOOR_ALIAS",
    "MAX_EGRESS",
    "MODEL_URL_KEY",
    "PROXY_NAMES",
    "PROXY_PORT",
    "Destination",
    "allowed",
    "describe",
    "door_config",
    "model_destination",
    "parse_entry",
    "proxy_env",
    "uses_model",
]

MODEL_URL_KEY = "OPENAI_BASE_URL"
MODEL_KEY_PREFIX = "OPENAI_"
DEFAULT_MODEL_URL = "https://api.openai.com/v1"
DEFAULT_PORT = 443
MAX_EGRESS = 20

# The door's name on the agent's networks, and the port its proxy listens on.
DOOR_ALIAS = "hb-door"
PROXY_PORT = 3128
# hb sets these for the agent; a manifest may not declare them.
PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")

MODEL = "model"
MANIFEST = "manifest"

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# A full host name: at least two labels, the last one not a number (so never an IP address).
_HOST_RE = re.compile(rf"(?:{_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?")
_PORT_RE = re.compile(r"[0-9]{1,5}")
# Names that mean the user's machine or network, never a public service.
_LOCAL_SUFFIXES = (".internal", ".local", ".localhost", ".lan", ".home.arpa")
_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})


@dataclass(frozen=True)
class Destination:
    host: str
    port: int
    source: str  # MODEL (from OPENAI_BASE_URL, the user's choice) | MANIFEST (runtime.egress)

    def __str__(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


def _port(text: str, what: str) -> int:
    if not _PORT_RE.fullmatch(text) or not 1 <= int(text) <= 65535:
        raise ValueError(f"{what}: {text!r} is not a port (1-65535)")
    return int(text)


def parse_entry(entry: object) -> tuple[str, int]:
    """(host, port) of a runtime.egress entry: an exact, lowercase host name, with an
    optional :port (443 when left out). No wildcards, no addresses, no URLs, and no name of
    the user's own machine or network. Raises ValueError (ready to show)."""
    if not isinstance(entry, str):
        raise ValueError(f"runtime.egress: {entry!r} is not a host name")
    host, sep, port_text = entry.partition(":")
    port = _port(port_text, f"runtime.egress entry {entry!r}") if sep else DEFAULT_PORT
    if len(host) > 253 or not _HOST_RE.fullmatch(host):
        raise ValueError(
            f"runtime.egress: {entry!r} is not an exact host name (lowercase, such as "
            "api.example.com or api.example.com:8443; no wildcard, address or URL)"
        )
    if host.endswith(_LOCAL_SUFFIXES):
        raise ValueError(
            f"runtime.egress: {entry!r} names the user's own machine or network, which an "
            "agent may not reach"
        )
    return host, port


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def model_destination(env: Mapping[str, str]) -> Destination | None:
    """Where the agent's model lives: the host and port of OPENAI_BASE_URL in `env`, or of
    api.openai.com when it is unset or empty. None when the URL points at the agent itself
    (localhost inside a container is the container): nothing to let through then.
    Raises ValueError (ready to show, without the URL's credentials or path)."""
    url = (env.get(MODEL_URL_KEY) or "").strip() or DEFAULT_MODEL_URL
    problem = f"{MODEL_URL_KEY} must be an http(s) URL with a host, such as {DEFAULT_MODEL_URL}"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError:
        raise ValueError(problem) from None
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(problem)
    if any(c.isspace() or ord(c) < 0x21 or ord(c) == 0x7F for c in host):
        raise ValueError(problem)
    if _is_loopback(host):
        return None
    return Destination(host, port or (443 if parts.scheme == "https" else 80), MODEL)


def uses_model(declared: Iterable[str]) -> bool:
    """The agent declares an OPENAI_* key, so it talks to a model."""
    return any(name.upper().startswith(MODEL_KEY_PREFIX) for name in declared)


def allowed(
    declared: Iterable[str], entries: Iterable[str] | None, env: Mapping[str, str]
) -> list[Destination]:
    """Every destination the door lets through for an agent that declares the keys
    `declared` and the runtime.egress `entries`, started with `env`. The model first; no
    duplicates. Raises ValueError (ready to show)."""
    found: dict[tuple[str, int], Destination] = {}
    if uses_model(declared):
        model = model_destination(env)
        if model is not None:
            found[(model.host, model.port)] = model
    for entry in entries or ():
        host, port = parse_entry(entry)
        found.setdefault((host, port), Destination(host, port, MANIFEST))
    return list(found.values())


def describe(destinations: Iterable[Destination]) -> str:
    """ "api.openai.com:443 (the model), files.example.com:443", or "nothing"."""
    parts = [f"{d} (the model)" if d.source == MODEL else str(d) for d in destinations]
    return ", ".join(parts) if parts else "nothing"


def proxy_env(no_proxy: Iterable[str] = ()) -> dict[str, str]:
    """The proxy variables of an agent's containers: web traffic goes to the door, except
    to the agent itself and to `no_proxy` (the names of its own services)."""
    proxy = f"http://{DOOR_ALIAS}:{PROXY_PORT}"
    direct = ",".join(dict.fromkeys(["localhost", "127.0.0.1", "::1", *no_proxy]))
    return {
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "NO_PROXY": direct,
        "http_proxy": proxy,
        "https_proxy": proxy,
        "no_proxy": direct,
    }


def door_config(destinations: Iterable[Destination]) -> str:
    """The door's allow list (its DOOR_ALLOW variable). A destination from the manifest must
    resolve to a public address; the model's, which the user chose, may be anywhere (a
    local model on the host or the local network)."""
    return json.dumps(
        [{"host": d.host, "port": d.port, "private": d.source == MODEL} for d in destinations],
        separators=(",", ":"),
    )
