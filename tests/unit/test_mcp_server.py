# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for MCP server API-key tools: alignment with the client's scope contract."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp")  # MCP SDK ships in the [mcp] extra

from humanbound_cli import mcp_server


@pytest.fixture
def client(monkeypatch):
    c = MagicMock()
    monkeypatch.setattr(mcp_server, "_client", c)
    return c


class TestApiKeyTools:
    """The client renamed scopes→scope (default read); the MCP tools must match."""

    def test_create_defaults_to_read_scope(self, client):
        client.create_api_key.return_value = {"id": "k1"}
        mcp_server.hb_create_api_key("ci key")
        client.create_api_key.assert_called_once_with("ci key", scope="read")

    def test_create_passes_explicit_scope(self, client):
        client.create_api_key.return_value = {"id": "k1"}
        mcp_server.hb_create_api_key("ci key", scope="admin")
        client.create_api_key.assert_called_once_with("ci key", scope="admin")

    def test_update_sends_singular_scope_field(self, client):
        client.update_api_key.return_value = {"id": "k1"}
        mcp_server.hb_update_api_key("key-1", scope="admin")
        client.update_api_key.assert_called_once_with("key-1", {"scope": "admin"})
