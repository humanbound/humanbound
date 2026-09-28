# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Loopback calls (daemon health, agent health, reset, gateway → agent) ignore proxy env vars.

A real HTTP server on 127.0.0.1 stands in for the gateway/agent, and the proxy variables
point at a closed port: any call that honoured them would fail to connect.
"""

from __future__ import annotations

import http.server
import json

import pytest
from starlette.testclient import TestClient

from humanbound_cli.arena import daemon, runtime, target
from humanbound_cli.arena.gateway import create_app
from humanbound_cli.arena.manifest import Health
from humanbound_cli.arena.runtime import RunningAgent

from .arena_testing import local_http_server, route_proxies_to_nowhere
from .test_arena_gateway import ECHO, FakeRegistry, RegistryEntry


class _Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._json({"status": "ok", "version": "x", "pid": 1})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._json({"reply": f"local: {body.get('prompt', '')}", "id": "echo"})

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    with local_http_server(_Handler) as port:
        yield port


@pytest.fixture(autouse=True)
def _isolated_home(arena_home):
    return arena_home


@pytest.fixture(autouse=True)
def proxies_everywhere(monkeypatch):
    route_proxies_to_nowhere(monkeypatch)


def test_daemon_health_ignores_proxy(local_server):
    assert daemon._health(local_server) is not None


def test_wait_healthy_default_getter_ignores_proxy(local_server):
    agent = RunningAgent("echo", "0.1.0", "image", local_server)
    runtime.wait_healthy(agent, Health(path="/health", timeout_s=1), sleep=lambda s: None)


def test_reset_via_gateway_ignores_proxy(local_server):
    target.reset_via_gateway("echo", f"http://127.0.0.1:{local_server}")


def test_gateway_client_ignores_proxy(local_server):
    agent = RunningAgent("echo", ECHO.version, "image", local_server)
    registry = FakeRegistry([ECHO])
    registry.entries["echo"] = RegistryEntry(
        agent=agent, manifest=ECHO, agent_dir=registry.entries["echo"].agent_dir
    )
    app = create_app(registry, allowed_hosts=["testserver"], token="x" * 43)
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "SendMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": "m", "parts": [{"text": "hi"}]}},
    }
    with TestClient(app) as client:
        assert client.app.state.http.trust_env is False
        resp = client.post("/a2a/echo", json=body, headers={"X-Arena-Token": "x" * 43})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["message"]["parts"][0]["text"] == "local: hi"
