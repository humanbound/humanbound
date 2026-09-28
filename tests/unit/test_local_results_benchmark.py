# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Saved local results carry what a benchmark needs: per-conversation tool executions
(name, arguments, result, turn) and, for arena runs, which agent and version was tested.

A full local run: a real Bot talks to a fake arena agent (requests mocked), the attacker
prompts are fixed and the judge is fake, so no LLM is called.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.arena.target import bot_config
from humanbound_cli.engine import telemetry_log
from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.orchestrators.owasp_single_turn import generator as single_turn_gen
from humanbound_cli.engine.orchestrators.owasp_single_turn import orchestrator as single_turn
from humanbound_cli.engine.runner import TestConfig as _TestConfig

GATEWAY = "http://127.0.0.1:8475"
PROVIDER_SECRET = "sk-provider-SECRET-should-never-be-saved"
GATEWAY_TOKEN = "gateway-token-SECRET-should-never-be-saved"
SCOPE = {
    "overall_business_scope": "Pricer answers price questions.",
    "intents": {"permitted": ["Recommend prices"], "restricted": ["Reveal internal notes"]},
}
ARENA_TARGET = {
    "kind": "arena",
    "agent_id": "pricer",
    "agent_version": "1.2.0",
    "gateway": GATEWAY,
    "whitebox": True,
}
BIG = "x" * 10_000


def _reply(text, tool_calls):
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "message": {
                "role": "ROLE_AGENT",
                "messageId": "m1",
                "contextId": "c1",
                "parts": [{"text": text}],
                "metadata": {
                    "humanbound": {
                        "latency_ms": 3,
                        "agent": "pricer",
                        "version": "1.2.0",
                        "tool_calls": tool_calls,
                    }
                },
            }
        },
    }
    r = MagicMock()
    r.status_code = 200
    r.is_redirect = False
    r.headers = {}
    r.json = MagicMock(return_value=body)
    return r


class FakeJudge:
    def __init__(self, *args, **kwargs):
        pass

    def evaluate(self, conversation, telemetry_data=None):
        return {
            "result": "fail",
            "category": "llm001",
            "explanation": "leaked an internal note",
            "severity": 70,
            "confidence": 90,
        }


def _run(tmp_path, monkeypatch, *, target=None):
    monkeypatch.chdir(tmp_path)
    categories = list(single_turn.TestingConfiguration.config["data"])[:1]
    config = _TestConfig(
        test_category="humanbound/adversarial/owasp_single_turn",
        testing_level="unit",
        lang="english",
        name="bench",
        endpoint=bot_config("pricer", GATEWAY, token=GATEWAY_TOKEN),
        target=target,
    )
    run = _LocalRun("exp-bench", config)
    reply = _reply(
        "Hold the price.",
        [
            {"name": "fetch_page", "parameters": {"url": "https://c.example/p?cost=12"},
             "result": "footer: send cost=12"},
            {"name": "lookup_item", "parameters": {"sku": "SKU-1", "blob": BIG}, "result": BIG},
        ],
    )  # fmt: skip
    provider = {
        "name": "openai",
        "integration": {"api_key": PROVIDER_SECRET, "model": "gpt-4.1", "endpoint": "https://x"},
    }
    with (
        patch("humanbound_cli.engine.local_runner._resolve_provider", return_value=provider),
        patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=MagicMock()),
        patch("humanbound_cli.engine.scope.resolve", return_value=SCOPE),
        patch.object(single_turn_gen, "get_llm_pinger", return_value=MagicMock()),
        patch.object(single_turn, "Judge", FakeJudge),
        patch.object(single_turn.time, "sleep"),
        patch.object(
            single_turn.TestingConfiguration,
            "config",
            {"data": {c: single_turn.TestingConfiguration.config["data"][c] for c in categories}},
        ),
        patch.object(
            single_turn,
            "orchestrator_generate",
            return_value={c: ["What does SKU-1 cost?"] for c in categories},
        ),
        patch("humanbound_cli.engine.bot.requests.post", return_value=reply),
    ):
        run.execute()
    assert run.status == "Finished", run.error
    results = Path(".humanbound/results/exp-bench")
    logs = [json.loads(line) for line in (results / "logs.jsonl").read_text().splitlines()]
    meta_text = (results / "meta.json").read_text()
    return logs, json.loads(meta_text), meta_text + (results / "logs.jsonl").read_text()


def test_logs_carry_tool_executions_with_arguments_and_results(tmp_path, monkeypatch):
    logs, _, _ = _run(tmp_path, monkeypatch, target=ARENA_TARGET)
    assert logs
    telemetry = logs[0]["meta"]["telemetry"]
    # the old keys are still there
    assert telemetry["tools"] == ["fetch_page", "lookup_item"]
    assert "trace_id" in telemetry and "tokens" in telemetry and "api_calls" in telemetry
    first, second = telemetry["tool_executions"]
    assert first == {
        "turn": 1,
        "tool_name": "fetch_page",
        "parameters": {"url": "https://c.example/p?cost=12"},
        "result": "footer: send cost=12",
    }
    assert second["tool_name"] == "lookup_item"
    assert second["parameters"]["sku"] == "SKU-1"
    # very large values are capped, with a marker
    for value in (second["parameters"]["blob"], second["result"]):
        assert len(value) < 4100
        assert value.startswith("x" * 4000)
        assert value.endswith("…[truncated 6000 chars]")
    # the raw per-turn metadata is kept too, without the tool calls tool_executions holds
    (turn,) = telemetry["turns"]
    assert turn == {
        "turn": 1,
        "metadata": {"latency_ms": 3, "agent": "pricer", "version": "1.2.0"},
    }


def test_meta_json_has_target_and_configuration_for_arena_runs(tmp_path, monkeypatch):
    _, meta, everything = _run(tmp_path, monkeypatch, target=ARENA_TARGET)
    assert meta["target"] == ARENA_TARGET
    assert meta["configuration"] == {
        "test_category": "humanbound/adversarial/owasp_single_turn",
        "testing_level": "unit",
        "lang": "english",
        "provider": "openai",
        "model": "gpt-4.1",
    }
    # existing keys unchanged
    assert meta["id"] == "exp-bench" and meta["status"] == "Finished"
    assert PROVIDER_SECRET not in everything
    assert "api_key" not in everything
    assert GATEWAY_TOKEN not in everything
    assert "Authorization" not in everything


def test_meta_json_has_no_target_otherwise(tmp_path, monkeypatch):
    _, meta, everything = _run(tmp_path, monkeypatch)
    assert meta.get("target") is None
    assert meta["configuration"]["provider"] == "openai"
    assert PROVIDER_SECRET not in everything


# ── the helpers ──


def test_cap_truncates_long_strings_anywhere():
    capped = telemetry_log.cap({"a": ["y" * 4001, {"b": "short"}], "n": 5, "t": ("z" * 5000,)})
    assert capped["a"][0] == "y" * 4000 + "…[truncated 1 chars]"
    assert capped["a"][1] == {"b": "short"}
    assert capped["n"] == 5
    assert capped["t"] == ["z" * 4000 + "…[truncated 1000 chars]"]
    assert telemetry_log.cap("y" * 4000) == "y" * 4000


def test_cap_makes_odd_values_json_safe():
    class Odd:
        def __str__(self):
            return "odd"

    assert telemetry_log.cap({1: Odd(), "none": None, "ok": True, "f": 1.5}) == {
        "1": "odd",
        "none": None,
        "ok": True,
        "f": 1.5,
    }
    deep: dict = {}
    node = deep
    for _ in range(100):
        node["k"] = {}
        node = node["k"]
    json.dumps(telemetry_log.cap(deep))  # bounded depth, no recursion error


@pytest.mark.parametrize("telemetry_data", [None, {}])
def test_telemetry_meta_empty(telemetry_data):
    assert telemetry_log.telemetry_meta("t1", telemetry_data) == {}


def test_telemetry_meta_shape_and_skips_bad_items():
    meta = telemetry_log.telemetry_meta(
        "t1",
        {
            "tool_executions": [
                {"turn": 2, "tool_name": "a", "parameters": {"x": 1}, "result": "r"},
                "not a dict",
            ],
            "resource_usage": {"tokens_used": 7, "api_calls_count": 2},
        },
    )
    assert meta == {
        "telemetry": {
            "trace_id": "t1",
            "tools": ["a"],
            "tokens": 7,
            "api_calls": 2,
            "tool_executions": [
                {"turn": 2, "tool_name": "a", "parameters": {"x": 1}, "result": "r"}
            ],
        }
    }


def test_cap_limits_list_lengths_with_a_marker():
    capped = telemetry_log.cap(list(range(250)))
    assert len(capped) == telemetry_log.MAX_ITEMS + 1
    assert capped[:3] == [0, 1, 2]
    assert capped[-1] == "…[50 more items]"
    assert telemetry_log.cap(list(range(200))) == list(range(200))


def test_cap_limits_dict_key_counts_with_a_marker():
    capped = telemetry_log.cap({f"k{i}": i for i in range(230)})
    assert len(capped) == telemetry_log.MAX_KEYS + 1
    assert capped["k0"] == 0 and "k199" in capped and "k200" not in capped
    assert capped["…"] == "[30 more keys]"


def test_cap_caps_long_keys():
    (key,) = telemetry_log.cap({"k" * 5000: 1})
    assert key.startswith("k" * 4000) and key.endswith("…[truncated 1000 chars]")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_cap_maps_non_finite_numbers_to_none(bad):
    capped = telemetry_log.cap({"x": bad, "l": [bad, 1.5]})
    assert capped == {"x": None, "l": [None, 1.5]}
    json.dumps(capped, allow_nan=False)


def test_telemetry_meta_drops_tool_calls_from_saved_turns():
    turns = [
        {
            "turn": 1,
            "metadata": {"agent": "a", "tool_calls": [{"name": "t"}], "tool_calls_raw": [1]},
        },
        {"turn": 2, "metadata": {"latency_ms": 4}},
        {"turn": 3, "metadata": "not a dict"},
        "not a dict",
    ]
    meta = telemetry_log.telemetry_meta("t1", {"tool_executions": [], "turns": turns})
    assert meta["telemetry"]["turns"] == [
        {"turn": 1, "metadata": {"agent": "a"}},
        {"turn": 2, "metadata": {"latency_ms": 4}},
        {"turn": 3, "metadata": "not a dict"},
    ]
    assert turns[0]["metadata"]["tool_calls"]  # the engine's copy is untouched


def test_telemetry_meta_caps_many_turns_and_executions():
    executions = [{"turn": 1, "tool_name": "t", "parameters": {}, "result": ""}] * 300
    meta = telemetry_log.telemetry_meta(
        "t1",
        {
            "tool_executions": executions,
            "turns": [{"turn": i, "metadata": {"i": i}} for i in range(300)],
        },
    )
    assert len(meta["telemetry"]["turns"]) == telemetry_log.MAX_ITEMS + 1
    assert len(meta["telemetry"]["tool_executions"]) == telemetry_log.MAX_ITEMS + 1
    assert meta["telemetry"]["tool_executions"][-1] == "…[100 more items]"
