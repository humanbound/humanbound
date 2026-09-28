# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Passthrough to a native `integration.type: a2a` agent's own JSON-RPC endpoint."""

from __future__ import annotations

import httpx

from .http import AgentError, map_httpx_error, post_once_more_if_dropped

__all__ = ["A2APassthrough"]


class A2APassthrough:
    def __init__(
        self, base_url: str, path: str, timeout_s: float, client: httpx.AsyncClient
    ) -> None:
        self.base_url = base_url
        self.path = path
        self.timeout_s = timeout_s
        self.client = client

    async def forward(self, body: dict, a2a_version: str | None) -> tuple[int, dict]:
        version = a2a_version or "1.0"
        url = self.base_url + self.path
        try:
            resp = await post_once_more_if_dropped(
                self.client,
                url,
                json=body,
                headers={"A2A-Version": version},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as e:
            raise map_httpx_error(e, self.timeout_s) from e
        if not (200 <= resp.status_code < 300):
            raise AgentError("agent_error", f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise AgentError("unextractable_response", "agent response was not JSON") from e
        return resp.status_code, data
