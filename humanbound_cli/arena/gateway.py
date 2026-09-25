# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena gateway: every running agent as an A2A v1.0 server, plus an
OpenAI-compatible façade and management routes. Binds to loopback by default."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import __version__
from . import a2a, catalog, openai_compat, runtime
from .adapters.a2a_passthrough import A2APassthrough
from .adapters.http import AgentError, AgentReply, HttpAdapter
from .contexts import ContextStore
from .manifest import ArenaManifest


@dataclass(frozen=True)
class RegistryEntry:
    agent: runtime.RunningAgent
    manifest: ArenaManifest
    agent_dir: Path


class AgentRegistry:
    """Running agents joined with their cached manifests, refreshed from Docker at most
    every `ttl` seconds."""

    def __init__(self, ttl: float = 2.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._entries: dict[str, RegistryEntry] = {}
        self._loaded_at: float | None = None

    def _refresh(self) -> None:
        entries = {}
        for agent in runtime.list_running():
            found = catalog.installed(agent.id, agent.version)
            if found is None or agent.host_port is None:
                continue
            entries[agent.id] = RegistryEntry(agent, found[0], found[1])
        self._entries = entries
        self._loaded_at = self._clock()

    def _ensure_fresh(self) -> None:
        if self._loaded_at is None or self._clock() - self._loaded_at > self._ttl:
            self._refresh()

    def get(self, agent_id: str) -> RegistryEntry | None:
        self._ensure_fresh()
        return self._entries.get(agent_id)

    def all(self) -> list[RegistryEntry]:
        self._ensure_fresh()
        return list(self._entries.values())

    def invalidate(self) -> None:
        self._loaded_at = None


def _http_error(e: AgentError) -> JSONResponse:
    status = a2a.from_agent_error(e).http_status
    return JSONResponse({"error": {"code": e.code, "message": str(e)}}, status_code=status)


def _metadata(entry: RegistryEntry, reply: AgentReply) -> dict:
    meta: dict = {
        "latency_ms": reply.latency_ms,
        "agent": entry.manifest.id,
        "version": entry.manifest.version,
    }
    if reply.tool_calls is not None:
        meta["tool_calls"] = reply.tool_calls
    return meta


def _raw_id(body: Any) -> Any:
    """The request id to echo in an error, or None when it is absent or invalid."""
    rpc_id = body.get("id") if isinstance(body, dict) else None
    if isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, int, float)):
        return None
    return rpc_id


def create_app(
    registry=None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    reset_agent: Callable[[ArenaManifest, Path], object] = runtime.reset,
) -> Starlette:
    registry = registry or AgentRegistry()
    contexts = ContextStore()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with httpx.AsyncClient(transport=transport) as client:
            app.state.http = client
            yield

    async def lookup(agent_id: str) -> RegistryEntry:
        entry = await run_in_threadpool(registry.get, agent_id)
        if entry is None:
            raise AgentError(
                "agent_not_running", f"{agent_id} is not running → hb arena run {agent_id}"
            )
        return entry

    def http_adapter(request: Request, entry: RegistryEntry) -> HttpAdapter:
        return HttpAdapter(
            entry.manifest.integration,
            entry.agent.base_url,
            entry.manifest.runtime.timeout_s,
            request.app.state.http,
        )

    def passthrough(request: Request, entry: RegistryEntry) -> A2APassthrough:
        return A2APassthrough(
            entry.agent.base_url,
            entry.manifest.integration.path,
            entry.manifest.runtime.timeout_s,
            request.app.state.http,
        )

    async def converse(request: Request, entry: RegistryEntry, context_id, prompt: str):
        cid, ctx = contexts.get_or_create(entry.manifest.id, context_id)
        adapter = http_adapter(request, entry)
        async with ctx.lock:
            if not ctx.started:
                ctx.state = await adapter.start_conversation()
                ctx.started = True
            reply = await adapter.send(ctx.state, prompt, ctx.history)
            if entry.manifest.integration.history == "gateway":
                ctx.history.append({"role": "user", "content": prompt})
                ctx.history.append({"role": "assistant", "content": reply.text})
        return cid, reply

    # ── management ──

    async def health(request: Request):
        return JSONResponse({"status": "ok", "version": __version__})

    async def list_agents(request: Request):
        base = str(request.base_url).rstrip("/")
        entries = await run_in_threadpool(registry.all)
        return JSONResponse(
            [
                {
                    "id": e.manifest.id,
                    "version": e.manifest.version,
                    "status": "running",
                    "a2a_url": f"{base}/a2a/{e.manifest.id}",
                    "native_url": e.agent.base_url,
                }
                for e in entries
            ]
        )

    async def reset(request: Request):
        agent_id = request.path_params["agent_id"]
        try:
            entry = await lookup(agent_id)
        except AgentError as e:
            return _http_error(e)
        try:
            await run_in_threadpool(reset_agent, entry.manifest, entry.agent_dir)
        except (runtime.DockerError, runtime.HealthTimeout) as e:
            return JSONResponse(
                {"error": {"code": "reset_failed", "message": str(e)}}, status_code=500
            )
        contexts.drop_agent(agent_id)
        registry.invalidate()
        return JSONResponse({"id": agent_id, "status": "reset"})

    # ── A2A ──

    async def agent_card(request: Request):
        agent_id = request.path_params["agent_id"]
        try:
            entry = await lookup(agent_id)
        except AgentError as e:
            return _http_error(e)
        url = f"{str(request.base_url).rstrip('/')}/a2a/{agent_id}"
        return JSONResponse(a2a.agent_card(entry.manifest, url))

    async def rpc(request: Request):
        agent_id = request.path_params["agent_id"]
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                a2a.error_body(None, a2a.RpcError(a2a.PARSE_ERROR, "Invalid JSON payload"))
            )
        rpc_id = _raw_id(body)
        try:
            version = request.headers.get("A2A-Version")
            a2a.check_version(version)
            rpc_id, method, params = a2a.parse_envelope(body)
            entry = await lookup(agent_id)
            if entry.manifest.integration.type == "a2a":
                started = time.monotonic()
                status, data = await passthrough(request, entry).forward(body, version)
                result = data.get("result") if isinstance(data, dict) else None
                message = result.get("message") if isinstance(result, dict) else None
                if isinstance(message, dict):
                    meta = message.get("metadata")
                    if not isinstance(meta, dict):
                        meta = message["metadata"] = {}
                    hb = meta.get("humanbound")
                    if not isinstance(hb, dict):
                        hb = meta["humanbound"] = {}
                    hb["latency_ms"] = int((time.monotonic() - started) * 1000)
                return JSONResponse(data, status_code=status)
            if method == "GetTask":
                raise a2a.RpcError(
                    a2a.TASK_NOT_FOUND, "Task not found: this agent answers with direct messages"
                )
            if method != "SendMessage":
                raise a2a.RpcError(a2a.METHOD_NOT_FOUND, "Method not found")
            incoming = a2a.parse_message(params)
            cid, reply = await converse(request, entry, incoming.context_id, incoming.text)
            return JSONResponse(
                a2a.message_result(rpc_id, reply.text, cid, _metadata(entry, reply))
            )
        except a2a.RpcError as e:
            return JSONResponse(a2a.error_body(rpc_id, e), status_code=e.http_status)
        except AgentError as e:
            err = a2a.from_agent_error(e)
            return JSONResponse(a2a.error_body(rpc_id, err), status_code=err.http_status)

    # ── OpenAI façade ──

    async def chat_completions(request: Request):
        try:
            agent_id, prompt, history = openai_compat.parse_chat_request(await request.json())
        except ValueError as e:
            return JSONResponse(
                {"error": {"code": "invalid_request", "message": str(e)}}, status_code=400
            )
        try:
            entry = await lookup(agent_id)
            if entry.manifest.integration.type == "a2a":
                started = time.monotonic()
                _, data = await passthrough(request, entry).forward(
                    a2a.send_message_body(prompt), a2a.A2A_VERSION
                )
                reply = AgentReply(
                    a2a.reply_text(data), latency_ms=int((time.monotonic() - started) * 1000)
                )
            else:
                adapter = http_adapter(request, entry)
                state = await adapter.start_conversation()
                reply = await adapter.send(state, prompt, history)
        except AgentError as e:
            return _http_error(e)
        return JSONResponse(
            openai_compat.chat_response(agent_id, reply.text, _metadata(entry, reply))
        )

    routes = [
        Route("/arena/v1/health", health, methods=["GET"]),
        Route("/arena/v1/agents", list_agents, methods=["GET"]),
        Route("/arena/v1/agents/{agent_id}/reset", reset, methods=["POST"]),
        Route("/a2a/{agent_id}/.well-known/agent-card.json", agent_card, methods=["GET"]),
        Route("/a2a/{agent_id}", rpc, methods=["POST"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.contexts = contexts
    return app
