# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Helpers shared by the arena tests (and the loopback tests of the engine's Bot)."""

from __future__ import annotations

import contextlib
import http.server
import os
import stat
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

ARENA_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "arena"
CATALOG = ARENA_FIXTURES / "catalog"
ECHO_YAML = CATALOG / "agents" / "echo" / "arena.yaml"

DIGEST = "sha256:" + "0123456789abcdef" * 4
SHA = "c0cf9a14adad76e9d6a53c41741f625334bd9971"

# A closed port: a call that honoured the proxy variables would fail to connect.
DEAD_PROXY = "http://127.0.0.1:9"


def mode_of(path) -> int:
    """The permission bits of `path`."""
    return stat.S_IMODE(os.stat(path).st_mode)


def completed(argv, rc=0, stdout="", stderr="") -> subprocess.CompletedProcess:
    """What runtime._run returns for a docker call."""
    return subprocess.CompletedProcess(argv, rc, stdout, stderr)


def returns(*items):
    """A no-argument callable returning a fresh list of `items` (e.g. list_running)."""
    return lambda: list(items)


def route_proxies_to_nowhere(monkeypatch) -> None:
    """Point every proxy variable at a closed port and clear NO_PROXY."""
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, DEAD_PROXY)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


@contextlib.contextmanager
def local_http_server(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[int]:
    """A real HTTP server on 127.0.0.1 (a free port) for the duration; yields the port."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
