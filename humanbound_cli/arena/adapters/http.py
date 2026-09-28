# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""HTTP adapter: talks to an `integration.type: http` agent using the arena.yaml bot-config.

Placeholders reuse the hb bot-config vocabulary: `$PROMPT`, `$CONVERSATION` (the OpenAI-style
history), and `$<key>` for a key returned by `thread_init`. A leading backslash escapes a
literal `$`.
"""

from __future__ import annotations

import copy
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from ..manifest import Integration

__all__ = [
    "AgentError",
    "AgentReply",
    "HttpAdapter",
    "extract_path",
    "fill_endpoint",
    "map_httpx_error",
    "post_once_more_if_dropped",
    "substitute",
]

_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class AgentError(Exception):
    """An agent call failed. `.code` is one of the AgentError codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AgentReply:
    text: str
    tool_calls: Any = None
    latency_ms: int = 0


def substitute(item: Any, values: dict, prompt: str, conversation: list) -> Any:
    """Recursively resolve bot-config placeholders in `item`."""
    if isinstance(item, str):
        if item.startswith("\\"):
            return item[1:]
        if item.upper() == "$PROMPT":
            return prompt
        if item.upper() == "$CONVERSATION":
            return copy.deepcopy(conversation)
        if item.startswith("$"):
            return values.get(item[1:])
        return item
    if isinstance(item, dict):
        return {k: substitute(v, values, prompt, conversation) for k, v in item.items()}
    if isinstance(item, list):
        return [substitute(v, values, prompt, conversation) for v in item]
    return item


def fill_endpoint(endpoint: str, values: dict, *, encode: bool = True) -> str:
    """Replace `$key` (whole identifiers only) with `values[key]`. Unknown keys are left as-is."""

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            return m.group(0)
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return m.group(0)
        text = str(value)
        return urllib.parse.quote(text, safe="") if encode else text

    return _PLACEHOLDER_RE.sub(_replace, endpoint)


def extract_path(obj: Any, dotted: str) -> Any:
    """Walk a dotted path through dicts and lists. Raises KeyError on any miss."""
    current = obj
    for part in dotted.split("."):
        if isinstance(current, list):
            if part.isascii() and part.isdigit():
                index = int(part)
                if index >= len(current):
                    raise KeyError(dotted)
                current = current[index]
            else:
                raise KeyError(dotted)
        elif isinstance(current, dict):
            if part not in current:
                raise KeyError(dotted)
            current = current[part]
        else:
            raise KeyError(dotted)
    return current


def map_httpx_error(e: Exception, timeout_s: float) -> AgentError:
    if isinstance(e, httpx.TimeoutException):
        return AgentError("agent_timeout", f"did not answer within {timeout_s}s")
    if isinstance(e, httpx.ConnectError):
        return AgentError("agent_not_running", str(e))
    return AgentError("agent_error", str(e))


async def post_once_more_if_dropped(
    client: httpx.AsyncClient, url: str, **kwargs
) -> httpx.Response:
    """POST, retrying once if the agent closed the connection without answering.

    `RemoteProtocolError` from `post()` means no response reached us (typically a server
    closing a connection just as it was reused), so the request is sent again once.
    Timeouts, connect errors and HTTP error statuses are never retried.
    """
    try:
        return await client.post(url, **kwargs)
    except httpx.RemoteProtocolError:
        return await client.post(url, **kwargs)


class HttpAdapter:
    def __init__(
        self, integration: Integration, base_url: str, timeout_s: float, client: httpx.AsyncClient
    ) -> None:
        self.integration = integration
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.client = client

    async def _call(
        self,
        call,
        values: dict,
        prompt: str = "",
        conversation: list | None = None,
    ) -> Any:
        conversation = conversation if conversation is not None else []
        url = self.base_url + fill_endpoint(call.endpoint, values, encode=True)
        headers = {k: fill_endpoint(v, values, encode=False) for k, v in call.headers.items()}
        body = substitute(copy.deepcopy(call.payload), values, prompt, conversation)
        try:
            resp = await post_once_more_if_dropped(
                self.client, url, headers=headers, json=body, timeout=self.timeout_s
            )
        except httpx.HTTPError as e:
            raise map_httpx_error(e, self.timeout_s) from e
        if not (200 <= resp.status_code < 300):
            raise AgentError("agent_error", f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise AgentError("unextractable_response", "agent response was not JSON") from e

    async def start_conversation(self) -> dict:
        if self.integration.thread_init is None:
            return {}
        data = await self._call(self.integration.thread_init, {})
        return data if isinstance(data, dict) else {}

    async def send(self, state: dict, prompt: str, history: list) -> AgentReply:
        conversation = history if self.integration.history == "gateway" else []
        start = time.monotonic()
        data = await self._call(
            self.integration.chat_completion, state, prompt=prompt, conversation=conversation
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        response_map = self.integration.response
        try:
            text = extract_path(data, response_map.text)
        except KeyError as e:
            raise AgentError(
                "unextractable_response", f"missing response path '{response_map.text}'"
            ) from e
        if text is None:
            raise AgentError(
                "unextractable_response", f"response path '{response_map.text}' was null"
            )
        if not isinstance(text, str):
            text = json.dumps(text)

        tool_calls = None
        if response_map.tool_calls:
            try:
                tool_calls = extract_path(data, response_map.tool_calls)
            except KeyError:
                tool_calls = None

        return AgentReply(text=text, tool_calls=tool_calls, latency_ms=latency_ms)
