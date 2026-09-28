# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the A2A v1.0 JSON-RPC helpers and the conversation context store."""

from __future__ import annotations

import pytest
import yaml

from humanbound_cli.arena.a2a import (
    CONTENT_TYPE_NOT_SUPPORTED,
    ERROR_DOMAIN,
    INVALID_PARAMS,
    INVALID_REQUEST,
    VERSION_NOT_SUPPORTED,
    RpcError,
    agent_card,
    check_version,
    error_body,
    from_agent_error,
    message_result,
    parse_envelope,
    parse_message,
    reply_text,
    send_message_body,
)
from humanbound_cli.arena.adapters.http import AgentError
from humanbound_cli.arena.contexts import Context, ContextStore
from humanbound_cli.arena.manifest import parse_manifest

from .arena_testing import ECHO_YAML

ECHO_MANIFEST = parse_manifest(yaml.safe_load(ECHO_YAML.read_text()))


# ── contexts.py ──


def test_context_store_create_generates_uuid():
    store = ContextStore()
    cid, ctx = store.get_or_create("echo", None)
    assert isinstance(cid, str) and len(cid) == 32
    assert isinstance(ctx, Context)
    assert ctx.agent_id == "echo"
    assert ctx.state == {}
    assert ctx.history == []
    assert ctx.started is False


def test_context_store_reuse():
    store = ContextStore()
    cid, ctx = store.get_or_create("echo", None)
    ctx.state["x"] = 1
    cid2, ctx2 = store.get_or_create("echo", cid)
    assert cid2 == cid
    assert ctx2 is ctx
    assert ctx2.state == {"x": 1}


def test_context_store_lru_eviction():
    store = ContextStore(max_items=2)
    cid1, _ = store.get_or_create("echo", "a")
    cid2, _ = store.get_or_create("echo", "b")
    # touch "a" so it's most-recently-used
    store.get_or_create("echo", "a")
    store.get_or_create("echo", "c")  # evicts "b", the least recently used
    assert len(store) == 2
    # "a" survives
    _, ctx_a = store.get_or_create("echo", "a")
    assert ctx_a.agent_id == "echo"
    # "b" was evicted -> a new context is created for the same id
    cid_b_again, ctx_b_again = store.get_or_create("echo", "b")
    assert cid_b_again == "b"


def test_context_store_scoped_per_agent():
    store = ContextStore()
    cid1, ctx1 = store.get_or_create("echo", "shared")
    cid2, ctx2 = store.get_or_create("other", "shared")
    assert cid1 == cid2 == "shared"
    assert ctx1 is not ctx2
    assert ctx1.agent_id == "echo" and ctx2.agent_id == "other"
    assert len(store) == 2
    store.drop_agent("echo")
    assert len(store) == 1
    _, again = store.get_or_create("other", "shared")
    assert again is ctx2


# ── agent_card ──


def test_agent_card_fields():
    card = agent_card(ECHO_MANIFEST, "http://127.0.0.1:11500/a2a/echo")
    assert card["name"] == "Echo"
    assert "Intentionally vulnerable test agent" in card["description"]
    assert card["description"].startswith(ECHO_MANIFEST.description)
    assert card["supportedInterfaces"] == [
        {
            "url": "http://127.0.0.1:11500/a2a/echo",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card["provider"] == {"organization": "Humanbound Arena", "url": "https://humanbound.ai"}
    assert card["version"] == "0.1.0"
    assert card["capabilities"] == {"streaming": False, "pushNotifications": False}
    assert card["defaultInputModes"] == ["text/plain"]
    assert card["defaultOutputModes"] == ["text/plain"]
    assert card["skills"] == [
        {
            "id": "echo",
            "name": "Echo",
            "description": ECHO_MANIFEST.agent.scope.business.strip(),
            "tags": ["fixture"],
        }
    ]


def test_agent_card_tags_fallback():
    m = ECHO_MANIFEST.model_copy(update={"tags": []})
    card = agent_card(m, "http://x")
    assert card["skills"][0]["tags"] == ["echo"]


# ── check_version ──


@pytest.mark.parametrize("header", [None, "1.0", "1.0.x", "1.0.3"])
def test_check_version_accepted(header):
    check_version(header)  # should not raise


@pytest.mark.parametrize("header", ["2.0", "0.9", "abc"])
def test_check_version_rejected(header):
    with pytest.raises(RpcError) as exc_info:
        check_version(header)
    assert exc_info.value.code == VERSION_NOT_SUPPORTED


# ── parse_envelope ──


def test_parse_envelope_ok():
    rpc_id, method, params = parse_envelope(
        {"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {"a": 1}}
    )
    assert rpc_id == "1"
    assert method == "SendMessage"
    assert params == {"a": 1}


@pytest.mark.parametrize(
    "body",
    [
        "not a dict",
        {"jsonrpc": "1.0", "id": "1", "method": "SendMessage"},
        {"jsonrpc": "2.0", "id": "1"},
        {"jsonrpc": "2.0", "id": "1", "method": 123},
        {"jsonrpc": "2.0", "method": "SendMessage"},
        {"jsonrpc": "2.0", "id": True, "method": "SendMessage"},
        {"jsonrpc": "2.0", "id": [], "method": "SendMessage"},
    ],
)
def test_parse_envelope_rejected(body):
    with pytest.raises(RpcError) as exc_info:
        parse_envelope(body)
    assert exc_info.value.code == INVALID_REQUEST


@pytest.mark.parametrize("rpc_id", ["1", 1, 1.5])
def test_parse_envelope_id_types_accepted(rpc_id):
    result_id, _, _ = parse_envelope({"jsonrpc": "2.0", "id": rpc_id, "method": "SendMessage"})
    assert result_id == rpc_id


# ── parse_message ──


def _params(**over):
    base = {
        "message": {
            "role": "ROLE_USER",
            "messageId": "m1",
            "contextId": "c1",
            "parts": [{"text": "hi"}],
        }
    }
    base.update(over)
    return base


def test_parse_message_ok():
    msg = parse_message(_params())
    assert msg.text == "hi"
    assert msg.context_id == "c1"
    assert msg.message_id == "m1"


@pytest.mark.parametrize("text", [123, None, 1.5, ["a"], {"t": 1}, False])
def test_parse_message_non_string_text_is_invalid_params(text):
    params = _params()
    params["message"]["parts"] = [{"text": "ok"}, {"text": text}]
    with pytest.raises(RpcError) as e:
        parse_message(params)
    assert e.value.code == INVALID_PARAMS


def test_parse_message_joins_multiple_parts():
    params = _params(message={"role": "ROLE_USER", "parts": [{"text": "a"}, {"text": "b"}]})
    msg = parse_message(params)
    assert msg.text == "a\nb"


def test_parse_message_generates_missing_message_id():
    params = _params(message={"role": "ROLE_USER", "parts": [{"text": "hi"}]})
    msg = parse_message(params)
    assert msg.message_id


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"message": "not a dict"},
        {"message": {"role": "ROLE_AGENT", "parts": [{"text": "hi"}]}},
        {"message": {"role": "ROLE_USER", "parts": []}},
        {"message": {"role": "ROLE_USER"}},
    ],
)
def test_parse_message_invalid_params(params):
    with pytest.raises(RpcError) as exc_info:
        parse_message(params)
    assert exc_info.value.code == INVALID_PARAMS


def test_parse_message_non_text_part_rejected():
    params = _params(message={"role": "ROLE_USER", "parts": [{"file": "x"}]})
    with pytest.raises(RpcError) as exc_info:
        parse_message(params)
    assert exc_info.value.code == CONTENT_TYPE_NOT_SUPPORTED


@pytest.mark.parametrize("field", ["contextId", "messageId"])
@pytest.mark.parametrize("bad", [123, [], {}])
def test_parse_message_ids_must_be_strings(field, bad):
    params = _params(message={"role": "ROLE_USER", "parts": [{"text": "hi"}], field: bad})
    with pytest.raises(RpcError) as exc_info:
        parse_message(params)
    assert exc_info.value.code == INVALID_PARAMS


# ── message_result ──


def test_message_result_shape_and_key_order():
    result = message_result("1", "hello", "ctx1", {"latency_ms": 5})
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "1"
    message = result["result"]["message"]
    assert message["role"] == "ROLE_AGENT"
    assert message["contextId"] == "ctx1"
    assert message["parts"] == [{"text": "hello"}]
    assert message["metadata"] == {"humanbound": {"latency_ms": 5}}
    assert "messageId" in message
    keys = list(message.keys())
    assert keys.index("parts") < keys.index("metadata")


# ── error_body ──


def test_error_body_without_reason():
    err = RpcError(-32603, "boom")
    body = error_body("1", err)
    assert body == {"code": -32603, "message": "boom"}


def test_error_body_with_reason():
    err = RpcError(-32603, "boom", http_status=502, reason="AGENT_ERROR")
    body = error_body("1", err)
    assert body["code"] == -32603
    assert body["message"] == "boom"
    assert body["data"] == [
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "AGENT_ERROR",
            "domain": ERROR_DOMAIN,
        }
    ]


# ── from_agent_error ──


@pytest.mark.parametrize(
    "code,rpc_code,http_status,reason",
    [
        ("agent_not_running", -32603, 404, "AGENT_NOT_RUNNING"),
        ("agent_error", -32603, 502, "AGENT_ERROR"),
        ("agent_timeout", -32603, 504, "AGENT_TIMEOUT"),
        ("unextractable_response", -32006, 502, "UNEXTRACTABLE_RESPONSE"),
        ("docker_unavailable", -32603, 503, "DOCKER_UNAVAILABLE"),
    ],
)
def test_from_agent_error_mapping(code, rpc_code, http_status, reason):
    err = from_agent_error(AgentError(code, "oops"))
    assert err.code == rpc_code
    assert err.http_status == http_status
    assert err.reason == reason
    assert err.message == "oops"


def test_from_agent_error_fallback():
    class Weird(Exception):
        pass

    err = from_agent_error(Weird("bad"))
    assert err.code == -32603
    assert err.http_status == 502
    assert err.reason == "AGENT_ERROR"


# ── reply_text ──


def test_reply_text_from_message():
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"message": {"parts": [{"text": "a"}, {"text": "b"}]}},
    }
    assert reply_text(body) == "a\nb"


def test_reply_text_from_task_artifacts():
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"task": {"artifacts": [{"parts": [{"text": "x"}]}, {"parts": [{"text": "y"}]}]}},
    }
    assert reply_text(body) == "x\ny"


def test_reply_text_from_task_status():
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"task": {"status": {"message": {"parts": [{"text": "z"}]}}}},
    }
    assert reply_text(body) == "z"


def test_reply_text_error_body():
    body = {"jsonrpc": "2.0", "id": "1", "error": {"code": -32001, "message": "no task"}}
    with pytest.raises(AgentError) as exc_info:
        reply_text(body)
    assert exc_info.value.code == "agent_error"
    assert "-32001" in exc_info.value.message


@pytest.mark.parametrize(
    "body",
    [
        {"jsonrpc": "2.0", "id": "1"},
        {"jsonrpc": "2.0", "id": "1", "result": "not a dict"},
        {"jsonrpc": "2.0", "id": "1", "result": {}},
        {"jsonrpc": "2.0", "id": "1", "result": {"message": "not a dict"}},
        {"jsonrpc": "2.0", "id": "1", "result": {"message": {"parts": "not a list"}}},
        {"jsonrpc": "2.0", "id": "1", "result": {"task": {"artifacts": "not a list"}}},
    ],
)
def test_reply_text_malformed(body):
    with pytest.raises(AgentError) as exc_info:
        reply_text(body)
    assert exc_info.value.code == "unextractable_response"


# ── send_message_body ──


def test_send_message_body_well_formed():
    body = send_message_body("hello")
    assert body["jsonrpc"] == "2.0"
    assert isinstance(body["id"], str) and body["id"]
    params_message = body["params"]["message"]
    assert params_message["role"] == "ROLE_USER"
    assert isinstance(params_message["messageId"], str) and params_message["messageId"]
    assert params_message["parts"] == [{"text": "hello"}]
    assert "contextId" not in params_message


def test_send_message_body_with_context_id():
    body = send_message_body("hello", context_id="c1")
    assert body["params"]["message"]["contextId"] == "c1"
