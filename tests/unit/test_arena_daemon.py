# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import signal
import sys

import pytest

from humanbound_cli.arena import daemon
from humanbound_cli.arena.daemon import GatewayError


def test_ensure_running_is_a_noop_when_up(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "is_up", lambda port: True)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not spawn"))
    assert daemon.ensure_running(12345) == "http://127.0.0.1:12345"


def test_ensure_running_spawns_detached_and_waits(arena_home, monkeypatch):
    states = iter([False, False, True])
    monkeypatch.setattr(daemon, "is_up", lambda port: next(states))
    monkeypatch.setattr(daemon, "_port_in_use", lambda port: False)
    spawned = {}

    class Proc:
        pid = 4242

        def poll(self):
            return None

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
    assert daemon.pid_file().read_text() == "4242"


def test_ensure_running_refuses_a_foreign_port(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "is_up", lambda port: False)
    monkeypatch.setattr(daemon, "_port_in_use", lambda port: True)
    with pytest.raises(GatewayError, match="HB_ARENA_PORT"):
        daemon.ensure_running(12345)


def test_ensure_running_reports_a_crashed_gateway(arena_home, monkeypatch):
    monkeypatch.setattr(daemon, "is_up", lambda port: False)
    monkeypatch.setattr(daemon, "_port_in_use", lambda port: False)

    class Dead:
        pid = 1

        def poll(self):
            return 1

    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: Dead())
    with pytest.raises(GatewayError, match="gateway.log"):
        daemon.ensure_running(12345, sleep=lambda _: None)


def test_stop_gateway_signals_and_cleans_up(arena_home, monkeypatch):
    daemon.pid_file().parent.mkdir(parents=True, exist_ok=True)
    daemon.pid_file().write_text("4242")
    killed = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    assert daemon.stop_gateway() is True
    assert killed == [(4242, signal.SIGTERM)]
    assert not daemon.pid_file().exists()
    assert daemon.stop_gateway() is False


def test_serve_uses_default_allowed_hosts_for_loopback(monkeypatch):
    captured = {}

    def fake_create_app(**kwargs):
        captured["create_app_kwargs"] = kwargs
        return "the-app"

    def fake_run(app, **kwargs):
        captured["run_kwargs"] = kwargs
        captured["app"] = app

    monkeypatch.setattr(daemon, "create_app", fake_create_app)
    monkeypatch.setattr(daemon, "uvicorn", type("U", (), {"run": staticmethod(fake_run)}))
    daemon.serve("127.0.0.1", 12345)
    assert captured["app"] == "the-app"
    assert "allowed_hosts" not in captured["create_app_kwargs"]
    assert captured["run_kwargs"]["host"] == "127.0.0.1"
    assert captured["run_kwargs"]["port"] == 12345


def test_serve_opens_allowed_hosts_for_a_non_loopback_bind(monkeypatch):
    captured = {}

    def fake_create_app(**kwargs):
        captured["create_app_kwargs"] = kwargs
        return "the-app"

    monkeypatch.setattr(daemon, "create_app", fake_create_app)
    monkeypatch.setattr(
        daemon, "uvicorn", type("U", (), {"run": staticmethod(lambda app, **k: None)})
    )
    daemon.serve("0.0.0.0", 12345)
    assert captured["create_app_kwargs"]["allowed_hosts"] == ["*"]
