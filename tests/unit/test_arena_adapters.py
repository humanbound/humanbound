# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import asyncio

import httpx
import pytest

from humanbound_cli.arena.adapters.a2a_passthrough import A2APassthrough
from humanbound_cli.arena.adapters.http import (
    AgentError,
    HttpAdapter,
    extract_path,
    fill_endpoint,
    substitute,
)
from humanbound_cli.arena.manifest import Integration


def run(coro):
    return asyncio.run(coro)


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_substitute_placeholders():
    template = {
        "p": "$PROMPT",
        "h": "$CONVERSATION",
        "t": "$thread_id",
        "missing": "$nope",
        "lit": "\\$PROMPT",
        "n": [1, "$PROMPT"],
    }
    history = [{"role": "user", "content": "hi"}]
    out = substitute(template, {"thread_id": "t-1"}, "go", history)
    assert out == {
        "p": "go",
        "h": history,
        "t": "t-1",
        "missing": None,
        "lit": "$PROMPT",
        "n": [1, "go"],
    }


def test_fill_endpoint_and_extract_path():
    assert fill_endpoint("/threads/$thread_id/chat", {"thread_id": "t-1"}) == "/threads/t-1/chat"
    data = {"choices": [{"message": {"content": "x"}}]}
    assert extract_path(data, "choices.0.message.content") == "x"
    with pytest.raises(KeyError):
        extract_path(data, "choices.5.message")


def _integration(**kw):
    base = {
        "type": "http",
        "chat_completion": {
            "endpoint": "/chat",
            "payload": {"prompt": "$PROMPT", "history": "$CONVERSATION"},
        },
        "response": {"text": "reply", "tool_calls": "trace.tools"},
    }
    base.update(kw)
    return Integration.model_validate(base)


def test_send_extracts_reply_tool_calls_and_passes_history_for_gateway_mode():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={"reply": "hello", "trace": {"tools": [{"name": "t"}]}})

    async def go():
        async with client_for(handler) as c:
            adapter = HttpAdapter(_integration(history="gateway"), "http://agent", 5, c)
            return await adapter.send({}, "hi", [{"role": "user", "content": "before"}])

    reply = run(go())
    assert reply.text == "hello"
    assert reply.tool_calls == [{"name": "t"}]
    assert seen["url"] == "http://agent/chat"
    assert b'"before"' in seen["body"]


def test_history_is_not_sent_unless_gateway_mode():
    bodies = []

    def handler(request):
        bodies.append(request.read())
        return httpx.Response(200, json={"reply": "ok"})

    async def go():
        async with client_for(handler) as c:
            adapter = HttpAdapter(_integration(history="none"), "http://agent", 5, c)
            await adapter.send({}, "hi", [{"role": "user", "content": "before"}])

    run(go())
    assert b'"before"' not in bodies[0]


def test_thread_init_state_feeds_later_calls():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(200, json={"thread_id": "t-7"})
        assert request.url.path == "/threads/t-7/chat"
        return httpx.Response(200, json={"reply": "in thread"})

    integ = _integration(
        history="agent",
        thread_init={"endpoint": "/start", "payload": {}},
        chat_completion={"endpoint": "/threads/$thread_id/chat", "payload": {"q": "$PROMPT"}},
    )

    async def go():
        async with client_for(handler) as c:
            adapter = HttpAdapter(integ, "http://agent", 5, c)
            state = await adapter.start_conversation()
            return await adapter.send(state, "hi", [])

    assert run(go()).text == "in thread"


@pytest.mark.parametrize(
    "handler, code",
    [
        (lambda r: httpx.Response(500, text="kaboom"), "agent_error"),
        (lambda r: httpx.Response(200, text="not json"), "unextractable_response"),
        (lambda r: httpx.Response(200, json={"other": 1}), "unextractable_response"),
    ],
)
def test_agent_failures_map_to_codes(handler, code):
    async def go():
        async with client_for(handler) as c:
            await HttpAdapter(_integration(), "http://agent", 5, c).send({}, "hi", [])

    with pytest.raises(AgentError) as exc:
        run(go())
    assert exc.value.code == code


def test_timeout_and_unreachable_map_to_codes():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def refused(request):
        raise httpx.ConnectError("refused")

    for handler, code in [(timeout, "agent_timeout"), (refused, "agent_not_running")]:

        async def go(h=handler):
            async with client_for(h) as c:
                await HttpAdapter(_integration(), "http://agent", 5, c).send({}, "hi", [])

        with pytest.raises(AgentError) as exc:
            run(go())
        assert exc.value.code == code


def test_a2a_passthrough_forwards_body_and_version_header():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["version"] = request.headers.get("A2A-Version")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    async def go():
        async with client_for(handler) as c:
            return await A2APassthrough("http://agent", "/a2a", 5, c).forward(
                {"jsonrpc": "2.0", "id": 1, "method": "SendMessage"}, "1.0"
            )

    status, data = run(go())
    assert status == 200 and data["id"] == 1
    assert seen == {"path": "/a2a", "version": "1.0"}
