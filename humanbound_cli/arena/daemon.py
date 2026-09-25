# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Run the arena gateway as a detached background process (or in the foreground)."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import uvicorn

from .gateway import create_app
from .paths import arena_dir, gateway_port, gateway_url

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class GatewayError(RuntimeError):
    """The gateway could not be started. The message is ready to show."""


def pid_file() -> Path:
    return arena_dir() / "gateway.pid"


def log_file() -> Path:
    return arena_dir() / "gateway.log"


def is_up(port: int) -> bool:
    try:
        return httpx.get(f"{gateway_url(port)}/arena/v1/health", timeout=1).is_success
    except httpx.HTTPError:
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_running(
    port: int | None = None, *, wait_s: float = 10, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Start the gateway in the background unless it already answers. Returns its URL."""
    port = port or gateway_port()
    if is_up(port):
        return gateway_url(port)
    if _port_in_use(port):
        raise GatewayError(
            f"port {port} is used by another program → set HB_ARENA_PORT to a free port"
        )
    arena_dir().mkdir(parents=True, exist_ok=True)
    detach = (
        {"start_new_session": True}
        if os.name != "nt"
        else {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    with open(log_file(), "ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "humanbound_cli.arena.daemon", "--port", str(port)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            **detach,
        )
    pid_file().write_text(str(proc.pid))
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_up(port):
            return gateway_url(port)
        if proc.poll() is not None:
            break
        sleep(0.2)
    raise GatewayError(f"the arena gateway failed to start; see {log_file()}")


def stop_gateway() -> bool:
    path = pid_file()
    if not path.exists():
        return False
    try:
        os.kill(int(path.read_text().strip()), signal.SIGTERM)
    except (ProcessLookupError, ValueError):
        pass
    path.unlink(missing_ok=True)
    return True


def serve(host: str = "127.0.0.1", port: int | None = None) -> None:
    """Run the gateway in the foreground. A non-loopback bind is an explicit opt-in to
    network exposure (the CLI is responsible for warning about it); loopback binds keep
    the gateway's default Host-header allowlist."""
    kwargs = {} if host in LOOPBACK_HOSTS else {"allowed_hosts": ["*"]}
    app = create_app(**kwargs)
    uvicorn.run(app, host=host, port=port or gateway_port(), log_level="warning")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="humanbound_cli.arena.daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
