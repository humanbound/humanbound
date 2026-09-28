# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The engine's Bot never sends a loopback endpoint (a local agent, the arena gateway)
through a proxy from the environment; other endpoints keep honouring it.

A real HTTP server on 127.0.0.1 stands in for the agent, and every proxy variable points
at a closed port: a call that honoured them would fail to connect.
"""

from __future__ import annotations

import asyncio
import http.server
import json
from unittest.mock import MagicMock

import pytest

from humanbound_cli.engine import bot as bot_module
from humanbound_cli.engine.bot import Bot, Telemetry

from .arena_testing import local_http_server, route_proxies_to_nowhere


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._send(json.dumps({"traces": []}).encode(), "application/json")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/sse":
            events = [{"content": "local "}, {"content": "stream"}, {"type": "end"}]
            data = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()
            self._send(data, "text/event-stream")
            return
        self._send(
            json.dumps({"reply": f"local: {body.get('prompt', '')}"}).encode(), "application/json"
        )

    def log_message(self, *args):
        pass


@pytest.fixture
def local_port():
    with local_http_server(_Handler) as port:
        yield port


@pytest.fixture(autouse=True)
def proxies_everywhere(monkeypatch):
    route_proxies_to_nowhere(monkeypatch)


def _config(url, streaming=None):
    return {
        "streaming": streaming,
        "chat_completion": {"endpoint": url, "headers": {}, "payload": {"prompt": "$PROMPT"}},
    }


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_chat_to_a_loopback_endpoint_ignores_proxies_on_every_call(local_port, host):
    """requests adds environment proxies into the dict it is given: each call needs its own."""
    bot = Bot(_config(f"http://{host}:{local_port}/chat"), "e1")
    base = bot.init()
    for prompt in ("one", "two", "three"):
        assert asyncio.run(bot.ping(base, prompt))[0] == f"local: {prompt}"


def test_thread_init_to_a_loopback_endpoint_ignores_proxies(local_port):
    config = _config(f"http://127.0.0.1:{local_port}/chat")
    config["thread_init"] = {
        "endpoint": f"http://127.0.0.1:{local_port}/init",
        "headers": {},
        "payload": {},
    }
    base = Bot(config, "e1").init()
    assert base["reply"] == "local: "


def test_sse_to_a_loopback_endpoint_ignores_proxies(local_port):
    bot = Bot(_config(f"http://127.0.0.1:{local_port}/sse", streaming="sse"), "e1")
    text, _, _ = asyncio.run(bot.ping(bot.init(), "hi"))
    assert text == "local stream"


def test_telemetry_fetch_from_a_loopback_endpoint_ignores_proxies(local_port):
    telemetry = Telemetry(
        {
            "mode": "end_of_conversation",
            "format": "langfuse",
            "method": "GET",
            "endpoint": f"http://127.0.0.1:{local_port}/traces",
            "headers": {},
            "payload": {},
        },
        "e1",
    )
    call = telemetry._Telemetry__make_api_call
    assert call({}, f"http://127.0.0.1:{local_port}/traces", {}, {}) == {"traces": []}


@pytest.mark.parametrize(
    "url, loopback",
    [
        ("http://127.0.0.1:8000/x", True),
        ("http://127.3.2.1/x", True),
        ("http://localhost:11500/a2a/echo", True),
        ("http://LOCALHOST/x", True),
        ("http://[::1]:8000/x", True),
        ("https://api.example.com/chat", False),
        ("http://10.0.0.5/x", False),
        ("http://localhost.example.com/x", False),
        ("http://127.0.0.1.nip.io/x", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_is_loopback(url, loopback):
    assert bot_module._is_loopback(url) is loopback


def test_remote_endpoints_keep_the_environment_proxies(monkeypatch):
    seen = []

    def fake_post(url, **kwargs):
        seen.append(kwargs)
        resp = MagicMock(status_code=200, is_redirect=False, headers={})
        resp.json.return_value = {"reply": "remote"}
        return resp

    monkeypatch.setattr(bot_module.requests, "post", fake_post)
    bot = Bot(_config("https://agent.example.com/chat"), "e1")
    assert asyncio.run(bot.ping(bot.init(), "hi"))[0] == "remote"
    assert "proxies" not in seen[0]


def test_loopback_requests_get_no_proxies(monkeypatch):
    seen = []

    def fake_post(url, **kwargs):
        seen.append(kwargs)
        resp = MagicMock(status_code=200, is_redirect=False, headers={})
        resp.json.return_value = {"reply": "local"}
        return resp

    monkeypatch.setattr(bot_module.requests, "post", fake_post)
    bot = Bot(_config("http://127.0.0.1:11500/a2a/echo"), "e1")
    base = bot.init()
    asyncio.run(bot.ping(base, "a"))
    asyncio.run(bot.ping(base, "b"))
    assert seen[0]["proxies"] == {"http": None, "https": None, "all": None}
    assert seen[0]["proxies"] is not seen[1]["proxies"]


def test_websocket_to_a_loopback_endpoint_disables_proxies(monkeypatch):
    ws_client = pytest.importorskip("websockets.asyncio.client")
    seen = {}

    def fake_connect(url, **kwargs):
        seen.update(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(ws_client, "connect", fake_connect)
    bot = Bot(_config("ws://127.0.0.1:9999/ws", streaming="websocket"), "e1")
    with pytest.raises(Exception, match="stop here"):
        asyncio.run(bot.ping(bot.init(), "hi"))
    if bot_module._ws_supports_proxy():
        assert seen.get("proxy", "unset") is None
    seen.clear()
    bot = Bot(_config("wss://agent.example.com/ws", streaming="websocket"), "e1")
    with pytest.raises(Exception, match="stop here"):
        asyncio.run(bot.ping(bot.init(), "hi"))
    assert "proxy" not in seen
