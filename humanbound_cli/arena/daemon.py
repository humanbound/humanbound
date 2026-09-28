# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The background gateway process: health-checked start, version replacement, safe stop.

`ensure_running` spawns `python -m humanbound_cli.arena.daemon` detached and waits for its
health endpoint. Health checks present this owner's access token (paths.gateway_token()):
only a gateway that accepts it reports its version, pid and owner, and one that doesn't is
another owner's. The pidfile is owned by the child (the gateway writes it at startup and
removes it at shutdown); `stop_gateway` signals a pid only when an authenticated health
response reports our owner and that same pid is in our pidfile. A gateway of another owner
on our port is never used, replaced or stopped. Starlette and uvicorn are imported only
inside `serve`, so importing this module stays cheap.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx

from .. import __version__
from .paths import (
    LOOPBACK_HOSTS,
    arena_dir,
    arena_owner,
    auth_headers,
    ensure_arena_dir,
    gateway_port,
    gateway_token,
    gateway_url,
)

__all__ = [
    "GatewayError",
    "ensure_running",
    "is_up",
    "log_file",
    "main",
    "pid_file",
    "serve",
    "stop_gateway",
]

LOG_MAX_BYTES = 5 * 1024 * 1024
TOKEN_NAME = "gateway.token"
POLL_INTERVAL_S = 0.2


class GatewayError(RuntimeError):
    """The gateway could not be started or replaced."""


def pid_file(port: int | None = None) -> Path:
    """The pidfile of our gateway on `port` (one per port, so a foreground `serve --port`
    next to the detached gateway doesn't take over its pidfile)."""
    return arena_dir() / f"gateway-{port or gateway_port()}.pid"


def log_file() -> Path:
    return arena_dir() / "gateway.log"


def _lock_file() -> Path:
    return arena_dir() / "gateway.lock"


# ── probes ──


def _health(port: int) -> dict | None:
    """The gateway's health answer: full ({status, version, pid, owner}) when it accepted our
    token, just {"status": "ok"} when it didn't. Never creates the token."""
    token = gateway_token(create=False)
    headers = auth_headers(token) if token else None
    try:
        # trust_env=False: a proxy from the environment must never see loopback calls.
        resp = httpx.get(
            f"{gateway_url(port)}/arena/v1/health",
            headers=headers,
            timeout=2.0,
            trust_env=False,
        )
    except httpx.HTTPError:
        return None
    if not resp.is_success:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("status") == "ok":
        return data
    return None


def _foreign(health: dict | None) -> bool:
    """A gateway of another owner (another HOME on this machine): it says so, or it didn't
    accept our token (a bare {"status": "ok"}). One without an owner predates owners: not
    foreign, but `stop_gateway` won't signal it either."""
    if health is None:
        return False
    if "version" not in health:
        return True
    owner = health.get("owner")
    return bool(owner) and owner != arena_owner()


def is_up(port: int | None = None, *, any_owner: bool = False) -> bool:
    """Our gateway answers on `port` (with any_owner: any arena gateway does)."""
    health = _health(port or gateway_port())
    return health is not None and (any_owner or not _foreign(health))


def _foreign_error(port: int) -> GatewayError:
    return GatewayError(
        f"port {port} is used by another program (an hb arena gateway of another user or "
        f"HOME, or one started with another {TOKEN_NAME}); set HB_ARENA_PORT to a free port"
    )


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


# ── start ──


@contextlib.contextmanager
def _gateway_lock() -> Iterator[None]:
    """An exclusive lock so two `hb` processes don't both spawn a gateway."""
    if os.name == "nt":
        # No fcntl on Windows; a concurrent double start there just loses the port race
        # and the second child exits.
        yield
        return
    import fcntl

    ensure_arena_dir()
    path = _lock_file()
    with open(path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _rotate_log(path: Path) -> None:
    try:
        if path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass  # missing, or can't be rotated (e.g. open elsewhere on Windows): keep appending


def _spawn(port: int) -> subprocess.Popen:
    ensure_arena_dir()
    log = log_file()
    _rotate_log(log)
    argv = [sys.executable, "-m", "humanbound_cli.arena.daemon", "--port", str(port)]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    # The log may hold agent errors: readable by the user only.
    with open(log, "ab", opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
        if os.name != "nt":
            os.fchmod(out.fileno(), 0o600)
        return subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **kwargs
        )


def _current(health: dict | None) -> bool:
    return (
        health is not None
        and health.get("version") == __version__
        and health.get("owner") == arena_owner()
    )


def ensure_running(
    port: int | None = None,
    *,
    wait_s: float = 10,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Make sure an up-to-date gateway answers on `port`; return its URL."""
    port = port or gateway_port()
    url = gateway_url(port)
    health = _health(port)
    if _current(health):
        return url
    if _foreign(health):
        raise _foreign_error(port)
    with _gateway_lock():
        health = _health(port)
        if _current(health):
            return url
        if _foreign(health):
            raise _foreign_error(port)
        if health is not None:
            stop_gateway(port, sleep=sleep)
            if is_up(port):
                raise GatewayError(
                    f"a gateway from hb {health.get('version')} (pid {health.get('pid')}) "
                    f"is running on port {port} and could not be stopped"
                )
        if _port_in_use(port):
            raise GatewayError(
                f"port {port} is used by another program; set HB_ARENA_PORT to a free port"
            )
        gateway_token()  # the child and our health checks read the same token file
        proc = _spawn(port)
        attempts = max(1, int(wait_s / POLL_INTERVAL_S))
        for _ in range(attempts):
            if is_up(port):
                return url
            if proc.poll() is not None:
                if _foreign(_health(port)):
                    # Another owner's gateway won the race for the port.
                    raise _foreign_error(port)
                raise GatewayError(f"the gateway exited during startup; see {log_file()}")
            sleep(POLL_INTERVAL_S)
        if is_up(port):
            return url
        proc.terminate()
        raise GatewayError(
            f"the gateway did not become healthy within {wait_s:g}s; see {log_file()}"
        )


# ── stop ──


def _pidfile_pid(port: int) -> int | None:
    try:
        text = pid_file(port).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() and int(text) > 0 else None


def stop_gateway(
    port: int | None = None,
    *,
    wait_s: float = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Stop our gateway answering on `port`. A pid is signalled only when a health response
    that accepted our token reports this owner and that pid, and our pidfile holds the same
    pid; anything else (another owner's gateway, an unrelated process) is left alone."""
    port = port or gateway_port()
    health = _health(port)
    if health is None:
        pid_file(port).unlink(missing_ok=True)  # stale: nobody answers
        return False
    if _foreign(health) or health.get("owner") != arena_owner():
        return False
    pid = health.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if pid != _pidfile_pid(port):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    attempts = max(1, int(wait_s / POLL_INTERVAL_S))
    for _ in range(attempts):
        if not is_up(port):
            pid_file(port).unlink(missing_ok=True)
            return True
        sleep(POLL_INTERVAL_S)
    if not is_up(port):
        pid_file(port).unlink(missing_ok=True)
        return True
    return False


# ── the child ──


def serve(host: str = "127.0.0.1", port: int | None = None) -> None:
    import uvicorn

    from .gateway import DEFAULT_ALLOWED_HOSTS, create_app

    allowed = list(DEFAULT_ALLOWED_HOSTS) if host in LOOPBACK_HOSTS else ["*"]
    bind = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    port = port or gateway_port()
    app = create_app(allowed_hosts=allowed, pidfile=pid_file(port))
    uvicorn.run(app, host=bind, port=port, log_level="warning")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m humanbound_cli.arena.daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
