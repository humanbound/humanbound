# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Per-turn telemetry on the local engine.

Each generator drives a real ``Bot`` with a per-turn telemetry config (replies
carrying ``metadata.tool_calls``), with ``requests`` mocked. The metadata
returned by every ``Bot.ping()`` turn must reach
``Telemetry.standardize_accumulated_metadata`` so the judge sees tool calls,
including the fixed opening turn OWASP agentic sends before generated turns.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.engine.bot import Bot, Telemetry
from humanbound_cli.engine.orchestrators.behavioral_qa import generator as behavioral_qa
from humanbound_cli.engine.orchestrators.owasp_agentic import generator as owasp_agentic
from humanbound_cli.engine.orchestrators.owasp_agentic import (
    orchestrator as owasp_agentic_orchestrator,
)
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


# ── the opening turn (owasp_agentic sends a fixed opener before the generated turns) ──

_single_pipeline_run = getattr(owasp_agentic_orchestrator, "__do_single_pipeline_run")


class _CapturingJudge:
    def __init__(self):
        self.telemetry_data = "unset"

    def evaluate(self, conversation, telemetry_data=None):
        self.telemetry_data = telemetry_data
        return {
            "result": "pass",
            "category": "",
            "explanation": "",
            "severity": 0,
            "confidence": 100,
        }


def _run_pipeline(clientbot, replies, telemetry_config, depth=3):
    conv = _conversationer(owasp_agentic.Conversationer, clientbot, depth=depth)
    judge = _CapturingJudge()
    telemetry_client = Telemetry(telemetry_config, "exp-1") if telemetry_config else None
    with (
        patch("humanbound_cli.engine.bot.requests.post", side_effect=replies) as post,
        patch.object(owasp_agentic_orchestrator.time, "sleep"),
    ):
        logs, _ = asyncio.run(
            _single_pipeline_run(
                conv,
                judge,
                "GOAL: test",
                "category",
                "org",
                {"id": "exp-1"},
                [],
                100,
                telemetry_config=telemetry_config,
                telemetry_client=telemetry_client,
                opening="opening prompt",
            )
        )
    return logs, judge, post


def test_owasp_agentic_opening_turn_tool_calls_reach_judge_and_saved_log(clientbot, config):
    logs, judge, _ = _run_pipeline(clientbot, THREE_TURNS, config["telemetry"])

    assert len(logs) == 1 and logs[0]["result"] == "pass"
    assert [t["a"] for t in logs[0]["conversation"]] == ["a1", "a2", "a3"]
    _assert_three_turn_tools(judge.telemetry_data)
    assert [t["turn"] for t in judge.telemetry_data["turns"]] == [1, 2, 3]

    saved = logs[0]["meta"][0]["telemetry"]
    assert [(t["turn"], t["tool_name"]) for t in saved["tool_executions"]] == [
        (1, "lookup"),
        (3, "refund"),
        (3, "email"),
    ]
    assert [t["turn"] for t in saved["turns"]] == [1, 2, 3]


def test_owasp_agentic_opening_turn_only(clientbot, config):
    """A conversation that ends with the opener still reports the opener's tool calls."""
    reply = _reply("a1", [_call("lookup", {"id": 7}, "found")])
    logs, judge, _ = _run_pipeline(clientbot, [reply], config["telemetry"], depth=1)

    assert judge.telemetry_data["tool_executions"] == [
        {"turn": 1, "tool_name": "lookup", "parameters": {"id": 7}, "result": "found"}
    ]


def test_owasp_agentic_opening_turn_end_of_conversation_unchanged(clientbot):
    telemetry_config = {
        "mode": "end_of_conversation",
        "endpoint": "https://agent.example/telemetry",
        "extraction_map": {"tool_executions": "tool_calls"},
    }
    with patch.object(Telemetry, "fetch", return_value={"tool_executions": []}) as fetch:
        logs, judge, _ = _run_pipeline(clientbot, THREE_TURNS, telemetry_config)

    fetch.assert_called_once()
    assert fetch.call_args.args[1] == 3
    assert judge.telemetry_data == {"tool_executions": []}


def test_owasp_agentic_opening_turn_without_telemetry_config(clientbot):
    logs, judge, post = _run_pipeline(clientbot, THREE_TURNS, None)

    assert post.call_count == 3
    assert judge.telemetry_data is None
    assert logs[0]["meta"] == []


def test_owasp_agentic_prompt_and_chat_keep_their_return_shapes(clientbot, config):
    conv = _conversationer(owasp_agentic.Conversationer, clientbot, depth=2)
    opening_metadata = []
    with patch("humanbound_cli.engine.bot.requests.post", side_effect=THREE_TURNS[:2]):
        pre, _, _, payload = asyncio.run(
            conv.prompt("opening", payload={}, metadata=opening_metadata)
        )
        result = asyncio.run(
            conv.chat(
                lambda turn, history: "strategy",
                payload=payload,
                conversation=pre,
                opening_metadata=opening_metadata,
                telemetry_client=Telemetry,
                telemetry_config=config["telemetry"],
            )
        )

    assert pre == [{"u": "opening", "a": "a1"}]
    assert [m["turn"] for m in opening_metadata] == [1]
    assert len(result) == 4
    assert [t["turn"] for t in result[3]["tool_executions"]] == [1]
