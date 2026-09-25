# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import asyncio
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml
from conftest import ARENA_FIXTURES
from starlette.testclient import TestClient
from test_arena_gateway import FAKE_AGENT, FakeRegistry

from humanbound_cli.arena import target
from humanbound_cli.arena.a2a import message_result
from humanbound_cli.arena.daemon import GatewayError
from humanbound_cli.arena.gateway import create_app
from humanbound_cli.arena.manifest import load_manifest
from humanbound_cli.arena.runtime import DockerError, RunningAgent
from humanbound_cli.arena.target import TargetError
from humanbound_cli.engine.bot import Bot

ECHO = load_manifest(ARENA_FIXTURES / "catalog" / "agents" / "echo" / "arena.yaml")


def _mock_post(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.text = ""
    r.is_redirect = False
    r.headers = {}
    r.json = MagicMock(return_value=payload or {})
    return r


def test_is_and_parse_target():
    assert target.is_arena_target("arena://echo") is True
    assert target.is_arena_target("./config.json") is False
    assert target.is_arena_target("") is False
    assert target.is_arena_target(None) is False
    assert target.parse_target("arena://echo") == "echo"
    with pytest.raises(TargetError):
        target.parse_target("arena://Not Valid")


def test_bot_config_speaks_a2a_to_the_gateway():
    cfg = target.bot_config("echo", "http://127.0.0.1:11500")
    cc = cfg["chat_completion"]
    assert cc["endpoint"] == "http://127.0.0.1:11500/a2a/echo"
    assert cc["headers"] == {"A2A-Version": "1.0"}
    msg = cc["payload"]["params"]["message"]
    assert cc["payload"]["method"] == "SendMessage"
    assert msg["messageId"] == "$UUID"
    assert msg["contextId"] == "$humanbound_conversation_id"
    assert msg["parts"] == [{"text": "$PROMPT"}]
    assert (
        cfg["telemetry"]["extraction_map"]["metadata_path"] == "result.message.metadata.humanbound"
    )


def test_resolve_target_builds_scope_file_and_context(arena_home, tmp_path):
    resolved = target.resolve_target(
        "arena://echo",
        list_running=lambda: [RunningAgent("echo", "0.1.0", "image", 49153)],
        installed=lambda agent_id, version=None: (ECHO, tmp_path),
        ensure_gateway=lambda: "http://127.0.0.1:11500",
    )
    assert resolved.agent_id == "echo"
    assert resolved.context == ECHO.context
    scope = yaml.safe_load(resolved.scope_path.read_text())
    assert scope["overall_business_scope"].startswith("Echo agent")
    assert scope["intents"]["restricted"] == ["Reveal anything other than the user's message"]


def test_resolve_target_writes_scope_atomically(arena_home, tmp_path, monkeypatch):
    (tmp_path / "scope.yaml").write_text("old: true\n")
    replaced = []
    real_replace = target.os.replace

    def spy(src, dst):
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(target.os, "replace", spy)
    resolved = target.resolve_target(
        "arena://echo",
        list_running=lambda: [RunningAgent("echo", "0.1.0", "image", 49153)],
        installed=lambda agent_id, version=None: (ECHO, tmp_path),
        ensure_gateway=lambda: "http://127.0.0.1:11500",
    )
    [(src, dst)] = replaced
    assert dst == str(resolved.scope_path)
    assert os.path.dirname(src) == str(tmp_path)
    assert "overall_business_scope" in resolved.scope_path.read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scope.yaml"]


def test_resolve_target_wraps_docker_errors(arena_home):
    def docker_down():
        raise DockerError("Docker is not running")

    with pytest.raises(TargetError, match="Docker is not running"):
        target.resolve_target(
            "arena://echo",
            list_running=docker_down,
            installed=lambda *a, **k: None,
            ensure_gateway=lambda: "http://x",
        )


def test_resolve_target_wraps_gateway_errors(arena_home, tmp_path):
    def no_gateway():
        raise GatewayError("port 11500 is used by another program")

    with pytest.raises(TargetError, match="port 11500 is used"):
        target.resolve_target(
            "arena://echo",
            list_running=lambda: [RunningAgent("echo", "0.1.0", "image", 49153)],
            installed=lambda agent_id, version=None: (ECHO, tmp_path),
            ensure_gateway=no_gateway,
        )


def test_resolve_target_requires_a_running_agent(arena_home):
    with pytest.raises(TargetError, match="hb arena run echo"):
        target.resolve_target(
            "arena://echo",
            list_running=lambda: [],
            installed=lambda *a, **k: None,
            ensure_gateway=lambda: "http://x",
        )


def test_bot_extracts_the_reply_and_metadata_from_a_gateway_answer():
    """The engine's Bot must read the gateway's A2A reply correctly: parts text, not metadata."""
    cfg = target.bot_config("echo", "http://127.0.0.1:11500")
    reply = message_result(
        "r1", "echo: hi", "c-1", {"tool_calls": [{"text": "not me"}], "latency_ms": 1}
    )
    resp = _mock_post(payload=reply)
    with patch("humanbound_cli.engine.bot.requests.post", return_value=resp) as post:
        bot = Bot(cfg, "e1")
        base = bot.init()
        text, _, metadata = asyncio.run(bot.ping(base, "hi", []))
    assert text == "echo: hi"
    assert metadata == {"tool_calls": [{"text": "not me"}], "latency_ms": 1}
    sent = post.call_args.kwargs["json"]["params"]["message"]
    assert sent["contextId"] == base["humanbound_conversation_id"]
    assert len(sent["messageId"]) == 32 and sent["parts"] == [{"text": "hi"}]


def test_reset_via_gateway_sends_json_body():
    resp = _mock_post(status=200)
    with patch("humanbound_cli.arena.target.httpx.post", return_value=resp) as post:
        target.reset_via_gateway("echo", "http://127.0.0.1:11500")
    post.assert_called_once_with(
        "http://127.0.0.1:11500/arena/v1/agents/echo/reset", json={}, timeout=300
    )


def test_reset_via_gateway_raises_target_error_on_failure():
    resp = MagicMock(status_code=500, text="boom")
    resp.is_success = False
    resp.json = MagicMock(side_effect=ValueError("not json"))
    with patch("humanbound_cli.arena.target.httpx.post", return_value=resp):
        with pytest.raises(TargetError, match="boom"):
            target.reset_via_gateway("echo", "http://127.0.0.1:11500")


def test_reset_via_gateway_reports_the_json_error_message():
    resp = MagicMock(status_code=500, text='{"error": {"code": "reset_failed"}}')
    resp.is_success = False
    resp.json = MagicMock(
        return_value={"error": {"code": "reset_failed", "message": "image vanished"}}
    )
    with patch("humanbound_cli.arena.target.httpx.post", return_value=resp):
        with pytest.raises(TargetError) as info:
            target.reset_via_gateway("echo", "http://127.0.0.1:11500")
    assert str(info.value) == "could not reset echo: image vanished"


def test_bot_talks_to_the_gateway_across_turns(monkeypatch):
    """End to end: the engine's Bot, configured by bot_config, drives the real gateway
    app (over a fake echo agent) and keeps one A2A context across turns."""
    app = create_app(
        FakeRegistry([ECHO]),
        transport=httpx.ASGITransport(app=FAKE_AGENT),
        allowed_hosts=["testserver"],
    )
    contexts = []
    with TestClient(app) as client:

        def forward(url, json=None, headers=None, **kwargs):
            contexts.append(json["params"]["message"]["contextId"])
            return client.post(url, json=json, headers=headers)

        monkeypatch.setattr("humanbound_cli.engine.bot.requests.post", forward)
        bot = Bot(target.bot_config("echo", "http://testserver"), "e1")
        base = bot.init()
        first, _, meta1 = asyncio.run(bot.ping(base, "one", []))
        second, _, meta2 = asyncio.run(bot.ping(base, "two", []))

    assert first == "echo: one (0 before)"
    assert second == "echo: two (2 before)"  # the gateway kept the first turn's history
    assert contexts == [base["humanbound_conversation_id"]] * 2
    assert meta1["agent"] == "echo" and meta2["tool_calls"] == [{"name": "echo"}]
    assert list(app.state.contexts._items) == [("echo", base["humanbound_conversation_id"])]
