# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the arena gateway. Agents are fake Starlette apps over httpx.ASGITransport."""

import asyncio
import copy
import os
import threading
from pathlib import Path

import httpx
import pytest
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from humanbound_cli import __version__
from humanbound_cli.arena import catalog, paths, runtime
from humanbound_cli.arena.gateway import (
    DEFAULT_ALLOWED_HOSTS,
    AgentRegistry,
    RegistryEntry,
    create_app,
)
from humanbound_cli.arena.manifest import parse_manifest
from humanbound_cli.arena.paths import LOOPBACK_HOSTS
from humanbound_cli.arena.runtime import DockerError, RunningAgent

from .arena_testing import ECHO_YAML, returns

ECHO_RAW = yaml.safe_load(ECHO_YAML.read_text(encoding="utf-8"))


# ── the fake agent ──


class FakeAgentState:
    def __init__(self):
        self.starts = 0
        self.a2a_requests = []


def fake_agent_app(state: FakeAgentState) -> Starlette:
    async def chat(request: Request):
        body = await request.json()
        history = body.get("history") or []
        return JSONResponse(
            {
                "reply": f"echo: {body['prompt']} ({len(history)} before)",
                "trace": {"tools": [{"name": "echo"}]},
            }
        )

    async def start(request: Request):
        state.starts += 1
        n = state.starts
        await asyncio.sleep(0.02)  # widen the race window for the concurrency test
        return JSONResponse({"tid": f"t{n}"})

    async def thread_chat(request: Request):
        body = await request.json()
        tid = request.path_params["tid"]
        return JSONResponse({"reply": f"[{tid}] {body['prompt']}"})

    async def broken(request: Request):
        return JSONResponse({"nothing": "here"})

    async def fail(request: Request):
        return JSONResponse({"detail": "kaput"}, status_code=500)

    async def native(request: Request):
        body = await request.json()
        state.a2a_requests.append((dict(request.headers), body))
        rid = body.get("id")
        if body.get("method") == "GetTask":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rid, "result": {"id": "task-1", "raw": True}}
            )
        message = body["params"]["message"]
        text = message["parts"][0]["text"]
        if text == "task":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "task": {
                            "id": "task-1",
                            "contextId": "up-ctx",
                            "history": [message],
                            "artifacts": [{"parts": [{"text": "artifact answer"}]}],
                            "status": {"state": "TASK_STATE_COMPLETED"},
                        }
                    },
                }
            )
        if text == "error":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "upstream"}}
            )
        if text == "list":
            return JSONResponse([1, 2, 3])
        result_message = {
            "role": "ROLE_AGENT",
            "messageId": "m-up",
            "parts": [{"text": f"native: {text}"}],
        }
        if text == "withctx":
            result_message["contextId"] = "up-msg-ctx"
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"message": result_message}})

    return Starlette(
        routes=[
            Route("/chat", chat, methods=["POST"]),
            Route("/start", start, methods=["POST"]),
            Route("/threads/{tid}/chat", thread_chat, methods=["POST"]),
            Route("/broken", broken, methods=["POST"]),
            Route("/fail", fail, methods=["POST"]),
            Route("/a2a", native, methods=["POST"]),
        ]
    )


# ── manifests and registry ──


def _variant(agent_id: str, integration: dict):
    raw = copy.deepcopy(ECHO_RAW)
    raw["id"] = agent_id
    raw["name"] = agent_id.title()
    raw["integration"] = integration
    return parse_manifest(raw)


ECHO = parse_manifest(copy.deepcopy(ECHO_RAW))
PLAIN = _variant(
    "plain",
    {
        "type": "http",
        "chat_completion": {
            "endpoint": "/chat",
            "payload": {"prompt": "$PROMPT", "history": "$CONVERSATION"},
        },
        "response": {"text": "reply"},
        "history": "none",
    },
)
THREADED = _variant(
    "threaded",
    {
        "type": "http",
        "thread_init": {"endpoint": "/start"},
        "chat_completion": {"endpoint": "/threads/$tid/chat", "payload": {"prompt": "$PROMPT"}},
        "response": {"text": "reply"},
        "history": "agent",
    },
)
BROKEN = _variant(
    "broken",
    {
        "type": "http",
        "chat_completion": {"endpoint": "/broken", "payload": {"prompt": "$PROMPT"}},
        "response": {"text": "reply"},
    },
)
FAILING = _variant(
    "failing",
    {
        "type": "http",
        "chat_completion": {"endpoint": "/fail", "payload": {"prompt": "$PROMPT"}},
        "response": {"text": "reply"},
    },
)
NATIVE = _variant("native", {"type": "a2a", "path": "/a2a"})

ALL_MANIFESTS = [ECHO, PLAIN, THREADED, BROKEN, FAILING, NATIVE]


def _entry(m, port=9000):
    agent = RunningAgent(id=m.id, version=m.version, kind="image", host_port=port)
    return RegistryEntry(agent=agent, manifest=m, agent_dir=Path("/nonexistent") / m.id)


class FakeRegistry:
    def __init__(self, manifests=ALL_MANIFESTS, error: Exception | None = None):
        self.entries = {m.id: _entry(m, 9000 + i) for i, m in enumerate(manifests)}
        self.error = error
        self.invalidations = 0

    def get(self, agent_id):
        if self.error:
            raise self.error
        return self.entries.get(agent_id)

    def all(self):
        if self.error:
            raise self.error
        return list(self.entries.values())

    def invalidate(self):
        self.invalidations += 1


TOKEN = "t0ken-" + "x" * 38
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _app(registry=None, *, agent_state=None, **kwargs):
    agent_state = agent_state or FakeAgentState()
    transport = httpx.ASGITransport(app=fake_agent_app(agent_state))
    kwargs.setdefault("allowed_hosts", ["testserver"])
    kwargs.setdefault("token", TOKEN)
    return create_app(registry or FakeRegistry(), transport=transport, **kwargs)


def _tc(app, **kwargs) -> TestClient:
    """A client that presents the gateway token, as hb and configured tools do."""
    return TestClient(app, headers=AUTH, **kwargs)


@pytest.fixture
def agent_state():
    return FakeAgentState()


@pytest.fixture
def registry():
    return FakeRegistry()


@pytest.fixture
def client(registry, agent_state):
    with _tc(_app(registry, agent_state=agent_state)) as c:
        yield c


def _send(text, context_id=None, rpc_id="1", method="SendMessage"):
    message = {"role": "ROLE_USER", "messageId": "m1", "parts": [{"text": text}]}
    if context_id is not None:
        message["contextId"] = context_id
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": {"message": message}}


def _reply(resp):
    return resp.json()["result"]["message"]["parts"][0]["text"]


# ── management routes ──


def test_default_allowed_hosts_are_loopback():
    assert DEFAULT_ALLOWED_HOSTS == list(LOOPBACK_HOSTS)


def test_health(client):
    resp = client.get("/arena/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "version": __version__,
        "pid": os.getpid(),
        "owner": paths.arena_owner(),
    }


def test_agent_list(client):
    resp = client.get("/arena/v1/agents")
    assert resp.status_code == 200
    by_id = {a["id"]: a for a in resp.json()}
    assert set(by_id) == {m.id for m in ALL_MANIFESTS}
    assert by_id["echo"] == {
        "id": "echo",
        "version": "0.1.0",
        "status": "running",
        "a2a_url": "http://testserver/a2a/echo",
        "native_url": "http://127.0.0.1:9000",
    }


def test_agent_list_docker_unavailable():
    with _tc(_app(FakeRegistry(error=DockerError("daemon down")))) as c:
        resp = c.get("/arena/v1/agents")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "docker_unavailable"
    assert "daemon down" in resp.json()["error"]["message"]


def test_agent_card(client):
    resp = client.get("/a2a/echo/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Echo"
    assert card["supportedInterfaces"][0]["url"] == "http://testserver/a2a/echo"
    assert card["skills"][0]["id"] == "echo"


def test_agent_card_unknown_agent(client):
    resp = client.get("/a2a/nope/.well-known/agent-card.json")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_running"


# ── A2A: HTTP agents ──


def test_send_message_metadata(client):
    resp = client.post("/a2a/echo", json=_send("hi", "c-1", rpc_id=7))
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 7
    message = body["result"]["message"]
    assert message["role"] == "ROLE_AGENT"
    assert message["contextId"] == "c-1"
    assert message["parts"] == [{"text": "echo: hi (0 before)"}]
    meta = message["metadata"]["humanbound"]
    assert meta["agent"] == "echo"
    assert meta["version"] == "0.1.0"
    assert isinstance(meta["latency_ms"], int)
    assert meta["tool_calls"] == [{"name": "echo", "parameters": {}, "result": ""}]
    assert meta["tool_calls_raw"] == [{"name": "echo"}]
    assert list(message).index("parts") < list(message).index("metadata")


def test_send_message_creates_context_when_missing(client):
    resp = client.post("/a2a/echo", json=_send("hi"))
    assert resp.status_code == 200
    assert resp.json()["result"]["message"]["contextId"]


def test_per_context_history(client):
    assert _reply(client.post("/a2a/echo", json=_send("one", "c-1"))) == "echo: one (0 before)"
    assert _reply(client.post("/a2a/echo", json=_send("two", "c-1"))) == "echo: two (2 before)"
    assert _reply(client.post("/a2a/echo", json=_send("x", "c-2"))) == "echo: x (0 before)"


def test_same_context_id_is_independent_per_agent(client):
    assert _reply(client.post("/a2a/echo", json=_send("one", "shared"))) == "echo: one (0 before)"
    assert _reply(client.post("/a2a/plain", json=_send("x", "shared"))) == "echo: x (0 before)"
    assert _reply(client.post("/a2a/echo", json=_send("two", "shared"))) == "echo: two (2 before)"
    contexts = client.app.state.contexts
    _, ectx = contexts.get_or_create("echo", "shared")
    _, pctx = contexts.get_or_create("plain", "shared")
    assert ectx is not pctx
    assert len(ectx.history) == 4
    assert pctx.history == []


def test_history_recorded_only_for_gateway_agents(client):
    client.post("/a2a/echo", json=_send("one", "g-1"))
    client.post("/a2a/plain", json=_send("one", "p-1"))
    resp = client.post("/a2a/plain", json=_send("two", "p-1"))
    assert _reply(resp) == "echo: two (0 before)"
    contexts = client.app.state.contexts
    _, gctx = contexts.get_or_create("echo", "g-1")
    _, pctx = contexts.get_or_create("plain", "p-1")
    assert gctx.history == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "echo: one (0 before)"},
    ]
    assert pctx.history == []


def test_no_tool_calls_key_when_not_mapped(client):
    resp = client.post("/a2a/plain", json=_send("hi"))
    meta = resp.json()["result"]["message"]["metadata"]["humanbound"]
    assert "tool_calls" not in meta
    assert "tool_calls_raw" not in meta


def test_tool_calls_are_normalized_in_split_call_result_shape(agent_state):
    """A trace (separate call and result steps) becomes one item per call."""
    trace = [
        {"type": "tool_call", "name": "lookup", "args": {"sku": "A1"}},
        {"type": "tool_result", "name": "lookup", "content": "9.99"},
        "junk",
    ]
    traced = _variant(
        "traced",
        {
            "type": "http",
            "chat_completion": {"endpoint": "/traced", "payload": {"prompt": "$PROMPT"}},
            "response": {"text": "reply", "tool_calls": "trace"},
        },
    )

    async def traced_chat(request: Request):
        return JSONResponse({"reply": "ok", "trace": trace})

    agent = fake_agent_app(agent_state)
    agent.router.routes.append(Route("/traced", traced_chat, methods=["POST"]))
    app = create_app(
        FakeRegistry([traced]),
        transport=httpx.ASGITransport(app=agent),
        allowed_hosts=["testserver"],
        token=TOKEN,
    )
    with _tc(app) as c:
        resp = c.post("/a2a/traced", json=_send("hi"))
        meta = resp.json()["result"]["message"]["metadata"]["humanbound"]
        assert meta["tool_calls"] == [
            {"name": "lookup", "parameters": {"sku": "A1"}, "result": "9.99"}
        ]
        assert meta["tool_calls_raw"] == trace
        chat = c.post(
            "/v1/chat/completions",
            json={"model": "arena/traced", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert chat.status_code == 200
        assert chat.json()["humanbound"]["tool_calls"] == meta["tool_calls"]


def test_thread_init_runs_once_per_context(client, agent_state):
    assert _reply(client.post("/a2a/threaded", json=_send("a", "c-1"))) == "[t1] a"
    assert _reply(client.post("/a2a/threaded", json=_send("b", "c-1"))) == "[t1] b"
    assert agent_state.starts == 1
    assert _reply(client.post("/a2a/threaded", json=_send("c", "c-2"))) == "[t2] c"
    assert agent_state.starts == 2


def test_thread_init_runs_once_under_concurrency(agent_state):
    app = _app(agent_state=agent_state)

    async def go():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", headers=AUTH
            ) as c:
                return await asyncio.gather(
                    c.post("/a2a/threaded", json=_send("a", "c-1")),
                    c.post("/a2a/threaded", json=_send("b", "c-1")),
                )

    r1, r2 = asyncio.run(go())
    assert agent_state.starts == 1
    assert {_reply(r1), _reply(r2)} == {"[t1] a", "[t1] b"}


# ── A2A: native agents ──


def test_native_send_message_normalized(client, agent_state):
    resp = client.post("/a2a/native", json=_send("hello", "n-1", rpc_id="r1"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "r1"
    message = body["result"]["message"]
    assert message["parts"] == [{"text": "native: hello"}]
    assert message["contextId"] == "n-1"
    meta = message["metadata"]["humanbound"]
    assert meta["agent"] == "native"
    assert meta["version"] == "0.1.0"
    assert isinstance(meta["latency_ms"], int)
    headers, forwarded = agent_state.a2a_requests[0]
    assert headers["a2a-version"] == "1.0"
    assert forwarded["params"]["message"]["parts"] == [{"text": "hello"}]


def test_native_forwards_version_header(client, agent_state):
    client.post("/a2a/native", json=_send("hello"), headers={"A2A-Version": "1.0.1"})
    assert agent_state.a2a_requests[0][0]["a2a-version"] == "1.0.1"


def test_native_context_id_from_upstream_message(client):
    resp = client.post("/a2a/native", json=_send("withctx", "mine"))
    assert resp.json()["result"]["message"]["contextId"] == "up-msg-ctx"


def test_native_context_id_generated_when_missing(client):
    resp = client.post("/a2a/native", json=_send("hello"))
    assert resp.json()["result"]["message"]["contextId"]


def test_native_task_reply_is_artifact_text(client):
    resp = client.post("/a2a/native", json=_send("task", "n-1"))
    assert resp.status_code == 200
    message = resp.json()["result"]["message"]
    assert message["parts"] == [{"text": "artifact answer"}]
    assert message["contextId"] == "up-ctx"


def test_native_get_task_unchanged(client):
    body = {"jsonrpc": "2.0", "id": 3, "method": "GetTask", "params": {"id": "task-1"}}
    resp = client.post("/a2a/native", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"jsonrpc": "2.0", "id": 3, "result": {"id": "task-1", "raw": True}}


def test_native_other_methods_not_forwarded(client, agent_state):
    body = {"jsonrpc": "2.0", "id": 1, "method": "CancelTask", "params": {}}
    resp = client.post("/a2a/native", json=body)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32601
    assert agent_state.a2a_requests == []


def test_native_upstream_error_is_502(client):
    resp = client.post("/a2a/native", json=_send("error"))
    assert resp.status_code == 502
    assert resp.json()["error"] == {"code": -32603, "message": "upstream"}


def test_native_non_dict_body_unextractable(client):
    resp = client.post("/a2a/native", json=_send("list"))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == -32006


# ── A2A: protocol errors ──


def test_unknown_method(client):
    resp = client.post("/a2a/echo", json=_send("x", method="Frobnicate"))
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32601
    assert resp.json()["id"] == "1"


def test_get_task_on_http_agent(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "t"}}
    resp = client.post("/a2a/echo", json=body)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32001


def test_parse_error(client):
    resp = client.post(
        "/a2a/echo", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": resp.json()["error"]["message"]},
    }


def test_unsupported_version(client):
    resp = client.post("/a2a/echo", json=_send("x"), headers={"A2A-Version": "2.0"})
    assert resp.status_code == 200
    err = resp.json()["error"]
    assert err["code"] == -32009
    assert err["data"][0]["reason"] == "VERSION_NOT_SUPPORTED"


@pytest.mark.parametrize("bad_id", [True, None, {"a": 1}, [1]])
def test_invalid_id_is_invalid_request_with_null_id(client, bad_id):
    body = _send("x")
    body["id"] = bad_id
    resp = client.post("/a2a/echo", json=body)
    assert resp.status_code == 200
    assert resp.json()["id"] is None
    assert resp.json()["error"]["code"] == -32600


def test_non_text_part_is_32005(client):
    body = _send("x")
    body["params"]["message"]["parts"] = [{"file": {"uri": "x"}}]
    resp = client.post("/a2a/echo", json=body)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32005


@pytest.mark.parametrize("text", [123, None, ["a"], {"t": 1}, True])
def test_non_string_text_is_invalid_params(client, text):
    body = _send("x")
    body["params"]["message"]["parts"] = [{"text": text}]
    resp = client.post("/a2a/echo", json=body)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32602
    assert resp.json()["id"] == "1"


def test_notification_rejected(client):
    body = _send("x")
    del body["id"]
    resp = client.post("/a2a/echo", json=body)
    assert resp.json()["error"]["code"] == -32600
    assert resp.json()["id"] is None


# ── A2A: agent failures ──


def test_unextractable_reply(client):
    resp = client.post("/a2a/broken", json=_send("x", rpc_id=5))
    assert resp.status_code == 502
    body = resp.json()
    assert body["id"] == 5
    assert body["error"]["code"] == -32006
    assert body["error"]["data"][0]["reason"] == "UNEXTRACTABLE_RESPONSE"


def test_agent_http_error(client):
    resp = client.post("/a2a/failing", json=_send("x"))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == -32603
    assert resp.json()["error"]["data"][0]["reason"] == "AGENT_ERROR"


def test_agent_not_running(client):
    resp = client.post("/a2a/ghost", json=_send("x"))
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == -32603
    assert err["data"][0]["reason"] == "AGENT_NOT_RUNNING"
    assert "ghost is not running, and it is not installed" in err["message"]
    assert "hb arena run ghost" not in err["message"]


def test_docker_unavailable_on_a2a():
    with _tc(_app(FakeRegistry(error=DockerError("daemon down")))) as c:
        resp = c.post("/a2a/echo", json=_send("x"))
    assert resp.status_code == 503
    err = resp.json()["error"]
    assert err["data"][0]["reason"] == "DOCKER_UNAVAILABLE"
    assert err["message"].startswith("Docker is not reachable: ")


# ── OpenAI façade ──


def _chat(model, *messages, **extra):
    return {"model": model, "messages": list(messages), **extra}


def test_openai_http_agent_with_history(client):
    resp = client.post(
        "/v1/chat/completions",
        json=_chat(
            "arena/echo",
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "r1"},
            {"role": "user", "content": "two"},
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "arena/echo"
    assert body["choices"][0]["message"]["content"] == "echo: two (2 before)"
    assert body["humanbound"]["agent"] == "echo"
    assert body["humanbound"]["tool_calls"] == [{"name": "echo", "parameters": {}, "result": ""}]


def test_openai_fresh_conversation_each_request(client, agent_state):
    for text in ("a", "b"):
        resp = client.post(
            "/v1/chat/completions", json=_chat("arena/threaded", {"role": "user", "content": text})
        )
        assert resp.status_code == 200
    assert agent_state.starts == 2


def test_openai_native_agent(client):
    resp = client.post(
        "/v1/chat/completions", json=_chat("arena/native", {"role": "user", "content": "yo"})
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "native: yo"


def test_openai_native_error_is_502(client):
    resp = client.post(
        "/v1/chat/completions", json=_chat("arena/native", {"role": "user", "content": "error"})
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "agent_error"


@pytest.mark.parametrize(
    "body",
    [
        {"model": "gpt-4", "messages": [{"role": "user", "content": "x"}]},
        {"model": "arena/echo", "messages": []},
        {"model": "arena/echo", "messages": [{"role": "user", "content": "x"}], "stream": True},
        [1, 2],
    ],
)
def test_openai_bad_request(client, body):
    resp = client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_openai_invalid_json(client):
    resp = client.post(
        "/v1/chat/completions", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_openai_unknown_agent(client):
    resp = client.post(
        "/v1/chat/completions", json=_chat("arena/ghost", {"role": "user", "content": "x"})
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_running"


def test_openai_unextractable(client):
    resp = client.post(
        "/v1/chat/completions", json=_chat("arena/broken", {"role": "user", "content": "x"})
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "unextractable_response"


# ── reset ──


def test_reset_success_drops_contexts(registry, agent_state):
    calls = []

    def fake_reset(m, agent_dir):
        calls.append((m.id, agent_dir))

    with _tc(_app(registry, agent_state=agent_state, reset_agent=fake_reset)) as c:
        c.post("/a2a/echo", json=_send("one", "c-1"))
        c.post("/a2a/plain", json=_send("one", "p-1"))
        assert len(c.app.state.contexts) == 2
        resp = c.post("/arena/v1/agents/echo/reset", json={})
        assert resp.status_code == 200
        assert resp.json() == {"id": "echo", "status": "reset"}
        assert calls == [("echo", Path("/nonexistent") / "echo")]
        assert len(c.app.state.contexts) == 1
        assert registry.invalidations == 1
        # the conversation starts over
        assert _reply(c.post("/a2a/echo", json=_send("two", "c-1"))) == "echo: two (0 before)"


@pytest.mark.parametrize("exc", [DockerError("boom"), runtime.HealthTimeout("slow"), KeyError("x")])
def test_reset_failure_still_drops_contexts(registry, exc):
    def fake_reset(m, agent_dir):
        raise exc

    with _tc(_app(registry, reset_agent=fake_reset)) as c:
        c.post("/a2a/echo", json=_send("one", "c-1"))
        resp = c.post("/arena/v1/agents/echo/reset", json={})
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "reset_failed"
        assert len(c.app.state.contexts) == 0
        assert registry.invalidations == 1


def test_reset_refused_by_the_container_baseline_is_a_reset_failure(registry):
    from humanbound_cli.arena.baseline import BaselineError, Violation

    violation = Violation("arena-x-echo", "non-root", "runs as root (Config.User is 'root')")

    def fake_reset(m, agent_dir):
        raise BaselineError(m.id, [violation])

    with _tc(_app(registry, reset_agent=fake_reset)) as c:
        resp = c.post("/arena/v1/agents/echo/reset", json={})
        assert resp.status_code == 500
        error = resp.json()["error"]
        assert error["code"] == "reset_failed"
        assert error["message"].startswith("could not reset echo: ")
        assert "container baseline" in error["message"]
        assert str(violation) in error["message"].splitlines()


def test_forget_drops_contexts_and_invalidates(registry, agent_state):
    with _tc(_app(registry, agent_state=agent_state)) as c:
        c.post("/a2a/echo", json=_send("one", "c-1"))
        c.post("/a2a/plain", json=_send("one", "p-1"))
        resp = c.post("/arena/v1/agents/echo/forget", json={})
        assert resp.status_code == 200
        assert resp.json() == {"id": "echo", "status": "forgotten"}
        assert len(c.app.state.contexts) == 1
        assert registry.invalidations == 1
        assert _reply(c.post("/a2a/echo", json=_send("two", "c-1"))) == "echo: two (0 before)"


def test_forget_needs_no_running_agent(registry):
    with _tc(_app(registry)) as c:
        resp = c.post("/arena/v1/agents/ghost/forget", json={})
    assert resp.status_code == 200
    assert registry.invalidations == 1


def test_forget_requires_json(client):
    resp = client.post(
        "/arena/v1/agents/echo/forget", content=b"x", headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 415
    resp = client.post(
        "/arena/v1/agents/echo/forget",
        content=b"{nope",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_forget_get_not_allowed(client):
    assert client.get("/arena/v1/agents/echo/forget").status_code == 405


def test_reset_unknown_agent(client):
    resp = client.post("/arena/v1/agents/ghost/reset", json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_running"


def test_reset_docker_unavailable():
    with _tc(_app(FakeRegistry(error=DockerError("down")))) as c:
        resp = c.post("/arena/v1/agents/echo/reset", json={})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "docker_unavailable"


# ── local guard ──


def test_foreign_host_rejected_even_with_the_token():
    with _tc(_app(allowed_hosts=None), base_url="http://evil.example.com") as c:
        resp = c.get("/arena/v1/agents")
    assert resp.status_code == 400
    assert resp.text == "Invalid host header"


@pytest.mark.parametrize(
    "host", ["127.0.0.1:11500", "localhost", "LOCALHOST:1", "[::1]:11500", "[::1]"]
)
def test_loopback_hosts_accepted(host):
    with _tc(_app(allowed_hosts=None)) as c:
        resp = c.get("/arena/v1/health", headers={"Host": host})
    assert resp.status_code == 200


def test_host_with_port_only_prefix_is_not_loopback():
    with _tc(_app(allowed_hosts=None)) as c:
        resp = c.get("/arena/v1/health", headers={"Host": "127.0.0.1.evil.com"})
    assert resp.status_code == 400


def test_star_accepts_any_host():
    with _tc(_app(allowed_hosts=["*"]), base_url="http://evil.example.com") as c:
        resp = c.get("/arena/v1/health")
    assert resp.status_code == 200


def test_text_plain_post_rejected_on_a2a(client):
    resp = client.post("/a2a/echo", content=b"{}", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 415
    body = resp.json()
    assert body["error"]["code"] == -32600
    assert body["id"] is None


def test_text_plain_post_rejected_elsewhere(client):
    resp = client.post(
        "/v1/chat/completions", content=b"{}", headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"


def test_missing_content_type_rejected(client):
    resp = client.post("/arena/v1/agents/echo/reset")
    assert resp.status_code == 415


def test_json_content_type_with_params_accepted(client):
    resp = client.post(
        "/a2a/echo",
        content=b'{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":'
        b'{"role":"ROLE_USER","parts":[{"text":"hi"}]}}}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert resp.status_code == 200


# ── pidfile ──


def test_pidfile_written_and_removed(tmp_path):
    pidfile = tmp_path / "run" / "gateway.pid"
    with _tc(_app(pidfile=pidfile)):
        assert pidfile.read_text().strip() == str(os.getpid())
    assert not pidfile.exists()


def test_pidfile_left_alone_when_overwritten(tmp_path):
    pidfile = tmp_path / "gateway.pid"
    with _tc(_app(pidfile=pidfile)):
        pidfile.write_text("999999")
    assert pidfile.read_text() == "999999"


# ── registry ──


def _install(arena_home, raw_or_text, agent_id, version="0.1.0"):
    target = arena_home / "agents" / agent_id / version
    target.mkdir(parents=True, exist_ok=True)
    text = raw_or_text if isinstance(raw_or_text, str) else yaml.safe_dump(raw_or_text)
    (target / "arena.yaml").write_text(text, encoding="utf-8")
    return target


def _raw(agent_id):
    raw = copy.deepcopy(ECHO_RAW)
    raw["id"] = agent_id
    return raw


def test_registry_joins_running_and_installed(arena_home, monkeypatch):
    target = _install(arena_home, _raw("echo"), "echo")
    _install(arena_home, _raw("noport"), "noport")
    monkeypatch.setattr(
        runtime,
        "list_running",
        returns(
            RunningAgent("echo", "0.1.0", "image", 4001),
            RunningAgent("noport", "0.1.0", "image", None),
            RunningAgent("uninstalled", "0.1.0", "image", 4002),
        ),
    )
    reg = AgentRegistry()
    entries = reg.all()
    assert [e.manifest.id for e in entries] == ["echo"]
    entry = reg.get("echo")
    assert entry.agent.host_port == 4001
    assert entry.agent_dir == target
    assert reg.get("noport") is None
    assert reg.get("uninstalled") is None


def test_registry_bad_manifest_skips_only_that_agent(arena_home, monkeypatch):
    _install(arena_home, _raw("echo"), "echo")
    _install(arena_home, "id: bad\nthis: [is not valid", "bad")
    _install(arena_home, _raw("oserr"), "oserr")
    monkeypatch.setattr(
        runtime,
        "list_running",
        returns(
            RunningAgent("bad", "0.1.0", "image", 4000),
            RunningAgent("oserr", "0.1.0", "image", 4003),
            RunningAgent("echo", "0.1.0", "image", 4001),
        ),
    )
    real_installed = catalog.installed

    def installed(agent_id, version=None):
        if agent_id == "oserr":
            raise OSError("disk gone")
        return real_installed(agent_id, version)

    monkeypatch.setattr(catalog, "installed", installed)
    reg = AgentRegistry()
    assert [e.manifest.id for e in reg.all()] == ["echo"]


def test_bad_manifest_does_not_hide_others_through_the_app(arena_home, monkeypatch):
    _install(arena_home, _raw("echo"), "echo")
    _install(arena_home, "not: [valid", "bad")
    monkeypatch.setattr(
        runtime,
        "list_running",
        returns(
            RunningAgent("bad", "0.1.0", "image", 4000),
            RunningAgent("echo", "0.1.0", "image", 4001),
        ),
    )
    with _tc(_app(AgentRegistry())) as c:
        resp = c.get("/arena/v1/agents")
        assert [a["id"] for a in resp.json()] == ["echo"]
        assert _reply(c.post("/a2a/echo", json=_send("hi"))) == "echo: hi (0 before)"


def test_registry_docker_error_propagates(monkeypatch):
    def boom():
        raise DockerError("down")

    monkeypatch.setattr(runtime, "list_running", boom)
    with pytest.raises(DockerError):
        AgentRegistry().get("echo")


def test_registry_ttl(arena_home, monkeypatch):
    _install(arena_home, _raw("echo"), "echo")
    calls = []

    def list_running():
        calls.append(1)
        return [RunningAgent("echo", "0.1.0", "image", 4001)]

    monkeypatch.setattr(runtime, "list_running", list_running)
    now = [100.0]
    reg = AgentRegistry(ttl=2.0, clock=lambda: now[0])
    reg.get("echo")
    reg.all()
    now[0] += 1.9
    reg.get("echo")
    assert len(calls) == 1
    now[0] += 0.2
    reg.get("echo")
    assert len(calls) == 2
    reg.invalidate()
    reg.get("echo")
    assert len(calls) == 3


def test_registry_refresh_overlapping_invalidate_is_discarded(monkeypatch):
    calls = []
    reg = AgentRegistry()

    def list_running():
        calls.append(1)
        if len(calls) == 1:
            reg.invalidate()  # an invalidate lands mid-refresh
        return []

    monkeypatch.setattr(runtime, "list_running", list_running)
    reg.all()
    reg.all()
    assert len(calls) == 2  # the first result was not trusted as fresh
    reg.all()
    assert len(calls) == 2


def test_registry_single_flight(monkeypatch):
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def list_running():
        calls.append(1)
        entered.set()
        release.wait(5)
        return []

    monkeypatch.setattr(runtime, "list_running", list_running)
    reg = AgentRegistry()
    results = []
    threads = [threading.Thread(target=lambda: results.append(reg.all())) for _ in range(3)]
    threads[0].start()
    assert entered.wait(5)
    for t in threads[1:]:
        t.start()
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert results == [[], [], []]


# ── access token ──


def _anon(app, **kwargs) -> TestClient:
    return TestClient(app, **kwargs)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}])
def test_health_without_the_token_is_minimal(headers):
    with _anon(_app()) as c:
        resp = c.get("/arena/v1/health", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    # "Authorization: Bearer <token>" is what every `client` test sends (test_health)
    [{"authorization": f"bearer {TOKEN}"}, {"X-Arena-Token": TOKEN}],
)
def test_health_with_token_is_full(headers):
    with _anon(_app()) as c:
        resp = c.get("/arena/v1/health", headers=headers)
    assert resp.json()["owner"] == paths.arena_owner()
    assert resp.json()["pid"] == os.getpid()


PROTECTED = [
    ("GET", "/arena/v1/agents", None),
    ("POST", "/arena/v1/agents/echo/reset", {}),
    ("POST", "/arena/v1/agents/echo/forget", {}),
    ("GET", "/a2a/echo/.well-known/agent-card.json", None),
    ("POST", "/v1/chat/completions", {"model": "arena/echo", "messages": []}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": TOKEN},  # no scheme
        {"Authorization": f"Basic {TOKEN}"},
        {"X-Arena-Token": "wrong"},
        {"Authorization": f"Bearer {TOKEN}x"},
    ],
)
def test_routes_need_the_token(method, path, body, headers):
    resets = []
    app = _app(reset_agent=lambda m, d: resets.append(m.id))
    with _anon(app) as c:
        resp = c.request(method, path, json=body, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")
    assert resp.json()["error"]["code"] == "unauthorized"
    assert TOKEN not in resp.text
    assert resets == []


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_routes_accept_x_arena_token(method, path, body):
    with _anon(_app()) as c:
        resp = c.request(method, path, json=body, headers={"X-Arena-Token": TOKEN})
    assert resp.status_code != 401


def test_a2a_without_token_is_a_json_rpc_error():
    with _anon(_app()) as c:
        resp = c.post("/a2a/echo", json=_send("hi", rpc_id="7"))
    assert resp.status_code == 401
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] is None
    assert body["error"]["code"] == -32600
    assert "token" in body["error"]["message"]


def test_token_checked_before_content_type():
    with _anon(_app()) as c:
        resp = c.post("/a2a/echo", content=b"{}", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 401


def test_any_host_still_needs_the_token():
    """serve --host <non-loopback>: the Host guard is off, the token is not."""
    app = _app(allowed_hosts=["*"])
    with _anon(app, base_url="http://192.168.1.20:11500") as c:
        assert c.get("/arena/v1/agents").status_code == 401
        assert c.get("/arena/v1/health").json() == {"status": "ok"}
        assert c.get("/arena/v1/agents", headers=AUTH).status_code == 200


def test_default_token_is_the_owners(arena_home):
    token = paths.gateway_token()
    app = create_app(FakeRegistry(), allowed_hosts=["testserver"])
    with _anon(app) as c:
        assert c.get("/arena/v1/agents").status_code == 401
        resp = c.get("/arena/v1/agents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


def test_agent_card_declares_bearer_auth(client):
    card = client.get("/a2a/echo/.well-known/agent-card.json").json()
    assert card["securitySchemes"] == {
        "arenaToken": {
            "httpAuthSecurityScheme": {
                "scheme": "Bearer",
                "description": card["securitySchemes"]["arenaToken"]["httpAuthSecurityScheme"][
                    "description"
                ],
            }
        }
    }
    assert card["securityRequirements"] == [{"schemes": {"arenaToken": {"list": []}}}]


# ── the client the gateway uses to reach agents ──


def _captured_agent_client(monkeypatch, **app_kwargs):
    from humanbound_cli.arena import gateway as gateway_mod

    captured = {}
    real_client = httpx.AsyncClient

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gateway_mod.httpx, "AsyncClient", spy)
    app = create_app(FakeRegistry(), allowed_hosts=["testserver"], token=TOKEN, **app_kwargs)

    async def go():
        async with app.router.lifespan_context(app):
            return app.state.http

    client = asyncio.run(go())
    monkeypatch.setattr(gateway_mod.httpx, "AsyncClient", real_client)
    return captured, client


def test_agent_client_does_not_reuse_kept_alive_connections(monkeypatch):
    captured, client = _captured_agent_client(monkeypatch)
    limits = captured["limits"]
    assert isinstance(limits, httpx.Limits)
    assert limits.max_keepalive_connections == 0
    assert captured["trust_env"] is False
    assert captured["transport"] is None


def test_agent_client_keeps_injected_transport(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    captured, client = _captured_agent_client(monkeypatch, transport=transport)
    assert captured["transport"] is transport
    assert captured["limits"].max_keepalive_connections == 0
    assert captured["trust_env"] is False
