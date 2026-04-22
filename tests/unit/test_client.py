"""
Unit tests for HumanboundClient — no live API required.

Covers: auth checks, header building, response handling, credential storage,
token refresh, convenience methods, and error mapping.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.client import HumanboundClient
from humanbound_cli.exceptions import (
    APIError,
    AuthenticationError,
    ForbiddenError,
    NotAuthenticatedError,
    NotFoundError,
    RateLimitError,
    SessionExpiredError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a client with mocked credential storage."""
    config_dir = tmp_path / ".humanbound"
    config_dir.mkdir()
    token_file = config_dir / "credentials.json"

    monkeypatch.setattr("humanbound_cli.client.CONFIG_DIR", config_dir)
    monkeypatch.setattr("humanbound_cli.client.TOKEN_FILE", token_file)
    monkeypatch.setattr("humanbound_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("humanbound_cli.config.TOKEN_FILE", token_file)

    c = HumanboundClient(base_url="http://test.local/api")
    c._api_token = "test-token"
    c._token_expires_at = time.time() + 3600
    c._organisation_id = "org-123"
    c._project_id = "proj-456"
    return c


@pytest.fixture
def unauthenticated_client(tmp_path, monkeypatch):
    """Client with no credentials."""
    config_dir = tmp_path / ".humanbound"
    config_dir.mkdir()
    token_file = config_dir / "credentials.json"
    monkeypatch.setattr("humanbound_cli.client.CONFIG_DIR", config_dir)
    monkeypatch.setattr("humanbound_cli.client.TOKEN_FILE", token_file)
    monkeypatch.setattr("humanbound_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("humanbound_cli.config.TOKEN_FILE", token_file)
    return HumanboundClient(base_url="http://test.local/api")


def _mock_response(status_code=200, json_data=None, text=""):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {})
    return resp


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_is_authenticated_with_valid_token(self, client):
        assert client.is_authenticated() is True

    def test_is_authenticated_no_token(self, unauthenticated_client):
        assert unauthenticated_client.is_authenticated() is False

    def test_is_authenticated_expired_no_refresh(self, client, tmp_path, monkeypatch):
        client._token_expires_at = time.time() - 100
        # No refresh token in file
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text(json.dumps({}))
        assert client.is_authenticated() is False

    def test_ensure_authenticated_raises(self, unauthenticated_client):
        with pytest.raises(NotAuthenticatedError, match="Not authenticated"):
            unauthenticated_client._ensure_authenticated()

    def test_logout_clears_state(self, client, tmp_path):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text(json.dumps({"api_token": "x"}))

        client.logout(silent=True)

        assert client._api_token is None
        assert client._organisation_id is None
        assert client._project_id is None
        assert not token_file.exists()


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_headers_include_auth(self, client):
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_headers_include_org(self, client):
        headers = client._get_headers(include_org=True)
        assert headers["organisation_id"] == "org-123"

    def test_headers_exclude_org(self, client):
        headers = client._get_headers(include_org=False)
        assert "organisation_id" not in headers

    def test_headers_include_project(self, client):
        headers = client._get_headers(include_project=True)
        assert headers["project_id"] == "proj-456"

    def test_headers_exclude_project(self, client):
        headers = client._get_headers(include_project=False)
        assert "project_id" not in headers


# ---------------------------------------------------------------------------
# Response Handling
# ---------------------------------------------------------------------------


class TestHandleResponse:
    def test_200_returns_json(self, client):
        resp = _mock_response(200, {"data": [1, 2, 3]})
        result = client._handle_response(resp)
        assert result == {"data": [1, 2, 3]}

    def test_204_returns_none(self, client):
        resp = _mock_response(204)
        assert client._handle_response(resp) is None

    def test_404_raises_not_found(self, client):
        resp = _mock_response(404, {"message": "Project not found"})
        with pytest.raises(NotFoundError, match="Project not found"):
            client._handle_response(resp)

    def test_401_revoked_raises_session_expired(self, client):
        resp = _mock_response(401, {"message": "Session has been revoked"})
        with pytest.raises(SessionExpiredError):
            client._handle_response(resp)

    def test_401_expired_raises_session_expired(self, client):
        resp = _mock_response(401, {"message": "Token expired"})
        with pytest.raises(SessionExpiredError):
            client._handle_response(resp)

    def test_401_generic_raises_forbidden(self, client):
        resp = _mock_response(401, {"message": "Unauthorized"})
        with pytest.raises(ForbiddenError):
            client._handle_response(resp)

    def test_403_raises_forbidden(self, client):
        resp = _mock_response(403, {"message": "Forbidden"})
        with pytest.raises(ForbiddenError):
            client._handle_response(resp)

    def test_429_raises_rate_limit(self, client):
        resp = _mock_response(429, {"message": "Too many requests"})
        with pytest.raises(RateLimitError):
            client._handle_response(resp)

    def test_500_raises_api_error(self, client):
        resp = _mock_response(500, {"message": "Internal server error"})
        with pytest.raises(APIError, match="Internal server error") as exc_info:
            client._handle_response(resp)
        assert exc_info.value.status_code == 500

    def test_invalid_json_body(self, client):
        resp = MagicMock()
        resp.status_code = 502
        resp.json.side_effect = ValueError("No JSON")
        resp.text = "Bad Gateway"
        with pytest.raises(APIError, match="Bad Gateway"):
            client._handle_response(resp)

    def test_api_error_stores_response(self, client):
        resp = _mock_response(422, {"message": "Validation failed", "errors": ["field required"]})
        with pytest.raises(APIError) as exc_info:
            client._handle_response(resp)
        assert exc_info.value.response == {
            "message": "Validation failed",
            "errors": ["field required"],
        }


# ---------------------------------------------------------------------------
# HTTP Methods
# ---------------------------------------------------------------------------


class TestHTTPMethods:
    @patch("humanbound_cli.client.requests.get")
    def test_get_calls_requests(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": []})
        result = client.get("projects", params={"page": 1})
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert (
            "http://test.local/api/projects" in call_kwargs.args
            or call_kwargs.kwargs.get("url", call_kwargs.args[0])
            == "http://test.local/api/projects"
        )

    @patch("humanbound_cli.client.requests.post")
    def test_post_sends_json(self, mock_post, client):
        mock_post.return_value = _mock_response(200, {"id": "new-123"})
        result = client.post("projects", data={"name": "Test"})
        assert result == {"id": "new-123"}
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("json") == {"name": "Test"} or call_kwargs[1].get("json") == {
            "name": "Test"
        }

    @patch("humanbound_cli.client.requests.put")
    def test_put_sends_json(self, mock_put, client):
        mock_put.return_value = _mock_response(200, {"updated": True})
        result = client.put("projects/123", data={"name": "Updated"})
        assert result == {"updated": True}

    @patch("humanbound_cli.client.requests.delete")
    def test_delete_works(self, mock_delete, client):
        mock_delete.return_value = _mock_response(204)
        result = client.delete("projects/123")
        assert result is None

    @patch("humanbound_cli.client.requests.get")
    def test_get_unauthenticated_raises(self, mock_get, unauthenticated_client):
        with pytest.raises(NotAuthenticatedError):
            unauthenticated_client.get("projects")
        mock_get.assert_not_called()

    @patch("humanbound_cli.client.requests.get")
    def test_get_extra_headers(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {})
        client.get("endpoint", extra_headers={"X-Custom": "val"})
        headers = mock_get.call_args.kwargs.get("headers") or mock_get.call_args[1].get("headers")
        assert headers["X-Custom"] == "val"
        assert headers["Authorization"] == "Bearer test-token"


# ---------------------------------------------------------------------------
# Credential Persistence
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_save_and_load(self, client, tmp_path, monkeypatch):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        client._save_credentials("refresh-abc")

        assert token_file.exists()
        data = json.loads(token_file.read_text())
        assert data["api_token"] == "test-token"
        assert data["organisation_id"] == "org-123"
        assert data["project_id"] == "proj-456"
        assert data["refresh_token"] == "refresh-abc"

        # Verify file permissions (0o600)
        mode = token_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_load_missing_file(self, unauthenticated_client, tmp_path):
        creds = unauthenticated_client._load_credentials_file()
        assert creds == {}

    def test_load_corrupt_file(self, unauthenticated_client, tmp_path, monkeypatch):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text("not json {{{{")
        creds = unauthenticated_client._load_credentials_file()
        assert creds == {}


# ---------------------------------------------------------------------------
# Context Management
# ---------------------------------------------------------------------------


class TestContext:
    def test_set_organisation_clears_project(self, client):
        assert client._project_id == "proj-456"
        client.set_organisation("org-new")
        assert client._organisation_id == "org-new"
        assert client._project_id is None

    def test_set_project(self, client):
        client.set_project("proj-new")
        assert client._project_id == "proj-new"

    def test_properties(self, client):
        assert client.organisation_id == "org-123"
        assert client.project_id == "proj-456"


# ---------------------------------------------------------------------------
# Convenience Methods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    @patch("humanbound_cli.client.requests.get")
    def test_list_organisations(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": [{"id": "org-1"}]})
        result = client.list_organisations()
        assert result == [{"id": "org-1"}]

    @patch("humanbound_cli.client.requests.get")
    def test_list_projects(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": [{"id": "p1"}], "total": 1})
        result = client.list_projects(page=2, size=10)
        assert result["data"] == [{"id": "p1"}]
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["page"] == 2
        assert params["size"] == 10

    @patch("humanbound_cli.client.requests.get")
    def test_list_experiments(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": []})
        result = client.list_experiments()
        assert result == {"data": []}

    @patch("humanbound_cli.client.requests.get")
    def test_get_experiment(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"id": "exp-1", "status": "completed"})
        result = client.get_experiment("exp-1")
        assert result["id"] == "exp-1"

    @patch("humanbound_cli.client.requests.get")
    def test_list_findings(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": [], "total": 0})
        result = client.list_findings("proj-456", status="open", severity="high")
        call_url = (
            mock_get.call_args.args[0]
            if mock_get.call_args.args
            else mock_get.call_args.kwargs.get("url", "")
        )
        assert "findings" in call_url

    @patch("humanbound_cli.client.requests.get")
    def test_list_members(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": [{"email": "a@b.c"}]})
        result = client.list_members()
        assert isinstance(result, dict)

    @patch("humanbound_cli.client.requests.get")
    def test_list_api_keys(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": []})
        result = client.list_api_keys()
        assert isinstance(result, dict)

    @patch("humanbound_cli.client.requests.post")
    def test_create_api_key(self, mock_post, client):
        mock_post.return_value = _mock_response(200, {"id": "key-1", "key": "hb_xxx"})
        result = client.create_api_key("my-key")
        assert result["id"] == "key-1"

    @patch("humanbound_cli.client.requests.get")
    def test_get_project_logs_with_filters(self, mock_get, client):
        mock_get.return_value = _mock_response(200, {"data": [], "total": 0})
        client.get_project_logs(
            from_date="2025-01-01", until_date="2025-12-31", test_category="prompt", last=5
        )
        params = mock_get.call_args.kwargs.get("params") or mock_get.call_args[1].get("params")
        assert params["from"] == "2025-01-01"
        assert params["to"] == "2025-12-31"
        assert params["test_category"] == "prompt"
        assert params["last"] == 5


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    @patch("humanbound_cli.client.requests.get")
    @patch("humanbound_cli.client.requests.post")
    def test_refresh_token_success(self, mock_post, mock_get, client, tmp_path):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text(json.dumps({"refresh_token": "rt-abc"}))

        # Mock Auth0 token refresh
        mock_post.return_value = _mock_response(
            200,
            {
                "access_token": "new-auth0-token",
                "expires_in": 3600,
                "refresh_token": "rt-new",
            },
        )
        # Mock API token exchange
        mock_get.return_value = _mock_response(
            200,
            {
                "access_token": "new-api-token",
                "user": {"username": "tester"},
            },
        )

        client._refresh_token()
        assert client._api_token == "new-api-token"

    def test_refresh_token_no_refresh_token(self, client, tmp_path):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text(json.dumps({}))

        with pytest.raises(AuthenticationError, match="No refresh token"):
            client._refresh_token()

    @patch("humanbound_cli.client.requests.post")
    def test_refresh_token_auth0_fails(self, mock_post, client, tmp_path):
        token_file = tmp_path / ".humanbound" / "credentials.json"
        token_file.write_text(json.dumps({"refresh_token": "rt-abc"}))

        mock_post.return_value = _mock_response(401, {"error": "invalid_grant"})

        with pytest.raises(AuthenticationError, match="refresh failed"):
            client._refresh_token()
