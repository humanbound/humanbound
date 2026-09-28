# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the gateway daemon. No real processes, sockets to real gateways, or uvicorn."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys

import httpx
import pytest

from humanbound_cli import __version__
from humanbound_cli.arena import daemon, paths
from humanbound_cli.arena.gateway import DEFAULT_ALLOWED_HOSTS

from .arena_testing import mode_of

PORT = 12345
URL = f"http://127.0.0.1:{PORT}"


def _ok(version=__version__, pid=4242, owner=None):
    """A healthy gateway; by default this owner's (HOME's)."""
    owner = paths.arena_owner() if owner is None else owner
    return {"status": "ok", "version": version, "pid": pid, "owner": owner}


FOREIGN = "ffffffffffff"


class FakeProc:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True


class Harness:
    """Scripted `_health` answers plus recorded spawns, stops and lock usage."""

    def __init__(self, monkeypatch, healths, *, port_in_use=False, proc=None):
        self.healths = list(healths)
        self.health_calls = []
        self.popen_calls = []
        self.stops = []
        self.locked = False
        self.proc = proc or FakeProc()

        def fake_health(port):
            self.health_calls.append((port, self.locked))
            if len(self.healths) > 1:
                return self.healths.pop(0)
            return self.healths[0]

        def fake_popen(argv, **kwargs):
            self.popen_calls.append((argv, kwargs))
            return self.proc

        @contextlib.contextmanager
        def fake_lock():
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        monkeypatch.setattr(daemon, "_health", fake_health)
        monkeypatch.setattr(daemon, "_port_in_use", lambda port: port_in_use)
        monkeypatch.setattr(daemon, "_gateway_lock", fake_lock)
        monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)


def _no_sleep(_s):
    pass


# ── _health / is_up ──


def _mock_get(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def fake_get(url, headers=None, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.get(url, headers=headers)

    monkeypatch.setattr(daemon.httpx, "get", fake_get)


def test_health_ok(arena_home, monkeypatch):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json=_ok())

    _mock_get(monkeypatch, handler)
    token = paths.gateway_token()
    assert daemon._health(PORT) == _ok()
    assert seen == [(f"{URL}/arena/v1/health", f"Bearer {token}")]
    assert daemon.is_up(PORT) is True


def test_health_without_a_token_file_never_creates_one(arena_home, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"status": "ok"})

    _mock_get(monkeypatch, handler)
    assert daemon._health(PORT) == {"status": "ok"}
    assert seen == [None]
    assert not paths.token_file().exists()


def test_ensure_running_creates_the_token_before_spawning(arena_home, monkeypatch):
    h = Harness(monkeypatch, [None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    assert len(h.popen_calls) == 1
    assert paths.gateway_token(create=False)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"status": "ok"}),
        httpx.Response(200, json={"status": "starting"}),
        httpx.Response(200, json=[1]),
        httpx.Response(200, text="not json"),
    ],
)
def test_health_rejects_bad_answers(monkeypatch, response):
    _mock_get(monkeypatch, lambda request: response)
    assert daemon._health(PORT) is None
    assert daemon.is_up(PORT) is False


def test_health_connection_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    _mock_get(monkeypatch, handler)
    assert daemon._health(PORT) is None


def test_port_in_use_uses_connect_ex(monkeypatch):
    calls = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect_ex(self, addr):
            calls.append(addr)
            return 0

    monkeypatch.setattr(daemon.socket, "socket", lambda *a, **k: FakeSock())
    assert daemon._port_in_use(PORT) is True
    assert calls == [("127.0.0.1", PORT)]


def test_paths(arena_home):
    assert daemon.pid_file(PORT) == arena_home / f"gateway-{PORT}.pid"
    assert daemon.pid_file() == arena_home / "gateway-11500.pid"
    assert daemon.log_file() == arena_home / "gateway.log"


# ── ensure_running ──


def test_up_to_date_gateway_is_noop(arena_home, monkeypatch):
    h = Harness(monkeypatch, [_ok()])
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert h.popen_calls == []
    assert h.health_calls == [(PORT, False)]


def test_recheck_under_lock_finds_gateway(arena_home, monkeypatch):
    # another hb started it while we waited for the lock
    h = Harness(monkeypatch, [None, _ok()])
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert h.popen_calls == []
    assert h.health_calls == [(PORT, False), (PORT, True)]


def test_default_port_from_env(arena_home, monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "12999")
    h = Harness(monkeypatch, [_ok()])
    assert daemon.ensure_running(sleep=_no_sleep) == "http://127.0.0.1:12999"
    assert h.health_calls[0][0] == 12999


def test_spawn_argv_detach_and_no_parent_pidfile(arena_home, monkeypatch):
    h = Harness(monkeypatch, [None, None, None, _ok()])
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert len(h.popen_calls) == 1
    argv, kwargs = h.popen_calls[0]
    assert argv == [sys.executable, "-m", "humanbound_cli.arena.daemon", "--port", str(PORT)]
    if os.name == "nt":
        assert kwargs["creationflags"] == (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["stdout"].name == str(daemon.log_file())
    assert not daemon.pid_file(PORT).exists()


def test_spawn_all_under_lock(arena_home, monkeypatch):
    h = Harness(monkeypatch, [None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    assert all(locked for _, locked in h.health_calls[1:])


def test_foreign_port_hint(arena_home, monkeypatch):
    h = Harness(monkeypatch, [None], port_in_use=True)
    with pytest.raises(daemon.GatewayError, match="set HB_ARENA_PORT to a free port"):
        daemon.ensure_running(PORT, sleep=_no_sleep)
    assert h.popen_calls == []


def test_child_exits_during_startup(arena_home, monkeypatch):
    Harness(monkeypatch, [None], proc=FakeProc(exit_code=1))
    with pytest.raises(daemon.GatewayError, match="exited during startup; see .*gateway.log"):
        daemon.ensure_running(PORT, sleep=_no_sleep)


def test_timeout_terminates_child(arena_home, monkeypatch):
    proc = FakeProc()
    sleeps = []
    Harness(monkeypatch, [None], proc=proc)
    with pytest.raises(daemon.GatewayError, match="did not become healthy within 2s"):
        daemon.ensure_running(PORT, wait_s=2, sleep=sleeps.append)
    assert proc.terminated is True
    assert len(sleeps) == int(2 / daemon.POLL_INTERVAL_S)


def test_log_rotation(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    log = daemon.log_file()
    log.write_bytes(b"x" * (daemon.LOG_MAX_BYTES + 1))
    Harness(monkeypatch, [None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    rotated = log.with_name("gateway.log.1")
    assert rotated.stat().st_size == daemon.LOG_MAX_BYTES + 1
    assert log.stat().st_size == 0


def test_small_log_not_rotated(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    log = daemon.log_file()
    log.write_bytes(b"small")
    Harness(monkeypatch, [None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    assert log.read_bytes() == b"small"
    assert not log.with_name("gateway.log.1").exists()


def test_version_mismatch_replaced(arena_home, monkeypatch):
    old = _ok(version="0.0.1", pid=77)
    # outside lock, under lock, then is_up after stop -> gone, then healthy new child
    h = Harness(monkeypatch, [old, old, None, _ok()])
    stops = []

    def fake_stop(port, **kwargs):
        stops.append(port)
        return True

    monkeypatch.setattr(daemon, "stop_gateway", fake_stop)
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert stops == [PORT]
    assert len(h.popen_calls) == 1


def test_version_mismatch_cannot_stop(arena_home, monkeypatch):
    old = _ok(version="0.0.1", pid=77)
    h = Harness(monkeypatch, [old])
    monkeypatch.setattr(daemon, "stop_gateway", lambda port, **kw: False)
    with pytest.raises(daemon.GatewayError, match=r"hb 0\.0\.1 \(pid 77\)"):
        daemon.ensure_running(PORT, sleep=_no_sleep)
    assert h.popen_calls == []


def test_real_lock_file_created(arena_home, monkeypatch):
    if os.name == "nt":
        pytest.skip("no flock on Windows")
    answers = [None, _ok()]
    monkeypatch.setattr(daemon, "_health", lambda port: answers.pop(0))
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert (arena_home / "gateway.lock").exists()


# ── stop_gateway ──


def _stop_harness(monkeypatch, healths, kill_exc=None):
    kills = []
    answers = list(healths)

    def fake_health(port):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def fake_kill(pid, sig):
        kills.append((pid, sig))
        if kill_exc:
            raise kill_exc

    monkeypatch.setattr(daemon, "_health", fake_health)
    monkeypatch.setattr(daemon.os, "kill", fake_kill)
    return kills


def _pidfile(pid):
    paths.ensure_arena_dir()
    daemon.pid_file(PORT).write_text(str(pid))


def test_stop_signals_our_gateway(arena_home, monkeypatch):
    _pidfile(4242)
    kills = _stop_harness(monkeypatch, [_ok(pid=4242), _ok(pid=4242), None])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is True
    assert kills == [(4242, signal.SIGTERM)]
    assert not daemon.pid_file(PORT).exists()


def test_stop_needs_the_pid_in_our_pidfile(arena_home, monkeypatch):
    """A health answer alone (a process on our port) is not enough to signal its pid."""
    _pidfile(999)
    kills = _stop_harness(monkeypatch, [_ok(pid=4242)])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []
    assert daemon.pid_file(PORT).read_text() == "999"


@pytest.mark.parametrize("content", [None, "", "abc", "4242.0", "-4242"])
def test_stop_without_a_usable_pidfile(arena_home, monkeypatch, content):
    if content is not None:
        _pidfile(content)
    kills = _stop_harness(monkeypatch, [_ok(pid=4242)])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []


@pytest.mark.parametrize(
    "health",
    [
        {"status": "ok"},  # didn't accept our token
        {"status": "ok", "version": __version__, "pid": 4242},  # no owner
        {"status": "ok", "version": __version__, "pid": 4242, "owner": FOREIGN},
    ],
)
def test_stop_needs_our_owner_in_an_authenticated_health(arena_home, monkeypatch, health):
    _pidfile(4242)
    kills = _stop_harness(monkeypatch, [health])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []


def test_stop_stale_pidfile_no_kill(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    daemon.pid_file(PORT).write_text("4242")
    kills = _stop_harness(monkeypatch, [None])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []
    assert not daemon.pid_file(PORT).exists()


@pytest.mark.parametrize("pid", [None, "4242", True, 0, -1])
def test_stop_no_usable_pid(arena_home, monkeypatch, pid):
    kills = _stop_harness(monkeypatch, [{"status": "ok", "version": __version__, "pid": pid}])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []


@pytest.mark.parametrize("exc", [ProcessLookupError(), PermissionError()])
def test_stop_kill_errors(arena_home, monkeypatch, exc):
    _pidfile(4242)
    kills = _stop_harness(monkeypatch, [_ok()], kill_exc=exc)
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert len(kills) == 1


def test_stop_still_up_returns_false(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    daemon.pid_file(PORT).write_text("4242")
    _stop_harness(monkeypatch, [_ok()])
    assert daemon.stop_gateway(PORT, wait_s=1, sleep=_no_sleep) is False
    assert daemon.pid_file(PORT).exists()


# ── owners ──


def test_foreign_owner_gateway_on_our_port_is_refused(arena_home, monkeypatch):
    h = Harness(monkeypatch, [_ok(owner=FOREIGN)])
    stops = []
    monkeypatch.setattr(daemon, "stop_gateway", lambda port, **kw: stops.append(port))
    with pytest.raises(daemon.GatewayError) as e:
        daemon.ensure_running(PORT, sleep=_no_sleep)
    message = str(e.value)
    assert f"port {PORT} is used by another program" in message
    assert "HB_ARENA_PORT" in message
    assert stops == [] and h.popen_calls == []


def test_foreign_owner_gateway_of_another_version_is_refused(arena_home, monkeypatch):
    h = Harness(monkeypatch, [_ok(version="0.0.1", owner=FOREIGN)])
    monkeypatch.setattr(daemon, "stop_gateway", lambda port, **kw: pytest.fail("stopped"))
    with pytest.raises(daemon.GatewayError, match="another program"):
        daemon.ensure_running(PORT, sleep=_no_sleep)
    assert h.popen_calls == []


def test_gateway_without_owner_is_replaced(arena_home, monkeypatch):
    legacy = {"status": "ok", "version": __version__, "pid": 77}
    h = Harness(monkeypatch, [legacy, legacy, None, _ok()])
    stops = []
    monkeypatch.setattr(daemon, "stop_gateway", lambda port, **kw: stops.append(port) or True)
    assert daemon.ensure_running(PORT, sleep=_no_sleep) == URL
    assert stops == [PORT] and len(h.popen_calls) == 1


def test_gateway_that_rejects_our_token_is_foreign(arena_home, monkeypatch):
    """Only `{"status": "ok"}`: a gateway that didn't accept our token is not ours."""
    h = Harness(monkeypatch, [{"status": "ok"}])
    monkeypatch.setattr(daemon, "stop_gateway", lambda port, **kw: pytest.fail("stopped"))
    with pytest.raises(daemon.GatewayError, match="another program"):
        daemon.ensure_running(PORT, sleep=_no_sleep)
    assert h.popen_calls == []
    assert daemon.is_up(PORT) is False
    assert daemon.is_up(PORT, any_owner=True) is True


def test_is_up_only_for_our_gateway(monkeypatch):
    monkeypatch.setattr(daemon, "_health", lambda port: _ok(owner=FOREIGN))
    assert daemon.is_up(PORT) is False
    assert daemon.is_up(PORT, any_owner=True) is True
    monkeypatch.setattr(daemon, "_health", lambda port: _ok())
    assert daemon.is_up(PORT) is True


def test_stop_never_signals_a_foreign_gateway(arena_home, monkeypatch):
    kills = _stop_harness(monkeypatch, [_ok(owner=FOREIGN)])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is False
    assert kills == []


# ── serve / main ──


@pytest.fixture
def served(arena_home, monkeypatch):
    import uvicorn

    import humanbound_cli.arena.gateway as gateway

    calls = {}

    def fake_create_app(**kwargs):
        calls["create_app"] = kwargs
        return "APP"

    def fake_run(app, **kwargs):
        calls["run"] = (app, kwargs)

    monkeypatch.setattr(gateway, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    return calls


def test_serve_loopback(served):
    daemon.serve("127.0.0.1", PORT)
    assert served["create_app"] == {
        "allowed_hosts": list(DEFAULT_ALLOWED_HOSTS),
        "pidfile": daemon.pid_file(PORT),
    }
    assert served["run"] == ("APP", {"host": "127.0.0.1", "port": PORT, "log_level": "warning"})


def test_serve_all_interfaces_allows_any_host(served):
    daemon.serve("0.0.0.0", PORT)
    assert served["create_app"]["allowed_hosts"] == ["*"]
    assert served["run"][1]["host"] == "0.0.0.0"


def test_serve_ipv6_brackets_stripped(served):
    daemon.serve("[::1]", PORT)
    assert served["create_app"]["allowed_hosts"] == list(DEFAULT_ALLOWED_HOSTS)
    assert served["run"][1]["host"] == "::1"


def test_serve_default_port(served, monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "13000")
    daemon.serve()
    assert served["run"][1]["port"] == 13000


def test_main_parses_args(monkeypatch):
    calls = []
    monkeypatch.setattr(daemon, "serve", lambda host, port: calls.append((host, port)))
    daemon.main(["--host", "0.0.0.0", "--port", "11501"])
    daemon.main([])
    assert calls == [("0.0.0.0", 11501), ("127.0.0.1", None)]


def test_child_exits_and_a_foreign_gateway_answers(arena_home, monkeypatch):
    # We lost a race for the port to another owner's gateway: say so clearly.
    Harness(monkeypatch, [None, None, _ok(owner=FOREIGN)], proc=FakeProc(exit_code=1))
    with pytest.raises(daemon.GatewayError, match="another program.*HB_ARENA_PORT"):
        daemon.ensure_running(PORT, sleep=_no_sleep)


# ── permissions ──


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_spawn_creates_private_dir_and_log(arena_home, monkeypatch):
    Harness(monkeypatch, [None, None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    assert mode_of(arena_home) == 0o700
    assert mode_of(daemon.log_file()) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_spawn_tightens_an_existing_log(arena_home, monkeypatch):
    arena_home.mkdir(parents=True, mode=0o755)
    daemon.log_file().write_text("old\n")
    os.chmod(daemon.log_file(), 0o644)
    Harness(monkeypatch, [None, None, None, _ok()])
    daemon.ensure_running(PORT, sleep=_no_sleep)
    assert mode_of(arena_home) == 0o700
    assert mode_of(daemon.log_file()) == 0o600


def test_rotate_log_never_raises(arena_home, monkeypatch):
    """A log that can't be rotated (e.g. held open on Windows) is simply appended to."""
    paths.ensure_arena_dir()
    log = daemon.log_file()
    log.write_bytes(b"x" * (daemon.LOG_MAX_BYTES + 1))

    def denied(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(daemon.os, "replace", denied)
    daemon._rotate_log(log)
    assert log.exists()


def test_a_gateway_on_another_port_has_its_own_pidfile(arena_home, monkeypatch):
    """`hb arena serve --port P` next to the detached gateway: each stays stoppable."""
    paths.ensure_arena_dir()
    daemon.pid_file(PORT).write_text("4242")
    daemon.pid_file(PORT + 1).write_text("5151")
    kills = _stop_harness(monkeypatch, [_ok(pid=4242), None])
    assert daemon.stop_gateway(PORT, sleep=_no_sleep) is True
    assert kills == [(4242, signal.SIGTERM)]
    assert daemon.pid_file(PORT + 1).read_text() == "5151"
