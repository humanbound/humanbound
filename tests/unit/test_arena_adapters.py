# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the HTTP adapter (bot-config placeholders, reply paths) and A2A passthrough."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from humanbound_cli.arena.adapters.a2a_passthrough import A2APassthrough
from humanbound_cli.arena.adapters.http import (
    AgentError,
    AgentReply,
    HttpAdapter,
    extract_path,
    fill_endpoint,
    map_httpx_error,
    substitute,
)
from humanbound_cli.arena.manifest import HttpCall, Integration, ResponseMap


def arun(coro):
    return asyncio.run(coro)


# ── substitute ──


def test_substitute_conversation_case_insensitive():
    history = [{"role": "user", "content": "hi"}]
    for token in ("$CONVERSATION", "$conversation", "$Conversation"):
        out = substitute(token, {"conversation": "state"}, "p", history)
        assert out == history
        assert out is not history


def test_substitute_prompt_case_insensitive():
    assert substitute("$PROMPT", {}, "hello", []) == "hello"
    assert substitute("$prompt", {}, "hello", []) == "hello"


def test_substitute_value_key():
    assert substitute("$thread", {"thread": "abc"}, "p", []) == "abc"
    assert substitute("$missing", {}, "p", []) is None


def test_substitute_escape_is_literal():
    assert substitute("\\$PROMPT", {}, "hello", []) == "$PROMPT"
    assert substitute("\\literal", {}, "hello", []) == "literal"


def test_substitute_unchanged():
    assert substitute("plain", {}, "p", []) == "plain"
    assert substitute(42, {}, "p", []) == 42
    assert substitute(None, {}, "p", []) is None


def test_substitute_recursive():
    payload = {"prompt": "$PROMPT", "nested": {"history": "$CONVERSATION", "x": ["$key", 1]}}
    result = substitute(payload, {"key": "v"}, "hi", [{"role": "user", "content": "hi"}])
    assert result == {
        "prompt": "hi",
        "nested": {"history": [{"role": "user", "content": "hi"}], "x": ["v", 1]},
    }


# ── fill_endpoint ──


def test_fill_endpoint_collision_prefers_longest_match():
    endpoint = "/t/$thread_id/chat/$thread"
    result = fill_endpoint(endpoint, {"thread": "X", "thread_id": "Y"})
    assert result == "/t/Y/chat/X"


def test_fill_endpoint_encoding():
    result = fill_endpoint("/x/$v", {"v": "a/b?c"})
    assert result == "/x/a%2Fb%3Fc"


def test_fill_endpoint_no_encode_for_headers():
    result = fill_endpoint("$v", {"v": "a/b?c"}, encode=False)
    assert result == "a/b?c"


def test_fill_endpoint_bools_not_substituted():
    result = fill_endpoint("/x/$v", {"v": True})
    assert result == "/x/$v"


def test_fill_endpoint_unknown_key_left_alone():
    result = fill_endpoint("/x/$unknown", {})
    assert result == "/x/$unknown"


def test_fill_endpoint_int_and_float():
    assert fill_endpoint("/x/$n", {"n": 3}) == "/x/3"
    assert fill_endpoint("/x/$n", {"n": 3.5}) == "/x/3.5"


def test_fill_endpoint_whole_identifiers_only():
    # $thread should not match inside "$threading"
    result = fill_endpoint("/x/$threading", {"thread": "X"})
    assert result == "/x/$threading"


# ── extract_path ──


def test_extract_path_dict():
    assert extract_path({"a": {"b": "c"}}, "a.b") == "c"


def test_extract_path_list_index():
    assert extract_path({"choices": [{"text": "hi"}]}, "choices.0.text") == "hi"


def test_extract_path_missing_raises():
    with pytest.raises(KeyError):
        extract_path({"a": 1}, "a.b")
    with pytest.raises(KeyError):
        extract_path({"a": [1, 2]}, "a.5")
    with pytest.raises(KeyError):
        extract_path({"a": [1, 2]}, "a.not_a_digit")


# ── map_httpx_error ──


def test_map_httpx_error_timeout():
    err = map_httpx_error(httpx.ReadTimeout("boom"), 5)
    assert err.code == "agent_timeout"
    assert "5" in err.message


@pytest.mark.parametrize(
    "exc, code",
    [
        (httpx.ConnectError("boom"), "agent_not_running"),
        (httpx.RemoteProtocolError("boom"), "agent_error"),
        (httpx.InvalidURL("boom"), "agent_error"),
    ],
)
def test_map_httpx_error_codes(exc, code):
    assert map_httpx_error(exc, 5).code == code


# ── HttpAdapter ──


def _integration(**overrides):
    defaults = dict(
        type="http",
        chat_completion=HttpCall(endpoint="/chat", payload={"prompt": "$PROMPT"}),
        response=ResponseMap(text="reply", tool_calls="trace.tools"),
        history="none",
    )
    defaults.update(overrides)
    return Integration(**defaults)


def _adapter(handler, integration=None, timeout_s=5):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return HttpAdapter(
        integration or _integration(), base_url="http://agent", timeout_s=timeout_s, client=client
    )


def test_send_extracts_text_and_tool_calls():
    def handler(request):
        return httpx.Response(200, json={"reply": "hi there", "trace": {"tools": ["a"]}})

    adapter = _adapter(handler)
    reply = arun(adapter.send({}, "hello", []))
    assert isinstance(reply, AgentReply)
    assert reply.text == "hi there"
    assert reply.tool_calls == ["a"]
    assert reply.latency_ms >= 0


def test_send_tool_calls_missing_is_none():
    def handler(request):
        return httpx.Response(200, json={"reply": "hi"})

    adapter = _adapter(handler)
    reply = arun(adapter.send({}, "hello", []))
    assert reply.tool_calls is None


def test_send_history_gateway_included():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"reply": "ok"})

    integration = _integration(
        chat_completion=HttpCall(
            endpoint="/chat", payload={"prompt": "$PROMPT", "history": "$CONVERSATION"}
        ),
        history="gateway",
    )
    adapter = _adapter(handler, integration)
    history = [{"role": "user", "content": "hi"}]
    arun(adapter.send({}, "hello", history))
    assert captured["body"]["history"] == history


def test_send_history_none_not_included():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"reply": "ok"})

    integration = _integration(
        chat_completion=HttpCall(
            endpoint="/chat", payload={"prompt": "$PROMPT", "history": "$CONVERSATION"}
        ),
        history="none",
    )
    adapter = _adapter(handler, integration)
    history = [{"role": "user", "content": "hi"}]
    arun(adapter.send({}, "hello", history))
    assert captured["body"]["history"] == []


def test_start_conversation_runs_thread_init():
    def handler(request):
        return httpx.Response(200, json={"thread_id": "abc"})

    integration = _integration(thread_init=HttpCall(endpoint="/sessions", payload={}))
    adapter = _adapter(handler, integration)
    state = arun(adapter.start_conversation())
    assert state == {"thread_id": "abc"}


def test_start_conversation_no_thread_init():
    def handler(request):
        raise AssertionError("should not be called")

    adapter = _adapter(handler)
    state = arun(adapter.start_conversation())
    assert state == {}


def test_start_conversation_non_dict_response():
    def handler(request):
        return httpx.Response(200, json=["not", "a", "dict"])

    integration = _integration(thread_init=HttpCall(endpoint="/sessions", payload={}))
    adapter = _adapter(handler, integration)
    state = arun(adapter.start_conversation())
    assert state == {}


def test_thread_init_state_feeds_endpoint():
    captured = {}

    def handler(request):
        captured.setdefault("paths", []).append(request.url.path)
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"thread": "T1"})
        return httpx.Response(200, json={"reply": "ok"})

    integration = _integration(
        thread_init=HttpCall(endpoint="/sessions", payload={}),
        chat_completion=HttpCall(endpoint="/t/$thread/chat", payload={"prompt": "$PROMPT"}),
    )
    adapter = _adapter(handler, integration)

    async def _run():
        state = await adapter.start_conversation()
        await adapter.send(state, "hi", [])

    arun(_run())
    assert captured["paths"] == ["/sessions", "/t/T1/chat"]


def test_send_headers_not_encoded():
    captured = {}

    def handler(request):
        captured["header"] = request.headers.get("x-thread")
        return httpx.Response(200, json={"reply": "ok"})

    integration = _integration(
        chat_completion=HttpCall(
            endpoint="/chat", headers={"x-thread": "$v"}, payload={"prompt": "$PROMPT"}
        ),
    )
    adapter = _adapter(handler, integration)
    arun(adapter.send({"v": "a/b?c"}, "hi", []))
    assert captured["header"] == "a/b?c"


def test_error_non_json_response():
    def handler(request):
        return httpx.Response(200, text="not json{{{")

    adapter = _adapter(handler)
    with pytest.raises(AgentError) as exc_info:
        arun(adapter.send({}, "hi", []))
    assert exc_info.value.code == "unextractable_response"


def test_error_missing_text_path():
    def handler(request):
        return httpx.Response(200, json={"other": "value"})

    adapter = _adapter(handler)
    with pytest.raises(AgentError) as exc_info:
        arun(adapter.send({}, "hi", []))
    assert exc_info.value.code == "unextractable_response"


def test_error_none_text():
    def handler(request):
        return httpx.Response(200, json={"reply": None})

    adapter = _adapter(handler)
    with pytest.raises(AgentError) as exc_info:
        arun(adapter.send({}, "hi", []))
    assert exc_info.value.code == "unextractable_response"


def test_error_non_string_text_is_json_dumped():
    def handler(request):
        return httpx.Response(200, json={"reply": {"a": 1}})

    adapter = _adapter(handler)
    reply = arun(adapter.send({}, "hi", []))
    assert json.loads(reply.text) == {"a": 1}


# ── A2APassthrough ──


def _passthrough(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return A2APassthrough("http://agent", "/a2a", 5, client)


def test_passthrough_forwards_body_and_version():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["version"] = request.headers.get("a2a-version")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    status, data = arun(_passthrough(handler).forward({"jsonrpc": "2.0", "id": 1}, "1.0"))
    assert status == 200
    assert data == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert captured["body"] == {"jsonrpc": "2.0", "id": 1}
    assert captured["version"] == "1.0"


def test_passthrough_default_version_header():
    captured = {}

    def handler(request):
        captured["version"] = request.headers.get("a2a-version")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    arun(_passthrough(handler).forward({"jsonrpc": "2.0", "id": 1}, None))
    assert captured["version"] == "1.0"


def test_passthrough_non_json_2xx():
    def handler(request):
        return httpx.Response(200, text="not json")

    with pytest.raises(AgentError) as exc_info:
        arun(_passthrough(handler).forward({}, "1.0"))
    assert exc_info.value.code == "unextractable_response"


# ── one retry when the agent drops a reused connection ──


def _flaky(failures, exc_factory, ok_response):
    """A handler that raises `exc_factory()` `failures` times, then answers."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc_factory()
        return ok_response()

    return handler, calls


def _disconnected():
    return httpx.RemoteProtocolError("Server disconnected without sending a response.")


def test_send_retries_once_after_remote_protocol_error():
    handler, calls = _flaky(
        1, _disconnected, lambda: httpx.Response(200, json={"reply": "hi", "trace": {"tools": []}})
    )
    reply = arun(_adapter(handler).send({}, "hello", []))
    assert reply.text == "hi"
    assert calls["n"] == 2


def test_send_second_remote_protocol_error_is_agent_error():
    handler, calls = _flaky(5, _disconnected, lambda: httpx.Response(200, json={"reply": "hi"}))
    with pytest.raises(AgentError) as exc_info:
        arun(_adapter(handler).send({}, "hello", []))
    assert exc_info.value.code == "agent_error"
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "exc_factory, code",
    [
        (lambda: httpx.ReadTimeout("timed out"), "agent_timeout"),
        (lambda: httpx.ConnectError("refused"), "agent_not_running"),
        (lambda: httpx.ReadError("reset"), "agent_error"),
    ],
)
def test_send_other_transport_errors_not_retried(exc_factory, code):
    handler, calls = _flaky(1, exc_factory, lambda: httpx.Response(200, json={"reply": "hi"}))
    with pytest.raises(AgentError) as exc_info:
        arun(_adapter(handler).send({}, "hello", []))
    assert exc_info.value.code == code
    assert calls["n"] == 1


def test_send_http_error_status_not_retried():
    handler, calls = _flaky(0, _disconnected, lambda: httpx.Response(502, text="bad gateway"))
    with pytest.raises(AgentError) as exc_info:
        arun(_adapter(handler).send({}, "hello", []))
    assert exc_info.value.code == "agent_error"
    assert "502" in exc_info.value.message
    assert calls["n"] == 1


def test_thread_init_retries_once_after_remote_protocol_error():
    handler, calls = _flaky(1, _disconnected, lambda: httpx.Response(200, json={"thread": "t1"}))
    integration = _integration(thread_init=HttpCall(endpoint="/start", payload={}))
    assert arun(_adapter(handler, integration).start_conversation()) == {"thread": "t1"}
    assert calls["n"] == 2


def test_passthrough_retries_once_after_remote_protocol_error():
    handler, calls = _flaky(
        1, _disconnected, lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1})
    )
    status, data = arun(_passthrough(handler).forward({"jsonrpc": "2.0", "id": 1}, "1.0"))
    assert status == 200
    assert data == {"jsonrpc": "2.0", "id": 1}
    assert calls["n"] == 2


def test_passthrough_second_remote_protocol_error_is_agent_error():
    handler, calls = _flaky(5, _disconnected, lambda: httpx.Response(200, json={}))
    with pytest.raises(AgentError) as exc_info:
        arun(_passthrough(handler).forward({}, "1.0"))
    assert exc_info.value.code == "agent_error"
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "exc_factory, code",
    [
        (lambda: httpx.ReadTimeout("timed out"), "agent_timeout"),
        (lambda: httpx.ConnectError("refused"), "agent_not_running"),
    ],
)
def test_passthrough_other_transport_errors_not_retried(exc_factory, code):
    handler, calls = _flaky(1, exc_factory, lambda: httpx.Response(200, json={}))
    with pytest.raises(AgentError) as exc_info:
        arun(_passthrough(handler).forward({}, "1.0"))
    assert exc_info.value.code == code
    assert calls["n"] == 1


def test_passthrough_http_error_status_not_retried():
    handler, calls = _flaky(0, _disconnected, lambda: httpx.Response(503, text="busy"))
    with pytest.raises(AgentError) as exc_info:
        arun(_passthrough(handler).forward({}, "1.0"))
    assert exc_info.value.code == "agent_error"
    assert calls["n"] == 1
