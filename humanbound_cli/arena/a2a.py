# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A2A v1.0 JSON-RPC helpers.

The wire format is the proto3 JSON form of the normative `a2a.proto` (`lf.a2a.v1`):
methods SendMessage/GetTask, roles ROLE_USER/ROLE_AGENT, a text part is {"text": ...},
and a SendMessage result is a direct Message or a Task.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from numbers import Number
from typing import Any

from .adapters.http import AgentError
from .manifest import ArenaManifest

__all__ = [
    "A2A_VERSION",
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "TASK_NOT_FOUND",
    "CONTENT_TYPE_NOT_SUPPORTED",
    "INVALID_AGENT_RESPONSE",
    "VERSION_NOT_SUPPORTED",
    "ERROR_DOMAIN",
    "RpcError",
    "IncomingMessage",
    "agent_card",
    "check_version",
    "parse_envelope",
    "parse_message",
    "message_result",
    "error_body",
    "from_agent_error",
    "reply_text",
    "send_message_body",
]

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
# The Agent Card's name for the gateway's bearer token.
TOKEN_SCHEME = "arenaToken"

_AGENT_ERRORS = {
    "agent_not_running": (INTERNAL_ERROR, 404, "AGENT_NOT_RUNNING"),
    "agent_error": (INTERNAL_ERROR, 502, "AGENT_ERROR"),
    "agent_timeout": (INTERNAL_ERROR, 504, "AGENT_TIMEOUT"),
    "unextractable_response": (INVALID_AGENT_RESPONSE, 502, "UNEXTRACTABLE_RESPONSE"),
    "docker_unavailable": (INTERNAL_ERROR, 503, "DOCKER_UNAVAILABLE"),
}


class RpcError(Exception):
    def __init__(
        self, code: int, message: str, *, http_status: int = 200, reason: str | None = None
    ) -> None:
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
    description = (
        f"{m.description} Intentionally vulnerable test agent served by Humanbound Arena. "
        "Do not deploy."
    )
    tags = m.tags or [m.id]
    return {
        "name": m.name,
        "description": description,
        "supportedInterfaces": [
            {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "provider": {"organization": "Humanbound Arena", "url": "https://humanbound.ai"},
        "version": m.version,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "securitySchemes": {
            TOKEN_SCHEME: {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                    "description": "The hb arena gateway token (hb arena endpoint <id> prints it).",
                }
            }
        },
        "securityRequirements": [{"schemes": {TOKEN_SCHEME: {"list": []}}}],
        "skills": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.agent.scope.business.strip(),
                "tags": tags,
            }
        ],
    }


def check_version(header: str | None) -> None:
    if header is None:
        return
    if header == "1.0" or header.startswith("1.0."):
        return
    raise RpcError(
        VERSION_NOT_SUPPORTED,
        f"unsupported A2A-Version '{header}'",
        reason="VERSION_NOT_SUPPORTED",
    )


def parse_envelope(body: Any) -> tuple[Any, str, dict]:
    if not isinstance(body, dict):
        raise RpcError(INVALID_REQUEST, "request body must be a JSON object")
    if body.get("jsonrpc") != "2.0":
        raise RpcError(INVALID_REQUEST, "jsonrpc must be '2.0'")
    method = body.get("method")
    if not isinstance(method, str):
        raise RpcError(INVALID_REQUEST, "method must be a string")
    if "id" not in body:
        raise RpcError(INVALID_REQUEST, "notifications are not supported; include an id")
    rpc_id = body["id"]
    if isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, Number)):
        raise RpcError(INVALID_REQUEST, "id must be a string or a number")
    params = body.get("params") or {}
    return rpc_id, method, params


def parse_message(params: dict) -> IncomingMessage:
    message = params.get("message") if isinstance(params, dict) else None
    if not isinstance(message, dict) or message.get("role") != "ROLE_USER":
        raise RpcError(INVALID_PARAMS, "params.message must have role ROLE_USER")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RpcError(INVALID_PARAMS, "params.message.parts must be a non-empty list")

    texts = []
    for part in parts:
        if not isinstance(part, dict) or "text" not in part:
            raise RpcError(CONTENT_TYPE_NOT_SUPPORTED, "only text parts are supported")
        if not isinstance(part["text"], str):
            raise RpcError(INVALID_PARAMS, "a text part's text must be a string")
        texts.append(part["text"])

    context_id = message.get("contextId")
    if context_id is not None and not isinstance(context_id, str):
        raise RpcError(INVALID_PARAMS, "contextId must be a string")

    message_id = message.get("messageId")
    if message_id is not None and not isinstance(message_id, str):
        raise RpcError(INVALID_PARAMS, "messageId must be a string")
    if not message_id:
        message_id = uuid.uuid4().hex

    return IncomingMessage(text="\n".join(texts), context_id=context_id, message_id=message_id)


def message_result(rpc_id: Any, text: str, context_id: str, metadata: dict) -> dict:
    message: dict[str, Any] = {
        "role": "ROLE_AGENT",
        "messageId": uuid.uuid4().hex,
        "contextId": context_id,
    }
    message["parts"] = [{"text": text}]
    message["metadata"] = {"humanbound": metadata}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {"message": message}}


def error_body(rpc_id: Any, err: RpcError) -> dict:
    body: dict[str, Any] = {"code": err.code, "message": err.message}
    if err.reason:
        body["data"] = [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": err.reason,
                "domain": ERROR_DOMAIN,
            }
        ]
    return body


def from_agent_error(e: Exception) -> RpcError:
    code = getattr(e, "code", None)
    rpc_code, http_status, reason = _AGENT_ERRORS.get(code, _AGENT_ERRORS["agent_error"])
    message = getattr(e, "message", None) or str(e)
    return RpcError(rpc_code, message, http_status=http_status, reason=reason)


def _parts_text(parts: Any) -> str | None:
    if not isinstance(parts, list):
        return None
    texts = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts)


def reply_text(body: dict) -> str:
    if "error" in body:
        err = body["error"]
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else None
        raise AgentError("agent_error", f"agent returned A2A error {code}: {message}")

    result = body.get("result")
    if not isinstance(result, dict):
        raise AgentError("unextractable_response", "A2A response had no result")

    message = result.get("message")
    if isinstance(message, dict):
        text = _parts_text(message.get("parts"))
        if text is not None:
            return text

    task = result.get("task")
    if isinstance(task, dict):
        artifacts = task.get("artifacts")
        if isinstance(artifacts, list):
            texts = []
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    text = _parts_text(artifact.get("parts"))
                    if text is not None:
                        texts.append(text)
            if texts:
                return "\n".join(texts)

        status = task.get("status")
        if isinstance(status, dict):
            status_message = status.get("message")
            if isinstance(status_message, dict):
                text = _parts_text(status_message.get("parts"))
                if text is not None:
                    return text

    raise AgentError("unextractable_response", "could not find text parts in A2A response")


def send_message_body(text: str, context_id: str | None = None) -> dict:
    message: dict[str, Any] = {
        "role": "ROLE_USER",
        "messageId": uuid.uuid4().hex,
        "parts": [{"text": text}],
    }
    if context_id is not None:
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "SendMessage",
        "params": {"message": message},
    }
