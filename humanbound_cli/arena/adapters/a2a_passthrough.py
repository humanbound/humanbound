# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Forward JSON-RPC unchanged to agents that already speak A2A (integration.type: a2a)."""

from __future__ import annotations

import httpx

from .http import AgentError, map_httpx_error


class A2APassthrough:
    def __init__(self, base_url: str, path: str, timeout_s: float, client: httpx.AsyncClient):
        self.url = base_url.rstrip("/") + path
        self.timeout_s = timeout_s
        self.client = client

    async def forward(self, body: dict, a2a_version: str | None) -> tuple[int, dict]:
        if not a2a_version:
            from ..a2a import A2A_VERSION  # lazy: a2a.py imports adapters.http

            a2a_version = A2A_VERSION
        headers = {"A2A-Version": a2a_version}
        try:
            resp = await self.client.post(
                self.url, json=body, headers=headers, timeout=self.timeout_s
            )
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise map_httpx_error(e, self.timeout_s) from None
        if not resp.is_success:
            raise AgentError(
                "agent_error", f"the agent returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.status_code, resp.json()
        except ValueError:
            raise AgentError(
                "unextractable_response", f"the agent returned non-JSON: {resp.text[:300]}"
            ) from None
