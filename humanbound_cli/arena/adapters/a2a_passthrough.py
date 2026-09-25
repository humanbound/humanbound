# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Forward JSON-RPC unchanged to agents that already speak A2A (integration.type: a2a)."""

from __future__ import annotations

import httpx

from .http import AgentError


class A2APassthrough:
    def __init__(self, base_url: str, path: str, timeout_s: float, client: httpx.AsyncClient):
        self.url = base_url.rstrip("/") + path
        self.timeout_s = timeout_s
        self.client = client

    async def forward(self, body: dict, a2a_version: str | None) -> tuple[int, dict]:
        headers = {"A2A-Version": a2a_version} if a2a_version else {}
        try:
            resp = await self.client.post(
                self.url, json=body, headers=headers, timeout=self.timeout_s
            )
        except httpx.TimeoutException:
            raise AgentError(
                "agent_timeout", f"the agent did not answer within {self.timeout_s}s"
            ) from None
        except httpx.HTTPError as e:
            raise AgentError("agent_not_running", f"cannot reach the agent: {e}") from None
        try:
            return resp.status_code, resp.json()
        except ValueError:
            raise AgentError(
                "unextractable_response", f"the agent returned non-JSON: {resp.text[:300]}"
            ) from None
