# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A2A v1.0 (JSON-RPC binding) helpers: Agent Card, request parsing, results, errors.

Field names follow the proto3 JSON form of the normative spec/a2a.proto (lf.a2a.v1).
The gateway always answers SendMessage with a direct Message; it never creates Tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .adapters.http import AgentError
from .manifest import ArenaManifest

A2A_VERSION = "1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
CONTENT_TYPE_NOT_SUPPORTED = -32005
INVALID_AGENT_RESPONSE = -32006
VERSION_NOT_SUPPORTED = -32009

ERROR_DOMAIN = "arena.humanbound.ai"

# AgentError.code -> (JSON-RPC code, HTTP status, ErrorInfo reason).
# Agent failures use non-200 HTTP so clients (and hb's Bot) fail the turn loudly
# instead of reading the error text as the agent's reply.
_AGENT_ERRORS = {
    "agent_not_running": (INTERNAL_ERROR, 404, "AGENT_NOT_RUNNING"),
    "agent_error": (INTERNAL_ERROR, 502, "AGENT_ERROR"),
    "agent_timeout": (INTERNAL_ERROR, 504, "AGENT_TIMEOUT"),
    "unextractable_response": (INVALID_AGENT_RESPONSE, 502, "UNEXTRACTABLE_RESPONSE"),
}


class RpcError(Exception):
    def __init__(
        self, code: int, message: str, *, http_status: int = 200, reason: str | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.reason = reason


@dataclass
class IncomingMessage:
    text: str
    context_id: str | None
    message_id: str


def agent_card(m: ArenaManifest, url: str) -> dict:
    return {
        "name": m.name,
        "description": (
            f"{m.description} Intentionally vulnerable test agent served by Humanbound Arena. "
            "Do not deploy."
        ),
        "supportedInterfaces": [
            {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": A2A_VERSION}
        ],
        "provider": {"organization": "Humanbound Arena", "url": "https://humanbound.ai"},
        "version": m.version,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.agent.scope.business.strip(),
                "tags": list(m.tags),
            }
        ],
    }


def check_version(header: str | None) -> None:
    """Accept a missing header (lenient) or any 1.0.x; reject other versions."""
    if not header:
        return
    if ".".join(header.strip().split(".")[:2]) != A2A_VERSION:
        raise RpcError(
            VERSION_NOT_SUPPORTED,
            f"A2A version {header} is not supported; this gateway speaks {A2A_VERSION}",
        )


def parse_envelope(body: Any) -> tuple[Any, str, Any]:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
        raise RpcError(INVALID_REQUEST, "Request payload validation error")
    return body.get("id"), body["method"], body.get("params")


def parse_message(params: Any) -> IncomingMessage:
    msg = params.get("message") if isinstance(params, dict) else None
    if not isinstance(msg, dict):
        raise RpcError(INVALID_PARAMS, "params.message is required")
    if msg.get("role") != "ROLE_USER":
        raise RpcError(INVALID_PARAMS, "params.message.role must be ROLE_USER")
    parts = msg.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RpcError(INVALID_PARAMS, "params.message.parts must be a non-empty list")
    texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if len(texts) != len(parts):
        raise RpcError(CONTENT_TYPE_NOT_SUPPORTED, "only text parts are supported")
    return IncomingMessage(
        text="\n".join(texts),
        context_id=msg.get("contextId") or None,
        message_id=msg.get("messageId") or uuid.uuid4().hex,
    )


def message_result(rpc_id: Any, text: str, context_id: str, metadata: dict) -> dict:
    # `parts` precedes `metadata` on purpose: hb's Bot takes the first `text` it finds.
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "message": {
                "role": "ROLE_AGENT",
                "messageId": uuid.uuid4().hex,
                "contextId": context_id,
                "parts": [{"text": text}],
                "metadata": {"humanbound": metadata},
            }
        },
    }


def error_body(rpc_id: Any, err: RpcError) -> dict:
    error: dict = {"code": err.code, "message": err.message}
    if err.reason:
        error["data"] = [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": err.reason,
                "domain": ERROR_DOMAIN,
            }
        ]
    return {"jsonrpc": "2.0", "id": rpc_id, "error": error}


def from_agent_error(e: AgentError) -> RpcError:
    code, status, reason = _AGENT_ERRORS.get(e.code, (INTERNAL_ERROR, 502, "AGENT_ERROR"))
    return RpcError(code, str(e), http_status=status, reason=reason)


def reply_text(result: Any) -> str:
    """Text of a SendMessage result, whether the agent answered with a Message or a Task."""
    if not isinstance(result, dict):
        return ""
    task = result.get("task")
    if isinstance(task, dict):
        parts = [p for art in task.get("artifacts") or [] for p in art.get("parts") or []]
        if not parts:
            parts = ((task.get("status") or {}).get("message") or {}).get("parts") or []
    else:
        parts = (result.get("message") or {}).get("parts") or []
    return "\n".join(
        p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
    )


def send_message_body(text: str, context_id: str | None = None) -> dict:
    message: dict = {"role": "ROLE_USER", "messageId": uuid.uuid4().hex, "parts": [{"text": text}]}
    if context_id:
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "SendMessage",
        "params": {"message": message},
    }
