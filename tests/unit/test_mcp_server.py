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


class TestGetAssessment:
    """hb_get_assessment — the poll target hb_create_assessment's docstring points to."""

    def test_delegates_to_client(self, client):
        import json

        client.project_id = "proj-1"
        client.get_assessment.return_value = {"id": "asmnt-1", "status": "completed"}

        result = mcp_server.hb_get_assessment("asmnt-1")

        data = json.loads(result)
        assert data["status"] == "completed"
        client.get_assessment.assert_called_once_with("proj-1", "asmnt-1")

    def test_requires_project(self, client):
        import json

        client.project_id = None
        result = mcp_server.hb_get_assessment("asmnt-1")
        data = json.loads(result)
        assert data["error"] is True


class TestStructuredErrors:
    """Any exception returns the {"error": ...} envelope, never a raw traceback (#68)."""

    def test_non_humanbound_error_returns_envelope(self, client):
        """Unexpected-shape bugs (KeyError/TypeError on backend responses) are
        the class the per-tool fallback still guards — network errors already
        become APIError inside the client."""
        import json

        client.project_id = "proj-1"
        client.get.side_effect = TypeError("'NoneType' object is not subscriptable")

        payload = json.loads(mcp_server.hb_get_posture())

        assert payload["error"] is True
        assert "NoneType" in payload["message"]

    def test_humanbound_error_still_returns_envelope(self, client):
        import json

        from humanbound_cli.exceptions import APIError

        client.project_id = "proj-1"
        client.get.side_effect = APIError("backend said no")

        payload = json.loads(mcp_server.hb_get_posture())

        assert payload["error"] is True
        assert "backend said no" in payload["message"]
