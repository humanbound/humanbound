# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Run the arena gateway as a detached background process (or in the foreground).

The server stack (uvicorn, starlette, the gateway app) is imported lazily in `serve()`
so that callers which only need to start, probe or stop the gateway stay light."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from .. import __version__
from .paths import arena_dir, gateway_port, gateway_url

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
LOG_MAX_BYTES = 5 * 1024 * 1024


class GatewayError(RuntimeError):
    """The gateway could not be started. The message is ready to show."""


def pid_file() -> Path:
    return arena_dir() / "gateway.pid"


def log_file() -> Path:
    return arena_dir() / "gateway.log"


def _lock_file() -> Path:
    return arena_dir() / "gateway.lock"


def _health(port: int) -> dict | None:
    """The gateway's health body when it answers 2xx with status ok, else None."""
    try:
        resp = httpx.get(f"{gateway_url(port)}/arena/v1/health", timeout=1)
    except httpx.HTTPError:
        return None
    if not resp.is_success:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("status") != "ok":
        return None
    return body


def is_up(port: int) -> bool:
    return _health(port) is not None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def _spawn_lock() -> Iterator[None]:
    """Serialize check-spawn-wait across processes so two callers never both spawn."""
    arena_dir().mkdir(parents=True, exist_ok=True)
    with open(_lock_file(), "a+b") as fh:
        if os.name == "nt":
            # msvcrt.locking gives up after ~10s of retries and locks byte ranges, not the
            # file; the race it would close only costs a failed bind in the loser (which
            # then finds the winner healthy), so Windows runs unlocked.
            yield
            return
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _rotate_log() -> None:
    log = log_file()
    try:
        if log.stat().st_size > LOG_MAX_BYTES:
            os.replace(log, log.with_name(log.name + ".1"))
    except FileNotFoundError:
        pass


def _spawn(port: int) -> subprocess.Popen:
    _rotate_log()
    detach = (
        {"start_new_session": True}
        if os.name != "nt"
        else {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    with open(log_file(), "ab") as log:
        return subprocess.Popen(
            [sys.executable, "-m", "humanbound_cli.arena.daemon", "--port", str(port)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            **detach,
        )


def ensure_running(
    port: int | None = None, *, wait_s: float = 10, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Start the gateway in the background unless one of this version already answers.
    Returns its URL. A gateway of another version is stopped and replaced."""
    port = port or gateway_port()
    url = gateway_url(port)
    info = _health(port)
    if info is not None and info.get("version") == __version__:
        return url
    with _spawn_lock():
        info = _health(port)  # another caller may have started it while we waited
        if info is not None:
            if info.get("version") == __version__:
                return url
            if not stop_gateway(port, sleep=sleep):
                raise GatewayError(
                    f"an arena gateway of version {info.get('version')} is running on port "
                    f"{port} and could not be stopped → run `hb arena stop` or stop pid "
                    f"{info.get('pid')}"
                )
        if _port_in_use(port):
            raise GatewayError(
                f"port {port} is used by another program → set HB_ARENA_PORT to a free port"
            )
        proc = _spawn(port)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if is_up(port):
                return url
            if proc.poll() is not None:
                raise GatewayError(f"the arena gateway exited during startup; see {log_file()}")
            sleep(0.2)
        if is_up(port):
            return url
        if proc.poll() is not None:
            raise GatewayError(f"the arena gateway exited during startup; see {log_file()}")
        proc.terminate()
        raise GatewayError(
            f"the arena gateway did not become healthy within {wait_s:g}s; see {log_file()}"
        )


def stop_gateway(
    port: int | None = None, *, wait_s: float = 5, sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Stop the gateway answering on `port`. The pid comes from its health endpoint, never
    from the pidfile alone, so a stale pidfile can't make us signal an unrelated process.
    Returns True if a gateway was stopped."""
    port = port or gateway_port()
    info = _health(port)
    pid = info.get("pid") if info is not None else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        if info is None:
            pid_file().unlink(missing_ok=True)  # nothing answers: the pidfile is stale
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    deadline = time.monotonic() + wait_s
    while is_up(port):
        if time.monotonic() >= deadline:
            return False
        sleep(0.1)
    pid_file().unlink(missing_ok=True)
    return True


def serve(host: str = "127.0.0.1", port: int | None = None) -> None:
    """Run the gateway in the foreground. A non-loopback bind is an explicit opt-in to
    network exposure (the CLI is responsible for warning about it); loopback binds keep
    the gateway's default Host-header allowlist."""
    import uvicorn

    from .gateway import create_app

    kwargs: dict = {"pidfile": pid_file()}
    if host not in LOOPBACK_HOSTS:
        kwargs["allowed_hosts"] = ["*"]
    app = create_app(**kwargs)
    uvicorn.run(app, host=host.strip("[]"), port=port or gateway_port(), log_level="warning")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="humanbound_cli.arena.daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
