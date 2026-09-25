# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Talk to an agent's native HTTP API, as described by arena.yaml `integration`.

Placeholders follow the hb bot-config vocabulary: $PROMPT, $CONVERSATION (OpenAI-style
history), $<key returned by thread_init>, and a leading backslash escapes a literal "$".
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..manifest import HttpCall, Integration


class AgentError(RuntimeError):
    """The agent failed. `code` is one of: agent_not_running, agent_error,
    agent_timeout, unextractable_response."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class AgentReply:
    text: str
    tool_calls: Any = None
    latency_ms: int = 0


def substitute(item: Any, values: dict, prompt: str, conversation: list[dict]) -> Any:
    if isinstance(item, dict):
        return {k: substitute(v, values, prompt, conversation) for k, v in item.items()}
    if isinstance(item, list):
        return [substitute(v, values, prompt, conversation) for v in item]
    if isinstance(item, str):
        if item.lower() == "$prompt":
            return prompt
        if item.lower() == "$conversation":
            return list(conversation)
        if item.startswith("$") and len(item) > 1:
            return values.get(item[1:])
        if item.startswith("\\"):
            return item[1:]
    return item


def fill_endpoint(endpoint: str, values: dict) -> str:
    for key, value in values.items():
        if isinstance(value, (str, int, float)):
            endpoint = endpoint.replace(f"${key}", str(value))
    return endpoint


def extract_path(obj: Any, dotted: str) -> Any:
    current = obj
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise KeyError(dotted)
    return current


class HttpAdapter:
    def __init__(
        self, integration: Integration, base_url: str, timeout_s: float, client: httpx.AsyncClient
    ):
        self.integration = integration
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.client = client

    async def _call(
        self, call: HttpCall, values: dict, prompt: str = "", conversation: list[dict] = ()
    ) -> Any:
        url = self.base_url + fill_endpoint(call.endpoint, values)
        headers = {k: fill_endpoint(v, values) for k, v in call.headers.items()}
        body = substitute(copy.deepcopy(call.payload), values, prompt, list(conversation))
        try:
            resp = await self.client.post(url, json=body, headers=headers, timeout=self.timeout_s)
        except httpx.TimeoutException:
            raise AgentError(
                "agent_timeout", f"the agent did not answer within {self.timeout_s}s"
            ) from None
        except httpx.HTTPError as e:
            raise AgentError("agent_not_running", f"cannot reach the agent: {e}") from None
        if not resp.is_success:
            raise AgentError(
                "agent_error", f"the agent returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError:
            raise AgentError(
                "unextractable_response", f"the agent returned non-JSON: {resp.text[:300]}"
            ) from None

    async def start_conversation(self) -> dict:
        """Run thread_init once per conversation; its JSON keys feed later placeholders."""
        if self.integration.thread_init is None:
            return {}
        data = await self._call(self.integration.thread_init, {})
        return data if isinstance(data, dict) else {}

    async def send(self, state: dict, prompt: str, history: list[dict]) -> AgentReply:
        conversation = history if self.integration.history == "gateway" else []
        started = time.monotonic()
        data = await self._call(self.integration.chat_completion, state, prompt, conversation)
        latency_ms = int((time.monotonic() - started) * 1000)
        mapping = self.integration.response
        try:
            text = extract_path(data, mapping.text)
        except KeyError:
            raise AgentError(
                "unextractable_response",
                f"reply path '{mapping.text}' not found in the agent response: {str(data)[:300]}",
            ) from None
        tool_calls = None
        if mapping.tool_calls:
            try:
                tool_calls = extract_path(data, mapping.tool_calls)
            except KeyError:
                tool_calls = None
        if not isinstance(text, str):
            text = json.dumps(text)
        return AgentReply(text, tool_calls, latency_ms)
