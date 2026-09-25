# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import signal
import sys

import httpx
import pytest
import uvicorn

from humanbound_cli import __version__
from humanbound_cli.arena import daemon, gateway
from humanbound_cli.arena.daemon import GatewayError

OK = {"status": "ok", "version": __version__, "pid": 4242}


def _states(*values):
    """A health stub returning each value in turn, then repeating the last one."""
    seq = list(values)

    def health(port):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return health


class Proc:
    pid = 4242

    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True


@pytest.fixture
def no_port_conflict(monkeypatch):
    monkeypatch.setattr(daemon, "_port_in_use", lambda port: False)


# ── is_up / health ──


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self.is_success = 200 <= status < 300
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"status": "ok", "version": "x"}, True),
        (200, {"status": "starting"}, False),
        (200, ["ok"], False),
        (200, ValueError("not json"), False),
        (500, {"status": "ok"}, False),
    ],
)
def test_is_up_requires_2xx_and_status_ok(monkeypatch, status, payload, expected):
    monkeypatch.setattr(daemon.httpx, "get", lambda *a, **k: _Resp(status, payload))
    assert daemon.is_up(12345) is expected


def test_is_up_is_false_when_unreachable(monkeypatch):
    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(daemon.httpx, "get", refuse)
    assert daemon.is_up(12345) is False


def test_loopback_hosts_include_bracketed_ipv6():
    assert "[::1]" in daemon.LOOPBACK_HOSTS


# ── ensure_running ──


def test_ensure_running_is_a_noop_when_up(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "_health", lambda port: OK)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not spawn"))
    assert daemon.ensure_running(12345) == "http://127.0.0.1:12345"


def test_ensure_running_spawns_detached_and_waits(arena_home, monkeypatch, no_port_conflict):
    monkeypatch.setattr(daemon, "_health", _states(None, None, None, OK))
    spawned = {}

    def popen(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs
        return Proc()

    monkeypatch.setattr(daemon.subprocess, "Popen", popen)
    url = daemon.ensure_running(12345, sleep=lambda _: None)
    assert url == "http://127.0.0.1:12345"
    assert spawned["argv"] == [
        sys.executable,
        "-m",
        "humanbound_cli.arena.daemon",
        "--port",
        "12345",
    ]
    # the child owns the pidfile; the parent never writes it
    assert not daemon.pid_file().exists()


def test_ensure_running_rechecks_under_the_lock(arena_home, monkeypatch):
    """A concurrent caller that started the gateway while we waited for the lock wins."""
    monkeypatch.setattr(daemon, "_health", _states(None, OK))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not spawn"))
    assert daemon.ensure_running(12345) == "http://127.0.0.1:12345"
    assert (arena_home / "gateway.lock").exists()


def test_ensure_running_replaces_a_gateway_of_another_version(
    arena_home, monkeypatch, no_port_conflict
):
    old = {"status": "ok", "version": "0.0.0-old", "pid": 99}
    monkeypatch.setattr(daemon, "_health", _states(old, old, OK))
    stopped = []

    def fake_stop(port=None, **kwargs):
        stopped.append(port)
        return True

    monkeypatch.setattr(daemon, "stop_gateway", fake_stop)
    spawned = []
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: spawned.append(1) or Proc())
    assert daemon.ensure_running(12345, sleep=lambda _: None) == "http://127.0.0.1:12345"
    assert stopped == [12345]
    assert spawned == [1]


def test_ensure_running_reports_an_old_gateway_it_cannot_stop(arena_home, monkeypatch):
    old = {"status": "ok", "version": "0.0.0-old", "pid": 99}
    monkeypatch.setattr(daemon, "_health", lambda port: old)
    monkeypatch.setattr(daemon, "stop_gateway", lambda port=None, **k: False)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not spawn"))
    with pytest.raises(GatewayError, match="0.0.0-old"):
        daemon.ensure_running(12345, sleep=lambda _: None)


def test_ensure_running_refuses_a_foreign_port(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "_health", lambda port: None)
    monkeypatch.setattr(daemon, "_port_in_use", lambda port: True)
    with pytest.raises(GatewayError, match="HB_ARENA_PORT"):
        daemon.ensure_running(12345)


def test_ensure_running_reports_a_crashed_gateway(arena_home, monkeypatch, no_port_conflict):
    monkeypatch.setattr(daemon, "_health", lambda port: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: Proc(exit_code=1))
    with pytest.raises(GatewayError, match="exited.*gateway.log"):
        daemon.ensure_running(12345, sleep=lambda _: None)


def test_ensure_running_kills_a_gateway_that_never_gets_healthy(
    arena_home, monkeypatch, no_port_conflict
):
    monkeypatch.setattr(daemon, "_health", lambda port: None)
    proc = Proc()
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: proc)
    with pytest.raises(GatewayError, match=r"did not become healthy within 0.05s.*gateway.log"):
        daemon.ensure_running(12345, wait_s=0.05, sleep=lambda _: None)
    assert proc.terminated


def test_ensure_running_rotates_a_large_log(arena_home, monkeypatch, no_port_conflict):
    arena_home.mkdir(parents=True)
    daemon.log_file().write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (arena_home / "gateway.log.1").write_text("older")
    monkeypatch.setattr(daemon, "_health", _states(None, None, OK))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: Proc())
    daemon.ensure_running(12345, sleep=lambda _: None)
    assert (arena_home / "gateway.log.1").stat().st_size == 5 * 1024 * 1024 + 1
    assert daemon.log_file().stat().st_size == 0


def test_ensure_running_keeps_a_small_log(arena_home, monkeypatch, no_port_conflict):
    arena_home.mkdir(parents=True)
    daemon.log_file().write_text("recent")
    monkeypatch.setattr(daemon, "_health", _states(None, None, OK))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: Proc())
    daemon.ensure_running(12345, sleep=lambda _: None)
    assert daemon.log_file().read_text() == "recent"
    assert not (arena_home / "gateway.log.1").exists()


# ── stop_gateway ──


def test_stop_gateway_signals_the_pid_reported_by_health(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    daemon.pid_file().write_text("1111")  # not trusted: health is the source of truth
    monkeypatch.setattr(daemon, "_health", lambda port: OK)
    up = iter([True, True, False])
    monkeypatch.setattr(daemon, "is_up", lambda port: next(up))
    killed = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    assert daemon.stop_gateway(12345, sleep=lambda _: None) is True
    assert killed == [(4242, signal.SIGTERM)]
    assert not daemon.pid_file().exists()


def test_stop_gateway_removes_a_stale_pidfile_without_signalling(arena_home, monkeypatch):
    arena_home.mkdir(parents=True)
    daemon.pid_file().write_text("4242")
    monkeypatch.setattr(daemon, "_health", lambda port: None)
    monkeypatch.setattr(daemon.os, "kill", lambda *a: pytest.fail("must not signal"))
    assert daemon.stop_gateway(12345) is False
    assert not daemon.pid_file().exists()


def test_stop_gateway_needs_a_pid_from_health(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "_health", lambda port: {"status": "ok", "version": "x"})
    monkeypatch.setattr(daemon.os, "kill", lambda *a: pytest.fail("must not signal"))
    assert daemon.stop_gateway(12345) is False


@pytest.mark.parametrize("exc", [ProcessLookupError, PermissionError])
def test_stop_gateway_tolerates_signal_failures(arena_home, monkeypatch, exc):
    monkeypatch.setattr(daemon, "_health", lambda port: OK)

    def kill(pid, sig):
        raise exc()

    monkeypatch.setattr(daemon.os, "kill", kill)
    assert daemon.stop_gateway(12345, sleep=lambda _: None) is False


# ── serve (imports are lazy) ──


def test_daemon_module_does_not_import_the_server_stack():
    assert not hasattr(daemon, "uvicorn")
    assert not hasattr(daemon, "create_app")


def test_serve_uses_default_allowed_hosts_for_loopback(arena_home, monkeypatch):
    captured = {}

    def fake_create_app(**kwargs):
        captured["create_app_kwargs"] = kwargs
        return "the-app"

    def fake_run(app, **kwargs):
        captured["run_kwargs"] = kwargs
        captured["app"] = app

    monkeypatch.setattr(gateway, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    daemon.serve("127.0.0.1", 12345)
    assert captured["app"] == "the-app"
    assert "allowed_hosts" not in captured["create_app_kwargs"]
    assert captured["create_app_kwargs"]["pidfile"] == daemon.pid_file()
    assert captured["run_kwargs"]["host"] == "127.0.0.1"
    assert captured["run_kwargs"]["port"] == 12345


@pytest.mark.parametrize("host", ["::1", "[::1]", "localhost"])
def test_serve_treats_ipv6_and_named_loopback_as_loopback(arena_home, monkeypatch, host):
    captured = {}
    monkeypatch.setattr(gateway, "create_app", lambda **k: captured.update(k) or "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: None)
    daemon.serve(host, 12345)
    assert "allowed_hosts" not in captured


def test_serve_opens_allowed_hosts_for_a_non_loopback_bind(arena_home, monkeypatch):
    captured = {}

    def fake_create_app(**kwargs):
        captured["create_app_kwargs"] = kwargs
        return "the-app"

    monkeypatch.setattr(gateway, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: None)
    daemon.serve("0.0.0.0", 12345)
    assert captured["create_app_kwargs"]["allowed_hosts"] == ["*"]
