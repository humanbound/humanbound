# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import pytest
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import a2a
from humanbound_cli.arena.adapters.http import AgentError
from humanbound_cli.arena.contexts import ContextStore
from humanbound_cli.arena.manifest import load_manifest

ECHO = load_manifest(ARENA_FIXTURES / "catalog" / "agents" / "echo" / "arena.yaml")


def test_context_store_creates_reuses_and_drops():
    store = ContextStore()
    cid, ctx = store.get_or_create("echo", None)
    assert len(cid) == 32
    same_id, same = store.get_or_create("echo", cid)
    assert same_id == cid and same is ctx
    client_id, other = store.get_or_create("echo", "client-chosen")
    assert client_id == "client-chosen" and other is not ctx
    store.drop_agent("echo")
    assert len(store) == 0


def test_context_store_evicts_oldest_beyond_capacity():
    store = ContextStore(max_items=2)
    first, _ = store.get_or_create("echo", None)
    store.get_or_create("echo", None)
    store.get_or_create("echo", None)
    assert len(store) == 2
    _, fresh = store.get_or_create("echo", first)
    assert fresh.started is False  # evicted, so a new empty context


def test_agent_card_fields():
    card = a2a.agent_card(ECHO, "http://127.0.0.1:11500/a2a/echo")
    assert card["name"] == "Echo"
    assert card["version"] == "0.1.0"
    assert card["supportedInterfaces"] == [
        {
            "url": "http://127.0.0.1:11500/a2a/echo",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card["capabilities"]["streaming"] is False
    assert card["defaultInputModes"] == ["text/plain"]
    assert card["skills"][0]["id"] == "echo"
    assert "Intentionally vulnerable" in card["description"]


def test_parse_envelope_and_message():
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "messageId": "m-1",
                "contextId": "c-1",
                "parts": [{"text": "hello"}, {"text": "world"}],
            }
        },
    }
    rpc_id, method, params = a2a.parse_envelope(body)
    assert (rpc_id, method) == (7, "SendMessage")
    msg = a2a.parse_message(params)
    assert (msg.text, msg.context_id, msg.message_id) == ("hello\nworld", "c-1", "m-1")


@pytest.mark.parametrize(
    "body, code",
    [
        ([], a2a.INVALID_REQUEST),
        ({"jsonrpc": "1.0", "method": "SendMessage"}, a2a.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": 1}, a2a.INVALID_REQUEST),
    ],
)
def test_bad_envelopes(body, code):
    with pytest.raises(a2a.RpcError) as exc:
        a2a.parse_envelope(body)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "params, code",
    [
        ({}, a2a.INVALID_PARAMS),
        ({"message": {"role": "ROLE_AGENT", "parts": [{"text": "x"}]}}, a2a.INVALID_PARAMS),
        ({"message": {"role": "ROLE_USER", "parts": []}}, a2a.INVALID_PARAMS),
        (
            {"message": {"role": "ROLE_USER", "parts": [{"url": "http://x"}]}},
            a2a.CONTENT_TYPE_NOT_SUPPORTED,
        ),
    ],
)
def test_bad_messages(params, code):
    with pytest.raises(a2a.RpcError) as exc:
        a2a.parse_message(params)
    assert exc.value.code == code


def test_check_version_accepts_missing_and_1_0_rejects_others():
    a2a.check_version(None)
    a2a.check_version("1.0")
    a2a.check_version("1.0.2")
    with pytest.raises(a2a.RpcError) as exc:
        a2a.check_version("0.3")
    assert exc.value.code == a2a.VERSION_NOT_SUPPORTED


def test_message_result_puts_parts_before_metadata():
    body = a2a.message_result(7, "hi", "c-1", {"latency_ms": 5})
    message = body["result"]["message"]
    assert list(message)[:5] == ["role", "messageId", "contextId", "parts", "metadata"]
    assert message["role"] == "ROLE_AGENT"
    assert message["parts"] == [{"text": "hi"}]
    assert message["metadata"] == {"humanbound": {"latency_ms": 5}}


def test_agent_errors_map_to_json_rpc_and_http_status():
    err = a2a.from_agent_error(AgentError("agent_timeout", "slow"))
    assert (err.code, err.http_status, err.reason) == (a2a.INTERNAL_ERROR, 504, "AGENT_TIMEOUT")
    body = a2a.error_body(3, err)
    assert body["error"]["code"] == a2a.INTERNAL_ERROR
    assert body["error"]["data"][0]["reason"] == "AGENT_TIMEOUT"
    assert body["error"]["data"][0]["@type"] == "type.googleapis.com/google.rpc.ErrorInfo"
    bad = a2a.from_agent_error(AgentError("unextractable_response", "?"))
    assert (bad.code, bad.http_status) == (a2a.INVALID_AGENT_RESPONSE, 502)
    gone = a2a.from_agent_error(AgentError("agent_not_running", "?"))
    assert gone.http_status == 404


def test_reply_text_from_message_or_task():
    assert a2a.reply_text({"message": {"parts": [{"text": "a"}, {"text": "b"}]}}) == "a\nb"
    task = {"task": {"artifacts": [{"parts": [{"text": "from artifact"}]}]}}
    assert a2a.reply_text(task) == "from artifact"
    status_only = {"task": {"status": {"message": {"parts": [{"text": "from status"}]}}}}
    assert a2a.reply_text(status_only) == "from status"
    assert a2a.reply_text(None) == ""


def test_send_message_body_shape():
    body = a2a.send_message_body("hi")
    msg = body["params"]["message"]
    assert body["method"] == "SendMessage" and msg["role"] == "ROLE_USER"
    assert msg["parts"] == [{"text": "hi"}] and len(msg["messageId"]) == 32
