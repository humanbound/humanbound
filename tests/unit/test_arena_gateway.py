# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import asyncio
import copy

import httpx
import pytest
from conftest import ARENA_FIXTURES
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from humanbound_cli.arena import gateway
from humanbound_cli.arena.gateway import RegistryEntry, create_app
from humanbound_cli.arena.manifest import ManifestError, load_manifest, parse_manifest
from humanbound_cli.arena.runtime import DockerError, RunningAgent

ECHO = load_manifest(ARENA_FIXTURES / "catalog" / "agents" / "echo" / "arena.yaml")


def _variant(agent_id, integration):
    data = copy.deepcopy(ECHO.model_dump(mode="json"))
    data["id"] = agent_id
    data["integration"] = integration
    return parse_manifest(data)


THREADED = _variant(
    "threaded",
    {
        "type": "http",
        "thread_init": {"endpoint": "/start", "payload": {}},
        "chat_completion": {"endpoint": "/threads/$thread_id/chat", "payload": {"q": "$PROMPT"}},
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
NATIVE = _variant("native", {"type": "a2a", "path": "/a2a"})
FAILING_NATIVE = _variant("failing-native", {"type": "a2a", "path": "/a2a-error"})
ODD_NATIVE = _variant("odd-native", {"type": "a2a", "path": "/a2a-list"})

TEST_HOSTS = ["testserver", "gw"]


async def _chat(request: Request):
    body = await request.json()
    history = body.get("history") or []
    return JSONResponse(
        {
            "reply": f"echo: {body.get('prompt')} ({len(history)} before)",
            "trace": {"tools": [{"name": "echo"}]},
        }
    )


async def _start(request):
    return JSONResponse({"thread_id": "t-1"})


async def _thread_chat(request):
    body = await request.json()
    return JSONResponse({"reply": f"{request.path_params['tid']}: {body['q']}"})


async def _broken(request):
    return JSONResponse({"nothing": "here"})


async def _native(request):
    body = await request.json()
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "message": {
                    "role": "ROLE_AGENT",
                    "messageId": "m",
                    "contextId": "c",
                    "parts": [{"text": "native"}],
                }
            },
        }
    )


async def _native_error(request):
    body = await request.json()
    return JSONResponse(
        {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32603, "message": "boom"}}
    )


async def _native_list(request):
    return JSONResponse(["not", "a", "dict"])


FAKE_AGENT = Starlette(
    routes=[
        Route("/chat", _chat, methods=["POST"]),
        Route("/start", _start, methods=["POST"]),
        Route("/threads/{tid}/chat", _thread_chat, methods=["POST"]),
        Route("/broken", _broken, methods=["POST"]),
        Route("/a2a", _native, methods=["POST"]),
        Route("/a2a-error", _native_error, methods=["POST"]),
        Route("/a2a-list", _native_list, methods=["POST"]),
    ]
)


class FakeRegistry:
    def __init__(self, manifests):
        self.entries = {
            m.id: RegistryEntry(RunningAgent(m.id, m.version, "image", 9999), m, ARENA_FIXTURES)
            for m in manifests
        }
        self.invalidated = 0

    def get(self, agent_id):
        return self.entries.get(agent_id)

    def all(self):
        return list(self.entries.values())

    def invalidate(self):
        self.invalidated += 1


@pytest.fixture
def resets():
    return []


@pytest.fixture
def client(resets):
    registry = FakeRegistry([ECHO, THREADED, BROKEN, NATIVE, FAILING_NATIVE, ODD_NATIVE])
    app = create_app(
        registry,
        transport=httpx.ASGITransport(app=FAKE_AGENT),
        reset_agent=lambda m, d: resets.append(m.id),
        allowed_hosts=TEST_HOSTS,
    )
    with TestClient(app) as c:
        c.registry = registry
        c.contexts = app.state.contexts
        yield c


def _rpc_body(text, context_id=None, rpc_id=1):
    message = {"role": "ROLE_USER", "messageId": f"m-{rpc_id}", "parts": [{"text": text}]}
    if context_id:
        message["contextId"] = context_id
    return {"jsonrpc": "2.0", "id": rpc_id, "method": "SendMessage", "params": {"message": message}}


def send(client, agent_id, text, context_id=None, rpc_id=1, headers=None):
    return client.post(
        f"/a2a/{agent_id}",
        json=_rpc_body(text, context_id, rpc_id),
        headers=headers or {"A2A-Version": "1.0"},
    )


def test_health_and_agent_list(client):
    assert client.get("/arena/v1/health").json()["status"] == "ok"
    agents = {a["id"]: a for a in client.get("/arena/v1/agents").json()}
    assert agents["echo"]["a2a_url"] == "http://testserver/a2a/echo"
    assert agents["echo"]["native_url"] == "http://127.0.0.1:9999"


def test_agent_card(client):
    card = client.get("/a2a/echo/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["url"] == "http://testserver/a2a/echo"
    assert client.get("/a2a/ghost/.well-known/agent-card.json").status_code == 404


def test_send_message_returns_a2a_message_with_metadata(client):
    body = send(client, "echo", "hello").json()
    message = body["result"]["message"]
    assert body["id"] == 1
    assert message["role"] == "ROLE_AGENT"
    assert message["parts"] == [{"text": "echo: hello (0 before)"}]
    assert message["metadata"]["humanbound"]["tool_calls"] == [{"name": "echo"}]
    assert message["metadata"]["humanbound"]["agent"] == "echo"
    assert len(message["contextId"]) == 32


def test_gateway_history_is_kept_per_context(client):
    send(client, "echo", "one", context_id="c-1")
    second = send(client, "echo", "two", context_id="c-1", rpc_id=2).json()
    other = send(client, "echo", "solo", context_id="c-2", rpc_id=3).json()
    assert second["result"]["message"]["contextId"] == "c-1"
    # the fake agent reports how many prior turns it received: history is per context
    assert second["result"]["message"]["parts"][0]["text"] == "echo: two (2 before)"
    assert other["result"]["message"]["parts"][0]["text"] == "echo: solo (0 before)"


def test_thread_init_runs_once_per_context(client):
    body = send(client, "threaded", "hi", context_id="c-9").json()
    assert body["result"]["message"]["parts"][0]["text"] == "t-1: hi"


def test_history_is_only_recorded_for_gateway_history_agents(client):
    send(client, "threaded", "hi", context_id="c-9")
    send(client, "threaded", "again", context_id="c-9", rpc_id=2)
    _, ctx = client.contexts.get_or_create("threaded", "c-9")
    assert ctx.history == []
    send(client, "echo", "hi", context_id="c-9")
    _, ctx = client.contexts.get_or_create("echo", "c-9")
    assert [t["role"] for t in ctx.history] == ["user", "assistant"]


def test_concurrent_first_messages_run_thread_init_once():
    starts = []

    async def start(request):
        starts.append(1)
        await asyncio.sleep(0.05)
        return JSONResponse({"thread_id": f"t-{len(starts)}"})

    agent = Starlette(
        routes=[
            Route("/start", start, methods=["POST"]),
            Route("/threads/{tid}/chat", _thread_chat, methods=["POST"]),
        ]
    )
    app = create_app(
        FakeRegistry([THREADED]),
        transport=httpx.ASGITransport(app=agent),
        reset_agent=lambda m, d: None,
        allowed_hosts=TEST_HOSTS,
    )

    async def run():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://gw") as c:
                return await asyncio.gather(
                    c.post("/a2a/threaded", json=_rpc_body("a", "c-x", 1)),
                    c.post("/a2a/threaded", json=_rpc_body("b", "c-x", 2)),
                )

    first, second = asyncio.run(run())
    assert len(starts) == 1
    texts = {r.json()["result"]["message"]["parts"][0]["text"] for r in (first, second)}
    assert texts == {"t-1: a", "t-1: b"}


def test_native_a2a_agents_are_passed_through_with_latency(client):
    body = send(client, "native", "hi").json()
    assert body["result"]["message"]["parts"] == [{"text": "native"}]
    assert "latency_ms" in body["result"]["message"]["metadata"]["humanbound"]


def test_protocol_errors_are_json_rpc_with_http_200(client):
    r = client.post("/a2a/echo", json={"jsonrpc": "2.0", "id": 5, "method": "Nope", "params": {}})
    assert r.status_code == 200 and r.json()["error"]["code"] == -32601
    r = client.post(
        "/a2a/echo", json={"jsonrpc": "2.0", "id": 6, "method": "GetTask", "params": {"id": "x"}}
    )
    assert r.json()["error"]["code"] == -32001
    r = client.post("/a2a/echo", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json()["error"]["code"] == -32700
    r = send(client, "echo", "x", headers={"A2A-Version": "0.3"})
    assert r.json()["error"]["code"] == -32009
    r = client.post("/a2a/echo", json={"jsonrpc": "2.0", "id": {"bad": 1}, "method": "SendMessage"})
    assert r.json()["error"]["code"] == -32600 and r.json()["id"] is None


def test_agent_failures_use_non_200(client):
    r = send(client, "broken", "x")
    assert r.status_code == 502 and r.json()["error"]["code"] == -32006
    r = send(client, "ghost", "x")
    assert r.status_code == 404
    assert r.json()["error"]["data"][0]["reason"] == "AGENT_NOT_RUNNING"


def test_openai_facade(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "arena/echo",
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "echo: one"},
                {"role": "user", "content": "two"},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "echo: two (2 before)"
    native = client.post(
        "/v1/chat/completions",
        json={"model": "arena/native", "messages": [{"role": "user", "content": "x"}]},
    )
    assert native.json()["choices"][0]["message"]["content"] == "native"
    bad = client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": []})
    assert bad.status_code == 400
    missing = client.post(
        "/v1/chat/completions",
        json={"model": "arena/ghost", "messages": [{"role": "user", "content": "x"}]},
    )
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "agent_not_running"


def test_openai_facade_rejects_malformed_json(client):
    r = client.post(
        "/v1/chat/completions", content=b"{nope", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_openai_facade_surfaces_native_a2a_errors(client):
    r = client.post(
        "/v1/chat/completions",
        json={"model": "arena/failing-native", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 502 and r.json()["error"]["code"] == "agent_error"


def test_reset_recreates_and_drops_contexts(client, resets):
    first = send(client, "threaded", "hi", context_id="c-1").json()
    assert first["result"]["message"]["parts"][0]["text"] == "t-1: hi"
    send(client, "echo", "hi", context_id="c-1")
    assert len(client.contexts) == 2
    r = client.post("/arena/v1/agents/threaded/reset", json={})
    assert r.json() == {"id": "threaded", "status": "reset"}
    assert resets == ["threaded"]
    assert client.registry.invalidated == 1
    assert len(client.contexts) == 1  # only echo's context survives


def test_agent_registry_refreshes_from_docker_with_ttl(monkeypatch):
    calls = []

    def list_running():
        calls.append(1)
        return [
            RunningAgent("echo", "0.1.0", "image", 9999),
            RunningAgent("orphan", "1.0.0", "image", 1),
        ]

    monkeypatch.setattr(gateway.runtime, "list_running", list_running)
    monkeypatch.setattr(
        gateway.catalog,
        "installed",
        lambda agent_id, version=None: (ECHO, ARENA_FIXTURES) if agent_id == "echo" else None,
    )
    now = [0.0]
    registry = gateway.AgentRegistry(ttl=2.0, clock=lambda: now[0])
    assert registry.get("echo").manifest.id == "echo"
    assert registry.get("orphan") is None  # running but no cached manifest
    assert len(calls) == 1
    now[0] = 5.0
    registry.all()
    assert len(calls) == 2
    registry.invalidate()
    registry.all()
    assert len(calls) == 3


# ── review fixes ──


class DockerDownRegistry(FakeRegistry):
    def get(self, agent_id):
        raise DockerError("Cannot connect to the Docker daemon")

    def all(self):
        raise DockerError("Cannot connect to the Docker daemon")


@pytest.fixture
def docker_down_client():
    app = create_app(
        DockerDownRegistry([]),
        transport=httpx.ASGITransport(app=FAKE_AGENT),
        reset_agent=lambda m, d: None,
        allowed_hosts=TEST_HOSTS,
    )
    with TestClient(app) as c:
        yield c


def test_docker_unavailable_is_a_json_rpc_503(docker_down_client):
    r = send(docker_down_client, "echo", "hi")
    assert r.status_code == 503
    body = r.json()
    assert body["id"] == 1 and body["error"]["code"] == -32603
    assert body["error"]["data"][0]["reason"] == "DOCKER_UNAVAILABLE"
    assert "Docker is not reachable" in body["error"]["message"]


def test_docker_unavailable_agent_list_is_503(docker_down_client):
    r = docker_down_client.get("/arena/v1/agents")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "docker_unavailable"
    card = docker_down_client.get("/a2a/echo/.well-known/agent-card.json")
    assert card.status_code == 503


def test_openai_facade_docker_unavailable_is_503(docker_down_client):
    r = docker_down_client.post(
        "/v1/chat/completions",
        json={"model": "arena/echo", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "docker_unavailable"


def test_bad_manifest_does_not_hide_other_agents(monkeypatch):
    monkeypatch.setattr(
        gateway.runtime,
        "list_running",
        lambda: [
            RunningAgent("bad", "1.0.0", "image", 1),
            RunningAgent("gone", "1.0.0", "image", 2),
            RunningAgent("echo", "0.1.0", "image", 9999),
        ],
    )

    def installed(agent_id, version=None):
        if agent_id == "bad":
            raise ManifestError("broken arena.yaml")
        if agent_id == "gone":
            raise OSError("permission denied")
        return ECHO, ARENA_FIXTURES

    monkeypatch.setattr(gateway.catalog, "installed", installed)
    registry = gateway.AgentRegistry()
    assert [e.manifest.id for e in registry.all()] == ["echo"]


def test_foreign_host_is_rejected(client):
    r = client.get("/arena/v1/health", headers={"host": "evil.example"})
    assert r.status_code == 400
    r = client.post("/a2a/echo", json=_rpc_body("x"), headers={"host": "evil.example:8080"})
    assert r.status_code == 400


def test_default_allowed_hosts_are_loopback():
    app = create_app(FakeRegistry([ECHO]), reset_agent=lambda m, d: None)
    with TestClient(app) as c:
        assert c.get("/arena/v1/health").status_code == 400  # Host: testserver
        for host in ("127.0.0.1:8321", "localhost", "[::1]:8321"):
            assert c.get("/arena/v1/health", headers={"host": host}).status_code == 200


def test_wildcard_allowed_hosts_accepts_any_host():
    app = create_app(FakeRegistry([ECHO]), reset_agent=lambda m, d: None, allowed_hosts=["*"])
    with TestClient(app) as c:
        for host in ("testserver", "evil.example", "192.168.1.5:8321"):
            assert c.get("/arena/v1/health", headers={"host": host}).status_code == 200


def test_non_json_posts_are_415(client):
    r = client.post(
        "/a2a/echo",
        content=b'{"jsonrpc": "2.0"}',
        headers={"content-type": "text/plain", "A2A-Version": "1.0"},
    )
    assert r.status_code == 415
    assert r.json()["jsonrpc"] == "2.0" and r.json()["error"]["code"] == -32600
    r = client.post("/v1/chat/completions", content=b"{}", headers={"content-type": "text/plain"})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_media_type"
    r = client.post("/arena/v1/agents/echo/reset")  # no content-type at all
    assert r.status_code == 415
    ok = client.post(
        "/a2a/echo",
        content=httpx.Request("POST", "/", json=_rpc_body("hi")).content,
        headers={"content-type": "application/json; charset=utf-8", "A2A-Version": "1.0"},
    )
    assert ok.status_code == 200


def test_native_a2a_error_is_forwarded_with_502(client):
    r = send(client, "failing-native", "x")
    assert r.status_code == 502
    assert r.json() == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "boom"}}


def test_native_a2a_non_object_body_is_unextractable(client):
    r = send(client, "odd-native", "x")
    assert r.status_code == 502 and r.json()["error"]["code"] == -32006


def test_reset_failure_still_drops_contexts_and_invalidates():
    def boom(m, d):
        raise RuntimeError("compose exploded")

    registry = FakeRegistry([ECHO])
    app = create_app(
        registry,
        transport=httpx.ASGITransport(app=FAKE_AGENT),
        reset_agent=boom,
        allowed_hosts=TEST_HOSTS,
    )
    with TestClient(app) as c:
        send(c, "echo", "hi", context_id="c-1")
        assert len(app.state.contexts) == 1
        r = c.post("/arena/v1/agents/echo/reset", json={})
        assert r.status_code == 500
        assert r.json()["error"] == {"code": "reset_failed", "message": "compose exploded"}
        assert len(app.state.contexts) == 0
        assert registry.invalidated == 1


def test_registry_discards_a_refresh_that_raced_an_invalidate(monkeypatch):
    calls = []
    registry = gateway.AgentRegistry(ttl=100.0, clock=lambda: 0.0)

    def list_running():
        calls.append(1)
        if len(calls) == 1:
            registry.invalidate()  # a reset lands while docker is being listed
        return [RunningAgent("echo", "0.1.0", "image", 9999)]

    monkeypatch.setattr(gateway.runtime, "list_running", list_running)
    monkeypatch.setattr(
        gateway.catalog, "installed", lambda agent_id, version=None: (ECHO, ARENA_FIXTURES)
    )
    assert registry.get("echo") is None  # stale result discarded, not stamped
    assert registry.get("echo").manifest.id == "echo"
    assert len(calls) == 2
    registry.get("echo")
    assert len(calls) == 2  # the second refresh was kept and is fresh


def test_registry_refreshes_once_under_concurrency(monkeypatch):
    import threading

    calls = []
    gate = threading.Event()

    def list_running():
        calls.append(1)
        gate.wait(1)
        return [RunningAgent("echo", "0.1.0", "image", 9999)]

    monkeypatch.setattr(gateway.runtime, "list_running", list_running)
    monkeypatch.setattr(
        gateway.catalog, "installed", lambda agent_id, version=None: (ECHO, ARENA_FIXTURES)
    )
    registry = gateway.AgentRegistry(ttl=100.0)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(registry.get("echo"))) for _ in range(5)
    ]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert all(r is not None for r in results)
