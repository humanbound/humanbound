# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena gateway: running agents over A2A v1.0 and an OpenAI chat-completions façade.

Agents are found by joining Docker's running containers with the cached manifests. Only
loopback Host headers are accepted by default, and every POST must be JSON, so a web page
in the user's browser can't drive the gateway (DNS rebinding, simple-request CSRF). Every
route but a minimal health check also needs the owner's access token
(paths.gateway_token()), so other local users and processes can't drive the agents either.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from .. import __version__
from . import a2a, catalog, runtime
from .adapters.a2a_passthrough import A2APassthrough
from .adapters.http import AgentError, AgentReply, HttpAdapter
from .contexts import ContextStore
from .manifest import ArenaManifest, ManifestError
from .openai_compat import chat_response, parse_chat_request
from .paths import LOOPBACK_HOSTS, arena_owner, gateway_token
from .tools import normalize_tool_calls

__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "AgentRegistry",
    "LocalGuardMiddleware",
    "RegistryEntry",
    "create_app",
]

DEFAULT_ALLOWED_HOSTS = list(LOOPBACK_HOSTS)


# ── registry ──


@dataclass(frozen=True)
class RegistryEntry:
    agent: runtime.RunningAgent
    manifest: ArenaManifest
    agent_dir: Path


class AgentRegistry:
    """Running agents with a cached manifest, refreshed at most every `ttl` seconds."""

    def __init__(self, ttl: float = 2.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, RegistryEntry] = {}
        self._fresh_until: float | None = None
        self._generation = 0

    def _is_fresh(self) -> bool:
        return self._fresh_until is not None and self._clock() < self._fresh_until

    def _load(self) -> dict[str, RegistryEntry]:
        entries: dict[str, RegistryEntry] = {}
        for agent in runtime.list_running():
            if agent.host_port is None:
                continue
            try:
                found = catalog.installed(agent.id, agent.version or None)
            except (ManifestError, OSError):
                continue
            if found is None:
                continue
            manifest, agent_dir = found
            entries[agent.id] = RegistryEntry(agent=agent, manifest=manifest, agent_dir=agent_dir)
        return entries

    def _current(self) -> dict[str, RegistryEntry]:
        if self._is_fresh():
            return self._entries
        with self._lock:
            if self._is_fresh():
                return self._entries
            generation = self._generation
            entries = self._load()
            if generation == self._generation:
                self._entries = entries
                self._fresh_until = self._clock() + self.ttl
            return entries

    def get(self, agent_id: str) -> RegistryEntry | None:
        return self._current().get(agent_id)

    def all(self) -> list[RegistryEntry]:
        return list(self._current().values())

    def invalidate(self) -> None:
        # Deliberately lock-free: it must not wait for a slow refresh in progress.
        self._generation += 1
        self._fresh_until = None


# ── local guard ──


def _strip_port(host: str) -> str:
    host = host.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host  # a bare name, or a bare IPv6 literal


HEALTH_PATH = "/arena/v1/health"
TOKEN_HEADER = "x-arena-token"
UNAUTHORIZED = (
    "missing or invalid arena gateway token: send 'Authorization: Bearer <token>' "
    "(hb arena endpoint <id> prints it)"
)


def presented_token(headers: Headers) -> str | None:
    """The token from `Authorization: Bearer <token>` (what OpenAI and A2A clients send)
    or `X-Arena-Token: <token>`."""
    auth = headers.get("authorization", "")
    scheme, _, value = auth.strip().partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    value = headers.get(TOKEN_HEADER, "").strip()
    return value or None


def token_matches(presented: str | None, token: str) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8"))


def _unauthorized(scope) -> JSONResponse:
    headers = {"WWW-Authenticate": 'Bearer realm="hb arena"'}
    if scope["method"] == "POST" and scope["path"].startswith("/a2a/"):
        body = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": a2a.INVALID_REQUEST, "message": UNAUTHORIZED},
        }
        return JSONResponse(body, status_code=401, headers=headers)
    response = _error_response("unauthorized", UNAUTHORIZED, 401)
    response.headers.update(headers)
    return response


class LocalGuardMiddleware:
    """Host allowlist (IPv6-aware), the access token, and JSON-only POSTs, in that order.

    Only `GET /arena/v1/health` is served without the token, and then says only that the
    gateway is up (the route reads `scope["state"]["authenticated"]`)."""

    def __init__(self, app, allowed_hosts: list[str], token: str) -> None:
        self.app = app
        self.allow_any = "*" in allowed_hosts
        self.allowed = {h.lower() for h in allowed_hosts}
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not self.allow_any:
            host = _strip_port(headers.get("host", "")).lower()
            if host not in self.allowed:
                response = PlainTextResponse("Invalid host header", status_code=400)
                await response(scope, receive, send)
                return
        authenticated = token_matches(presented_token(headers), self.token)
        scope.setdefault("state", {})["authenticated"] = authenticated
        public = scope["path"] == HEALTH_PATH and scope["method"] in ("GET", "HEAD")
        if not authenticated and not public:
            await _unauthorized(scope)(scope, receive, send)
            return
        if scope["method"] == "POST":
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                message = "Content-Type must be application/json"
                if scope["path"].startswith("/a2a/"):
                    body = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": a2a.INVALID_REQUEST, "message": message},
                    }
                    response = JSONResponse(body, status_code=415)
                else:
                    response = _error_response("unsupported_media_type", message, 415)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ── helpers ──


def _error_response(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _http_error(e: AgentError) -> JSONResponse:
    return _error_response(e.code, e.message, a2a.from_agent_error(e).http_status)


def _rpc_error(rpc_id: Any, err: a2a.RpcError) -> JSONResponse:
    body = {"jsonrpc": "2.0", "id": rpc_id, "error": a2a.error_body(rpc_id, err)}
    return JSONResponse(body, status_code=err.http_status)


def _valid_rpc_id(body: Any) -> Any:
    rpc_id = body.get("id") if isinstance(body, dict) else None
    if isinstance(rpc_id, str) or (
        isinstance(rpc_id, (int, float)) and not isinstance(rpc_id, bool)
    ):
        return rpc_id
    return None


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


async def lookup(request: Request, agent_id: str) -> RegistryEntry:
    registry = request.app.state.registry
    try:
        entry = await run_in_threadpool(registry.get, agent_id)
    except runtime.DockerError as e:
        raise AgentError("docker_unavailable", f"Docker is not reachable: {e}") from None
    if entry is None:
        raise AgentError("agent_not_running", catalog.not_running_message(agent_id))
    return entry


def _http_adapter(request: Request, entry: RegistryEntry) -> HttpAdapter:
    m = entry.manifest
    return HttpAdapter(
        m.integration, entry.agent.base_url, float(m.runtime.timeout_s), request.app.state.http
    )


def _passthrough(request: Request, entry: RegistryEntry) -> A2APassthrough:
    m = entry.manifest
    return A2APassthrough(
        entry.agent.base_url,
        m.integration.path,
        float(m.runtime.timeout_s),
        request.app.state.http,
    )


async def converse(
    request: Request, entry: RegistryEntry, context_id: str | None, prompt: str
) -> tuple[str, AgentReply]:
    """One turn in a gateway-held conversation (thread_init once, then send)."""
    integration = entry.manifest.integration
    adapter = _http_adapter(request, entry)
    cid, ctx = request.app.state.contexts.get_or_create(entry.manifest.id, context_id)
    async with ctx.lock:
        if not ctx.started:
            ctx.state = await adapter.start_conversation()
            ctx.started = True
        reply = await adapter.send(ctx.state, prompt, ctx.history)
        if integration.history == "gateway":
            ctx.history.append({"role": "user", "content": prompt})
            ctx.history.append({"role": "assistant", "content": reply.text})
    return cid, reply


def _metadata(entry: RegistryEntry, latency_ms: int, tool_calls: Any = None) -> dict:
    meta: dict[str, Any] = {
        "latency_ms": latency_ms,
        "agent": entry.manifest.id,
        "version": entry.manifest.version,
    }
    if tool_calls is not None:
        meta["tool_calls"] = normalize_tool_calls(tool_calls)
        meta["tool_calls_raw"] = tool_calls
    return meta


def _upstream_context_id(data: dict) -> str | None:
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("message", "task"):
        obj = result.get(key)
        if isinstance(obj, dict) and isinstance(obj.get("contextId"), str) and obj["contextId"]:
            return obj["contextId"]
    return None


def _request_context_id(params: Any) -> str | None:
    message = params.get("message") if isinstance(params, dict) else None
    context_id = message.get("contextId") if isinstance(message, dict) else None
    return context_id if isinstance(context_id, str) and context_id else None


# ── routes ──


async def health(request: Request) -> JSONResponse:
    if not getattr(request.state, "authenticated", False):
        return JSONResponse({"status": "ok"})
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "pid": os.getpid(),
            "owner": request.app.state.owner,
        }
    )


async def list_agents(request: Request) -> JSONResponse:
    try:
        entries = await run_in_threadpool(request.app.state.registry.all)
    except runtime.DockerError as e:
        return _error_response("docker_unavailable", f"Docker is not reachable: {e}", 503)
    base = _base_url(request)
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


async def reset_agent_route(request: Request) -> JSONResponse:
    agent_id = request.path_params["id"]
    try:
        entry = await lookup(request, agent_id)
    except AgentError as e:
        return _http_error(e)
    try:
        await run_in_threadpool(request.app.state.reset_agent, entry.manifest, entry.agent_dir)
    except Exception as e:  # noqa: BLE001 - any failure is reported, never a 500 traceback
        return _error_response("reset_failed", f"could not reset {agent_id}: {e}", 500)
    finally:
        request.app.state.contexts.drop_agent(agent_id)
        request.app.state.registry.invalidate()
    return JSONResponse({"id": agent_id, "status": "reset"})


async def forget_agent_route(request: Request) -> JSONResponse:
    """Drop an agent's conversations and cached lookup (after `hb arena run` restarts it)."""
    agent_id = request.path_params["id"]
    try:
        await request.json()
    except ValueError:
        return _error_response("invalid_request", "request body is not valid JSON", 400)
    request.app.state.contexts.drop_agent(agent_id)
    request.app.state.registry.invalidate()
    return JSONResponse({"id": agent_id, "status": "forgotten"})


async def agent_card(request: Request) -> JSONResponse:
    agent_id = request.path_params["id"]
    try:
        entry = await lookup(request, agent_id)
    except AgentError as e:
        return _http_error(e)
    return JSONResponse(a2a.agent_card(entry.manifest, f"{_base_url(request)}/a2a/{agent_id}"))


async def _native_rpc(
    request: Request, entry: RegistryEntry, rpc_id: Any, method: str, body: dict, params: Any
) -> JSONResponse:
    if method not in ("SendMessage", "GetTask"):
        raise a2a.RpcError(a2a.METHOD_NOT_FOUND, f"method '{method}' not found")
    start = time.monotonic()
    _, data = await _passthrough(request, entry).forward(body, request.headers.get("a2a-version"))
    latency_ms = int((time.monotonic() - start) * 1000)
    if not isinstance(data, dict):
        raise AgentError("unextractable_response", "A2A response was not a JSON object")
    if "error" in data:
        return JSONResponse(data, status_code=502)
    if method == "GetTask":
        return JSONResponse(data)
    text = a2a.reply_text(data)
    cid = _upstream_context_id(data) or _request_context_id(params) or uuid.uuid4().hex
    return JSONResponse(a2a.message_result(rpc_id, text, cid, _metadata(entry, latency_ms)))


async def a2a_rpc(request: Request) -> JSONResponse:
    agent_id = request.path_params["id"]
    try:
        body = await request.json()
    except ValueError:
        return _rpc_error(None, a2a.RpcError(a2a.PARSE_ERROR, "invalid JSON"))
    rpc_id = _valid_rpc_id(body)
    try:
        a2a.check_version(request.headers.get("a2a-version"))
        rpc_id, method, params = a2a.parse_envelope(body)
        entry = await lookup(request, agent_id)
        if entry.manifest.integration.type == "a2a":
            return await _native_rpc(request, entry, rpc_id, method, body, params)
        if method == "GetTask":
            raise a2a.RpcError(a2a.TASK_NOT_FOUND, "task not found: this gateway creates no tasks")
        if method != "SendMessage":
            raise a2a.RpcError(a2a.METHOD_NOT_FOUND, f"method '{method}' not found")
        incoming = a2a.parse_message(params)
        cid, reply = await converse(request, entry, incoming.context_id, incoming.text)
        metadata = _metadata(entry, reply.latency_ms, reply.tool_calls)
        return JSONResponse(a2a.message_result(rpc_id, reply.text, cid, metadata))
    except a2a.RpcError as e:
        return _rpc_error(rpc_id, e)
    except AgentError as e:
        return _rpc_error(rpc_id, a2a.from_agent_error(e))


async def chat_completions(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _error_response("invalid_request", "request body is not valid JSON", 400)
    try:
        agent_id, prompt, history = parse_chat_request(body)
    except ValueError as e:
        return _error_response("invalid_request", str(e), 400)
    try:
        entry = await lookup(request, agent_id)
        if entry.manifest.integration.type == "a2a":
            start = time.monotonic()
            _, data = await _passthrough(request, entry).forward(
                a2a.send_message_body(prompt), "1.0"
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if not isinstance(data, dict):
                raise AgentError("unextractable_response", "A2A response was not a JSON object")
            text = a2a.reply_text(data)
            metadata = _metadata(entry, latency_ms)
        else:
            adapter = _http_adapter(request, entry)
            state = await adapter.start_conversation()
            reply = await adapter.send(state, prompt, history)
            text = reply.text
            metadata = _metadata(entry, reply.latency_ms, reply.tool_calls)
    except AgentError as e:
        return _http_error(e)
    return JSONResponse(chat_response(agent_id, text, metadata))


# ── app ──


def _write_pidfile(pidfile: Path) -> None:
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pidfile(pidfile: Path) -> None:
    try:
        if pidfile.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pidfile.unlink(missing_ok=True)
    except OSError:
        pass


def create_app(
    registry: AgentRegistry | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    reset_agent: Callable[[ArenaManifest, Path], Any] = runtime.reset,
    allowed_hosts: list[str] | None = None,
    pidfile: Path | None = None,
    token: str | None = None,
) -> Starlette:
    """The gateway app. `token` defaults to this owner's (created on first need)."""
    hosts = list(allowed_hosts) if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS
    token = token or gateway_token()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # Agents are on 127.0.0.1: never route them through a proxy from the environment.
        # No kept-alive connections: an agent's server may close an idle connection just as
        # it is reused, and the request then fails without an answer.
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as client:
            app.state.http = client
            if pidfile is not None:
                _write_pidfile(Path(pidfile))
            try:
                yield
            finally:
                if pidfile is not None:
                    _remove_pidfile(Path(pidfile))

    app = Starlette(
        routes=[
            Route(HEALTH_PATH, health, methods=["GET"]),
            Route("/arena/v1/agents", list_agents, methods=["GET"]),
            Route("/arena/v1/agents/{id}/reset", reset_agent_route, methods=["POST"]),
            Route("/arena/v1/agents/{id}/forget", forget_agent_route, methods=["POST"]),
            Route("/a2a/{id}/.well-known/agent-card.json", agent_card, methods=["GET"]),
            Route("/a2a/{id}", a2a_rpc, methods=["POST"]),
            Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        ],
        middleware=[Middleware(LocalGuardMiddleware, allowed_hosts=hosts, token=token)],
        lifespan=lifespan,
    )
    app.state.registry = registry if registry is not None else AgentRegistry()
    app.state.contexts = ContextStore()
    app.state.reset_agent = reset_agent
    # Who this gateway serves: `hb` refuses a gateway of another owner (HOME) on its port.
    app.state.owner = arena_owner()
    return app
