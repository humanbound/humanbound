# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for tool-call normalization (agent-specific shapes → {name, parameters, result})."""

from __future__ import annotations

import pytest

from humanbound_cli.arena.target import bot_config
from humanbound_cli.arena.tools import normalize_tool_calls
from humanbound_cli.engine.bot import Telemetry

# separate call and result steps ({type, name, args} then {type, name, content})
SPLIT_CALL_AND_RESULT = [
    {"type": "tool_call", "name": "lookup_price", "args": {"sku": "A1"}},
    {"type": "tool_result", "name": "lookup_price", "content": "A1 costs 9.99"},
    {"type": "tool_call", "name": "send_email", "args": {"to": "x@example.com"}},
    {"type": "tool_result", "name": "send_email", "content": "sent"},
]

# one entry per call ({name, args, result})
ONE_ENTRY_PER_CALL = [
    {"name": "order_lookup", "args": {"order": "O-1"}, "result": "shipped"},
    {"name": "account_check", "args": "user 42", "result": "active"},
]


def test_preferred_shape_unchanged():
    items = [{"name": "t", "parameters": {"a": 1}, "result": "ok"}]
    assert normalize_tool_calls(items) == items


def test_split_call_and_result_are_merged():
    assert normalize_tool_calls(SPLIT_CALL_AND_RESULT) == [
        {"name": "lookup_price", "parameters": {"sku": "A1"}, "result": "A1 costs 9.99"},
        {"name": "send_email", "parameters": {"to": "x@example.com"}, "result": "sent"},
    ]


def test_one_entry_per_call_shape():
    assert normalize_tool_calls(ONE_ENTRY_PER_CALL) == [
        {"name": "order_lookup", "parameters": {"order": "O-1"}, "result": "shipped"},
        {"name": "account_check", "parameters": "user 42", "result": "active"},
    ]


@pytest.mark.parametrize("key", ["name", "tool", "tool_name"])
def test_name_aliases(key):
    assert normalize_tool_calls([{key: "t"}])[0]["name"] == "t"


@pytest.mark.parametrize("key", ["parameters", "args", "arguments", "input"])
def test_parameter_aliases(key):
    assert normalize_tool_calls([{"name": "t", key: {"a": 1}}])[0]["parameters"] == {"a": 1}


@pytest.mark.parametrize("key", ["result", "output", "content"])
def test_result_aliases(key):
    assert normalize_tool_calls([{"name": "t", key: "r"}])[0]["result"] == "r"


def test_json_string_parameters_are_parsed():
    out = normalize_tool_calls([{"name": "t", "arguments": '{"q": "x"}'}])
    assert out[0]["parameters"] == {"q": "x"}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", "{broken"])
def test_non_object_string_parameters_kept_as_is(raw):
    assert normalize_tool_calls([{"name": "t", "args": raw}])[0]["parameters"] == raw


def test_missing_fields_default():
    assert normalize_tool_calls([{"name": "t"}]) == [{"name": "t", "parameters": {}, "result": ""}]


def test_non_dict_items_dropped():
    assert normalize_tool_calls(["x", 3, None, {"name": "t"}]) == [
        {"name": "t", "parameters": {}, "result": ""}
    ]


@pytest.mark.parametrize("value", [None, "text", 42])
def test_non_list_input_is_empty(value):
    assert normalize_tool_calls(value) == []


def test_single_dict_is_one_item():
    assert normalize_tool_calls({"name": "t", "args": {}}) == [
        {"name": "t", "parameters": {}, "result": ""}
    ]


def test_result_with_other_name_is_not_merged():
    out = normalize_tool_calls(
        [
            {"type": "tool_call", "name": "a", "args": {"x": 1}},
            {"type": "tool_result", "name": "b", "content": "rb"},
        ]
    )
    assert out == [
        {"name": "a", "parameters": {"x": 1}, "result": ""},
        {"name": "b", "parameters": {}, "result": "rb"},
    ]


def test_result_without_name_merges_into_previous_call():
    out = normalize_tool_calls(
        [
            {"type": "call", "name": "a", "args": {"x": 1}},
            {"type": "result", "name": "", "content": "ra"},
        ]
    )
    assert out == [{"name": "a", "parameters": {"x": 1}, "result": "ra"}]


def test_result_does_not_merge_into_a_complete_item():
    out = normalize_tool_calls(
        [
            {"name": "a", "args": {}, "result": "first"},
            {"type": "tool_result", "name": "a", "content": "second"},
        ]
    )
    assert [o["result"] for o in out] == ["first", "second"]


def test_does_not_mutate_input():
    items = [dict(i) for i in SPLIT_CALL_AND_RESULT]
    normalize_tool_calls(items)
    assert items == SPLIT_CALL_AND_RESULT


@pytest.mark.parametrize("raw", [SPLIT_CALL_AND_RESULT, ONE_ENTRY_PER_CALL])
def test_normalized_output_standardizes_to_tool_executions(raw):
    metadata = {"agent": "x", "tool_calls": normalize_tool_calls(raw)}
    extraction_map = bot_config("x", "http://127.0.0.1:11500", token="t")["telemetry"][
        "extraction_map"
    ]
    out = Telemetry.standardize_accumulated_metadata(
        [{"turn": 1, "metadata": metadata}], extraction_map
    )
    executions = out["tool_executions"]
    assert len(executions) == 2
    for execution in executions:
        assert execution["tool_name"]
        assert execution["parameters"]
        assert execution["result"]
    assert executions[0]["tool_name"] in ("lookup_price", "order_lookup")
