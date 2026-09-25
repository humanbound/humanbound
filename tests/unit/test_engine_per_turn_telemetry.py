# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Per-turn telemetry on the local engine.

Each generator drives a real ``Bot`` with a per-turn telemetry config (replies
carrying ``metadata.tool_calls``), with ``requests`` mocked. The metadata
returned by every ``Bot.ping()`` turn must reach
``Telemetry.standardize_accumulated_metadata`` so the judge sees tool calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.engine.bot import Bot, Telemetry
from humanbound_cli.engine.orchestrators.behavioral_qa import generator as behavioral_qa
from humanbound_cli.engine.orchestrators.owasp_agentic import generator as owasp_agentic
from humanbound_cli.engine.orchestrators.owasp_single_turn import generator as owasp_single_turn


def _response(body):
    r = MagicMock()
    r.status_code = 200
    r.is_redirect = False
    r.headers = {}
    r.json = MagicMock(return_value=body)
    return r


def _reply(text, tool_calls):
    metadata = {"latency_ms": 5}
    if tool_calls is not None:
        metadata["tool_calls"] = tool_calls
    return _response({"content": text, "metadata": metadata})


def _call(name, parameters, result):
    return {"name": name, "parameters": parameters, "result": result}


@pytest.fixture
def config():
    return {
        "streaming": None,
        "chat_completion": {
            "endpoint": "https://agent.example/chat",
            "payload": {"message": "$PROMPT"},
        },
        "telemetry": {
            "mode": "per_turn",
            "extraction_map": {"metadata_path": "metadata", "tool_executions": "tool_calls"},
        },
    }


@pytest.fixture
def clientbot(config):
    bot = Bot(config, e_id="exp-1")
    bot.init = MagicMock(return_value={})
    return bot


@pytest.fixture(autouse=True)
def _no_sleep():
    with (
        patch.object(owasp_agentic.time, "sleep"),
        patch.object(behavioral_qa.time, "sleep"),
    ):
        yield


def _conversationer(cls, clientbot, depth=0):
    conv = cls.__new__(cls)
    conv.clientbot = clientbot
    conv.llmp = MagicMock()
    conv.llmp.ping.return_value = "hello"
    conv.BASIC_TMPL = "<ATTACK_STRATEGY><TESTING_SCENARIO><CONVERSATION_HISTORY>"
    conv.conversation_depth = depth
    return conv


# Three turns: tools on turn 1, none reported on turn 2, two tools on turn 3.
THREE_TURNS = [
    _reply("a1", [_call("lookup", {"id": 7}, "found")]),
    _reply("a2", None),
    _reply("a3", [_call("refund", {"amount": 10}, "ok"), _call("email", {}, "sent")]),
]


def _assert_three_turn_tools(telemetry_data):
    assert telemetry_data["tool_executions"] == [
        {"turn": 1, "tool_name": "lookup", "parameters": {"id": 7}, "result": "found"},
        {"turn": 3, "tool_name": "refund", "parameters": {"amount": 10}, "result": "ok"},
        {"turn": 3, "tool_name": "email", "parameters": {}, "result": "sent"},
    ]
    # api_calls_count counts the turns that returned metadata (all three did)
    assert telemetry_data["resource_usage"] == {"api_calls_count": 3}


def test_owasp_agentic_passes_every_turns_tool_calls_to_telemetry(clientbot, config):
    conv = _conversationer(owasp_agentic.Conversationer, clientbot, depth=3)

    with patch("humanbound_cli.engine.bot.requests.post", side_effect=THREE_TURNS):
        conversation, _, _, telemetry_data = asyncio.run(
            conv.chat(
                lambda turn, history: "strategy",
                payload={},
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    assert [t["a"] for t in conversation] == ["a1", "a2", "a3"]
    _assert_three_turn_tools(telemetry_data)


def test_owasp_agentic_turn_numbers_continue_after_opening_turns(clientbot, config):
    conv = _conversationer(owasp_agentic.Conversationer, clientbot, depth=2)
    opening = [{"u": "opening", "a": "reply"}]
    reply = _reply("a2", [_call("lookup", {}, "found")])

    with patch("humanbound_cli.engine.bot.requests.post", return_value=reply):
        _, _, _, telemetry_data = asyncio.run(
            conv.chat(
                lambda turn, history: "strategy",
                payload={},
                conversation=opening,
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    assert [t["turn"] for t in telemetry_data["tool_executions"]] == [2]


def test_behavioral_qa_passes_every_turns_tool_calls_to_telemetry(clientbot, config):
    conv = _conversationer(behavioral_qa.Conversationer, clientbot, depth=3)

    with patch("humanbound_cli.engine.bot.requests.post", side_effect=THREE_TURNS):
        _, _, _, telemetry_data = asyncio.run(
            conv.chat(
                "scenario",
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    _assert_three_turn_tools(telemetry_data)


def test_owasp_single_turn_passes_the_turns_tool_calls_to_telemetry(clientbot, config):
    conv = _conversationer(owasp_single_turn.Conversationer, clientbot)
    reply = _reply("a1", [_call("lookup", {"id": 7}, "found")])

    with patch("humanbound_cli.engine.bot.requests.post", return_value=reply):
        response, _, _, telemetry_data = asyncio.run(
            conv.prompt(
                "hi",
                payload={},
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    assert response == "a1"
    assert telemetry_data["tool_executions"] == [
        {"turn": 1, "tool_name": "lookup", "parameters": {"id": 7}, "result": "found"}
    ]


def test_owasp_single_turn_without_metadata_yields_empty_telemetry(clientbot, config):
    conv = _conversationer(owasp_single_turn.Conversationer, clientbot)
    reply = _response({"content": "a1"})

    with patch("humanbound_cli.engine.bot.requests.post", return_value=reply):
        _, _, _, telemetry_data = asyncio.run(
            conv.prompt(
                "hi",
                payload={},
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    assert telemetry_data["tool_executions"] == []
    assert telemetry_data["resource_usage"] == {}
