"""Security tests for OAuth callback listeners and redirects."""

import io
import time
import urllib.parse
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from humanbound_cli.client import HumanboundClient
from humanbound_cli.exceptions import AuthenticationError
from humanbound_cli.main import cli


class _FakeRequest:
    """Minimal socket-like request used to run a callback handler."""

    def __init__(self, request: bytes):
        self._input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, mode, buffering):
        assert mode == "rb"
        return self._input

    def sendall(self, data):
        self.output.write(data)


def _response(status_code=200, data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = data or {}
    response.text = ""
    return response


def _login_with_callback(monkeypatch, callback_path: str):
    """Run login through the captured handler and return its server."""
    client = HumanboundClient(base_url="http://test.local")
    client._exchange_for_api_token = MagicMock()
    client._save_credentials = MagicMock()
    captured = {}
    server = MagicMock()

    def create_server(address, handler):
        captured["address"] = address
        captured["handler"] = handler
        return server

    def serve_callback():
        request = _FakeRequest(f"GET {callback_path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        captured["handler"](request, ("127.0.0.1", 12345), server)
        captured["response"] = request.output.getvalue()

    server.handle_request.side_effect = serve_callback
    monkeypatch.setattr("humanbound_cli.client.socketserver.TCPServer", create_server)
    monkeypatch.setattr("humanbound_cli.client.get_auth0_domain", lambda: "auth.example")
    monkeypatch.setattr("humanbound_cli.client.get_auth0_client_id", lambda: "client-id")
    monkeypatch.setattr("humanbound_cli.client.get_auth0_audience", lambda: "audience")
    monkeypatch.setattr("humanbound_cli.client.webbrowser.open", lambda _: True)
    monkeypatch.setattr(
        "humanbound_cli.client.requests.post",
        lambda *args, **kwargs: _response(
            data={"access_token": "auth0-token", "expires_in": 3600, "refresh_token": "refresh"}
        ),
    )
    return client, captured, server


def test_login_binds_callback_server_to_loopback(monkeypatch):
    client, captured, _ = _login_with_callback(monkeypatch, "/not-callback?code=code&state=state")

    with pytest.raises(AuthenticationError, match="Unexpected OAuth callback path"):
        client.login(callback_port=8099)

    assert captured["address"] == ("127.0.0.1", 8099)


def test_login_rejects_code_and_state_on_non_callback_path(monkeypatch):
    client, captured, _ = _login_with_callback(monkeypatch, "/?code=code&state=state")

    with pytest.raises(AuthenticationError, match="Unexpected OAuth callback path"):
        client.login()

    assert b"404" in captured["response"]


def test_login_accepts_code_and_state_on_callback_path(monkeypatch):
    captured = {}

    def callback_path():
        state = urllib.parse.parse_qs(urllib.parse.urlparse(captured["auth_url"]).query)["state"][0]
        return f"/callback?code=code&state={state}"

    client = HumanboundClient(base_url="http://test.local")
    client._exchange_for_api_token = MagicMock()
    client._save_credentials = MagicMock()
    server = MagicMock()

    def create_server(address, handler):
        captured["address"] = address
        captured["handler"] = handler
        return server

    def serve_callback():
        request = _FakeRequest(
            f"GET {callback_path()} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        )
        captured["handler"](request, ("127.0.0.1", 12345), server)
        captured["response"] = request.output.getvalue()

    server.handle_request.side_effect = serve_callback
    monkeypatch.setattr("humanbound_cli.client.socketserver.TCPServer", create_server)
    monkeypatch.setattr("humanbound_cli.client.get_auth0_domain", lambda: "auth.example")
    monkeypatch.setattr("humanbound_cli.client.get_auth0_client_id", lambda: "client-id")
    monkeypatch.setattr("humanbound_cli.client.get_auth0_audience", lambda: "audience")
    monkeypatch.setattr(
        "humanbound_cli.client.webbrowser.open",
        lambda url: captured.setdefault("auth_url", url) or True,
    )
    monkeypatch.setattr(
        "humanbound_cli.client.requests.post",
        lambda *args, **kwargs: _response(
            data={"access_token": "auth0-token", "expires_in": 3600, "refresh_token": "refresh"}
        ),
    )

    assert client.login() is True
    assert captured["address"] == ("127.0.0.1", 8085)
    assert b"200" in captured["response"]


def test_logout_revoke_binds_callback_server_to_loopback(monkeypatch):
    client = MagicMock()
    server = MagicMock()
    captured = {}

    def create_server(address, handler):
        captured["address"] = address
        return server

    monkeypatch.setattr("humanbound_cli.commands.auth.HumanboundClient", lambda: client)
    monkeypatch.setattr("socketserver.TCPServer", create_server)
    monkeypatch.setattr("webbrowser.open", lambda _: True)
    monkeypatch.setattr("humanbound_cli.config.get_auth0_domain", lambda: "auth.example")
    monkeypatch.setattr("humanbound_cli.config.get_auth0_client_id", lambda: "client-id")

    result = CliRunner().invoke(cli, ["logout", "--revoke", "--port", "8099"])

    assert result.exit_code == 0
    assert captured["address"] == ("127.0.0.1", 8099)


def test_persist_discovery_disables_redirects(monkeypatch):
    client = HumanboundClient(base_url="http://test.local")
    client._api_token = "api-token"
    client._token_expires_at = time.time() + 3600
    client._organisation_id = "org-123"
    post = MagicMock(return_value=_response(data={"persisted": 1}))
    monkeypatch.setattr("humanbound_cli.client.requests.post", post)

    assert client.persist_discovery("nonce") == {"persisted": 1}
    assert post.call_args.kwargs["allow_redirects"] is False


def test_auth_token_paths_disable_redirects(monkeypatch):
    """Auth helpers that bypass get/post wrappers must still refuse redirects."""
    client = HumanboundClient(base_url="http://test.local")
    client._auth0_token = "auth0-token"
    client._api_token = "api-token"

    get = MagicMock(return_value=_response(data={"access_token": "api"}))
    post = MagicMock(
        return_value=_response(
            data={"access_token": "auth0", "expires_in": 60, "refresh_token": "r"}
        )
    )
    monkeypatch.setattr("humanbound_cli.client.requests.get", get)
    monkeypatch.setattr("humanbound_cli.client.requests.post", post)
    monkeypatch.setattr("humanbound_cli.client.get_auth0_domain", lambda: "auth.example")
    monkeypatch.setattr("humanbound_cli.client.get_auth0_client_id", lambda: "client-id")
    monkeypatch.setattr(
        client,
        "_load_credentials_file",
        lambda: {"refresh_token": "refresh"},
    )
    monkeypatch.setattr(client, "_save_credentials", lambda *a, **k: None)
    monkeypatch.setattr(client, "_exchange_for_api_token", lambda: None)

    # Call the real exchange method once (unpatch local stub).
    HumanboundClient._exchange_for_api_token(client)
    assert get.call_args.kwargs["allow_redirects"] is False

    client.logout(silent=True)
    assert get.call_args.kwargs["allow_redirects"] is False

    HumanboundClient._refresh_token(client)
    assert post.call_args.kwargs["allow_redirects"] is False
