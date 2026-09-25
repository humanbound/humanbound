# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import asyncio
from unittest.mock import MagicMock, patch

import pytest
import yaml
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import target
from humanbound_cli.arena.a2a import message_result
from humanbound_cli.arena.manifest import load_manifest
from humanbound_cli.arena.runtime import RunningAgent
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
    assert target.is_arena_target("arena://echo")
    assert not target.is_arena_target("./config.json")
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
    with patch("humanbound_cli.arena.target.httpx.post", return_value=resp):
        with pytest.raises(TargetError, match="boom"):
            target.reset_via_gateway("echo", "http://127.0.0.1:11500")
