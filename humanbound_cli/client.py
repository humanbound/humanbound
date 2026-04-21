# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound API client with OAuth authentication."""

import json
import os
import time
import webbrowser
import http.server
import socketserver
import secrets
import hashlib
import base64
import urllib.parse
from typing import Optional, Dict, Any, List

import requests

from .config import (
    DEFAULT_BASE_URL,
    get_base_url,
    get_auth0_domain,
    get_auth0_client_id,
    get_auth0_audience,
    CONFIG_DIR,
    TOKEN_FILE,
    DEFAULT_TIMEOUT,
    LONG_TIMEOUT,
)
from .exceptions import (
    HumanboundError,
    AuthenticationError,
    NotAuthenticatedError,
    APIError,
    NotFoundError,
    ForbiddenError,
    SessionExpiredError,
    RateLimitError,
)


# HTML templates for OAuth callback pages
SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Humanbound CLI - Authenticated</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
            color: #e6edf3;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 3rem;
            background: rgba(22, 27, 34, 0.8);
            border: 1px solid #30363d;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            max-width: 480px;
        }
        .icon {
            width: 64px;
            height: 64px;
            margin-bottom: 1.5rem;
            background: #238636;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: auto;
            margin-right: auto;
        }
        .icon svg { width: 32px; height: 32px; fill: white; }
        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            color: #58a6ff;
        }
        .success { color: #3fb950; }
        p {
            color: #8b949e;
            font-size: 0.9rem;
            line-height: 1.6;
        }
        .command {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 1rem;
            margin-top: 1.5rem;
            font-size: 0.85rem;
        }
        .command code {
            color: #7ee787;
        }
        .prompt { color: #6e7681; }
        .close-hint {
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: #6e7681;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">
            <svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
        </div>
        <h1 class="success">Authentication Successful</h1>
        <p>You're now logged in to the Humanbound CLI.<br>Return to your terminal to continue.</p>
        <div class="command">
            <span class="prompt">$</span> <code>hb orgs list</code>
        </div>
        <p class="close-hint">You can close this tab</p>
    </div>
    <script>/* window stays open so user can see the result */</script>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Humanbound CLI - Error</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
            color: #e6edf3;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 3rem;
            background: rgba(22, 27, 34, 0.8);
            border: 1px solid #30363d;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            max-width: 480px;
        }
        .icon {
            width: 64px;
            height: 64px;
            margin-bottom: 1.5rem;
            background: #da3633;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: auto;
            margin-right: auto;
        }
        .icon svg { width: 32px; height: 32px; fill: white; }
        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            color: #f85149;
        }
        p {
            color: #8b949e;
            font-size: 0.9rem;
            line-height: 1.6;
        }
        .error-box {
            background: #0d1117;
            border: 1px solid #f8514966;
            border-radius: 6px;
            padding: 1rem;
            margin-top: 1.5rem;
            font-size: 0.85rem;
            color: #f85149;
            word-break: break-word;
        }
        .retry {
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: #6e7681;
        }
        .retry code {
            color: #7ee787;
            background: #0d1117;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">
            <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
        </div>
        <h1>Authentication Failed</h1>
        <p>Something went wrong during login.</p>
        <div class="error-box">{{ERROR}}</div>
        <p class="retry">Try again: <code>hb login</code></p>
    </div>
</body>
</html>"""


LOGOUT_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Humanbound CLI - Logged Out</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
            color: #e6edf3;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 3rem;
            background: rgba(22, 27, 34, 0.8);
            border: 1px solid #30363d;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            max-width: 480px;
        }
        .icon {
            width: 64px;
            height: 64px;
            margin-bottom: 1.5rem;
            background: #58a6ff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: auto;
            margin-right: auto;
        }
        .icon svg { width: 32px; height: 32px; fill: white; }
        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            color: #58a6ff;
        }
        p {
            color: #8b949e;
            font-size: 0.9rem;
            line-height: 1.6;
        }
        .command {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 1rem;
            margin-top: 1.5rem;
            font-size: 0.85rem;
        }
        .command code {
            color: #7ee787;
        }
        .prompt { color: #6e7681; }
        .close-hint {
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: #6e7681;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">
            <svg viewBox="0 0 24 24"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.58-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg>
        </div>
        <h1>Session Revoked</h1>
        <p>Your local credentials and browser session have been cleared.</p>
        <div class="command">
            <span class="prompt">$</span> <code>hb login</code>
        </div>
        <p class="close-hint">You can close this tab</p>
    </div>
</body>
</html>"""


class HumanboundClient:
    """API client for Humanbound platform with OAuth authentication."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize the client.

        Args:
            base_url: Optional base URL override for on-prem deployments.
        """
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self._auth0_token: Optional[str] = None
        self._api_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        self._organisation_id: Optional[str] = None
        self._project_id: Optional[str] = None
        self._username: Optional[str] = None
        self._email: Optional[str] = None
        self._default_organisation_id: Optional[str] = None

        # Try to load existing credentials
        self._load_credentials()

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def login(self, callback_port: int = 8085) -> bool:
        """Initiate OAuth login via browser.

        Opens the browser for Auth0 authentication and waits for the callback.

        Args:
            callback_port: Local port for OAuth callback server.

        Returns:
            True if login was successful.

        Raises:
            AuthenticationError: If login fails.
        """
        auth0_domain = get_auth0_domain()
        client_id = get_auth0_client_id()
        audience = get_auth0_audience()

        # Generate PKCE code verifier and challenge
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        redirect_uri = f"http://localhost:{callback_port}/callback"

        # Build authorization URL
        auth_params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "audience": audience,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"https://{auth0_domain}/authorize?" + urllib.parse.urlencode(auth_params)

        # Start callback server
        auth_result = {"code": None, "error": None}

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                if "code" in params and params.get("state", [None])[0] == state:
                    auth_result["code"] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(SUCCESS_HTML.encode())
                else:
                    auth_result["error"] = params.get("error_description", ["Unknown error"])[0]
                    self.send_response(400)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    error_html = ERROR_HTML.replace("{{ERROR}}", str(auth_result["error"]))
                    self.wfile.write(error_html.encode())

            def log_message(self, format, *args):
                pass  # Suppress server logs

        # Allow port reuse to avoid "Address already in use" errors
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("", callback_port), CallbackHandler)
        server.timeout = 120  # 2 minute timeout

        try:
            # Open browser
            print("Opening browser for authentication...")
            print(f"\nIf browser doesn't open, visit:\n{auth_url}\n")
            webbrowser.open(auth_url)

            # Wait for callback
            server.handle_request()
        finally:
            # Always close the server, even on errors
            server.server_close()

        if auth_result["error"]:
            raise AuthenticationError(f"Login failed: {auth_result['error']}")

        if not auth_result["code"]:
            raise AuthenticationError("Login timed out or was cancelled")

        # Exchange code for tokens
        token_url = f"https://{auth0_domain}/oauth/token"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": auth_result["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }

        response = requests.post(token_url, json=token_data, timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            raise AuthenticationError(f"Token exchange failed: {response.text}")

        tokens = response.json()
        self._auth0_token = tokens.get("access_token")
        self._token_expires_at = time.time() + tokens.get("expires_in", 3600)

        # Exchange Auth0 token for API session token
        self._exchange_for_api_token()

        # Save credentials
        self._save_credentials(tokens.get("refresh_token"))

        print("Login successful!")
        return True

    def logout(self, silent: bool = False) -> None:
        """Clear stored credentials and logout.

        Args:
            silent: If True, don't print success message (used for cleanup).
        """
        self._auth0_token = None
        self._api_token = None
        self._token_expires_at = None
        self._organisation_id = None
        self._project_id = None

        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

        if not silent:
            print("Logged out successfully.")

    def is_authenticated(self) -> bool:
        """Check if the client has valid credentials.

        Returns:
            True if authenticated and token is not expired.
        """
        if not self._api_token:
            return False

        if self._token_expires_at and time.time() >= self._token_expires_at:
            # Try to refresh
            try:
                self._refresh_token()
                return True
            except AuthenticationError:
                return False

        return True

    def _exchange_for_api_token(self) -> None:
        """Exchange Auth0 token for API session token."""
        try:
            response = requests.get(
                f"{self.base_url}/auth",
                headers={"Authorization": f"Bearer {self._auth0_token}"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.ConnectionError:
            raise AuthenticationError(f"Could not connect to {self.base_url}. Is the server running?")
        except requests.Timeout:
            raise AuthenticationError(f"Connection to {self.base_url} timed out.")

        if response.status_code != 200:
            raise AuthenticationError(f"API authentication failed ({response.status_code}): {response.text}")

        try:
            data = response.json()
        except Exception:
            raise AuthenticationError(f"API returned invalid response from {self.base_url}/auth")
        self._api_token = data.get("access_token") or data.get("token")
        if not self._api_token:
            raise AuthenticationError("No access token in API response")

        # Store user info from auth response
        user = data.get("user", {})
        if user:
            self._username = user.get("username")
            self._email = user.get("email")
            self._default_organisation_id = user.get("default_organisation_id")

    def _refresh_token(self) -> None:
        """Refresh the access token using refresh token."""
        credentials = self._load_credentials_file()
        refresh_token = credentials.get("refresh_token")

        if not refresh_token:
            raise AuthenticationError("No refresh token available. Please login again.")

        auth0_domain = get_auth0_domain()
        client_id = get_auth0_client_id()

        response = requests.post(
            f"https://{auth0_domain}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            timeout=DEFAULT_TIMEOUT,
        )

        if response.status_code != 200:
            raise AuthenticationError("Token refresh failed. Please login again.")

        tokens = response.json()
        self._auth0_token = tokens.get("access_token")
        self._token_expires_at = time.time() + tokens.get("expires_in", 3600)

        # Exchange for API token
        self._exchange_for_api_token()

        # Update stored credentials
        self._save_credentials(tokens.get("refresh_token", refresh_token))

    def _load_credentials(self) -> None:
        """Load credentials from disk."""
        credentials = self._load_credentials_file()
        if credentials:
            self._api_token = credentials.get("api_token")
            self._token_expires_at = credentials.get("expires_at")
            self._organisation_id = credentials.get("organisation_id")
            self._project_id = credentials.get("project_id")
            self._username = credentials.get("username")
            self._email = credentials.get("email")
            self._default_organisation_id = credentials.get("default_organisation_id")
            # Restore saved base_url unless explicitly overridden via --base-url or env var
            saved_url = credentials.get("base_url")
            env_override = os.environ.get("HUMANBOUND_BASE_URL")
            if saved_url and not env_override and self.base_url == DEFAULT_BASE_URL.rstrip("/"):
                self.base_url = saved_url.rstrip("/")

    def _load_credentials_file(self) -> dict:
        """Load credentials file."""
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_credentials(self, refresh_token: Optional[str] = None) -> None:
        """Save credentials to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.chmod(0o600) if TOKEN_FILE.exists() else None

        credentials = {
            "api_token": self._api_token,
            "expires_at": self._token_expires_at,
            "refresh_token": refresh_token,
            "organisation_id": self._organisation_id,
            "project_id": self._project_id,
            "base_url": self.base_url,
            "username": self._username,
            "email": self._email,
            "default_organisation_id": self._default_organisation_id,
        }

        TOKEN_FILE.write_text(json.dumps(credentials))
        TOKEN_FILE.chmod(0o600)

    # -------------------------------------------------------------------------
    # Context Management
    # -------------------------------------------------------------------------

    def set_organisation(self, organisation_id: str) -> None:
        """Set the active organisation for subsequent API calls.

        Args:
            organisation_id: Organisation UUID.
        """
        self._organisation_id = organisation_id
        self._project_id = None  # Reset project when org changes
        self._save_credentials(self._load_credentials_file().get("refresh_token"))

    def set_project(self, project_id: str) -> None:
        """Set the active project for subsequent API calls.

        Args:
            project_id: Project UUID.
        """
        self._project_id = project_id
        self._save_credentials(self._load_credentials_file().get("refresh_token"))

    @property
    def organisation_id(self) -> Optional[str]:
        """Get current organisation ID."""
        return self._organisation_id

    @property
    def project_id(self) -> Optional[str]:
        """Get current project ID."""
        return self._project_id

    @property
    def username(self) -> Optional[str]:
        """Get current username."""
        return self._username

    @property
    def email(self) -> Optional[str]:
        """Get current email."""
        return self._email

    @property
    def default_organisation_id(self) -> Optional[str]:
        """Get default organisation ID."""
        return self._default_organisation_id

    # -------------------------------------------------------------------------
    # HTTP Methods
    # -------------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        """Ensure the client is authenticated."""
        if not self.is_authenticated():
            raise NotAuthenticatedError("Not authenticated. Please run 'hb login' first.")

    def _get_headers(self, include_org: bool = True, include_project: bool = False) -> dict:
        """Build request headers.

        Args:
            include_org: Include organisation_id header.
            include_project: Include project_id header.

        Returns:
            Headers dictionary.
        """
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

        if include_org and self._organisation_id:
            headers["organisation_id"] = self._organisation_id

        if include_project and self._project_id:
            headers["project_id"] = self._project_id

        return headers

    def _handle_response(self, response: requests.Response) -> Any:
        """Handle API response and raise appropriate exceptions.

        Args:
            response: Requests response object.

        Returns:
            Parsed JSON response or None.

        Raises:
            APIError: On error responses.
        """
        if response.status_code == 204:
            return None

        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text}

        if response.status_code >= 400:
            message = data.get("message", "Unknown error")

            if response.status_code == 404:
                raise NotFoundError(message, response.status_code, data)
            elif response.status_code == 401 and "revoked" in message.lower():
                raise SessionExpiredError(message, response.status_code, data)
            elif response.status_code == 401 and "expired" in message.lower():
                raise SessionExpiredError(message, response.status_code, data)
            elif response.status_code in (401, 403):
                raise ForbiddenError(message, response.status_code, data)
            elif response.status_code == 429:
                raise RateLimitError(message, response.status_code, data)
            else:
                raise APIError(message, response.status_code, data)

        return data

    def get(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        include_org: bool = True,
        include_project: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        extra_headers: Optional[dict] = None,
    ) -> Any:
        """Make GET request.

        Args:
            endpoint: API endpoint (without base URL).
            params: Query parameters.
            include_org: Include organisation header.
            include_project: Include project header.
            timeout: Request timeout in seconds.
            extra_headers: Additional headers to merge.

        Returns:
            Parsed JSON response.
        """
        self._ensure_authenticated()
        headers = self._get_headers(include_org, include_project)
        if extra_headers:
            headers.update(extra_headers)
        response = requests.get(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        return self._handle_response(response)

    def post(
        self,
        endpoint: str,
        data: Optional[dict] = None,
        include_org: bool = True,
        include_project: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Any:
        """Make POST request.

        Args:
            endpoint: API endpoint (without base URL).
            data: Request body.
            include_org: Include organisation header.
            include_project: Include project header.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response.
        """
        self._ensure_authenticated()
        response = requests.post(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers=self._get_headers(include_org, include_project),
            json=data,
            timeout=timeout,
        )
        return self._handle_response(response)

    def put(
        self,
        endpoint: str,
        data: Optional[dict] = None,
        include_org: bool = True,
        include_project: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Any:
        """Make PUT request.

        Args:
            endpoint: API endpoint (without base URL).
            data: Request body.
            include_org: Include organisation header.
            include_project: Include project header.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response.
        """
        self._ensure_authenticated()
        response = requests.put(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers=self._get_headers(include_org, include_project),
            json=data,
            timeout=timeout,
        )
        return self._handle_response(response)

    def delete(
        self,
        endpoint: str,
        include_org: bool = True,
        include_project: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Any:
        """Make DELETE request.

        Args:
            endpoint: API endpoint (without base URL).
            include_org: Include organisation header.
            include_project: Include project header.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response.
        """
        self._ensure_authenticated()
        response = requests.delete(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers=self._get_headers(include_org, include_project),
            timeout=timeout,
        )
        return self._handle_response(response)

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def list_organisations(self) -> List[dict]:
        """List all organisations the user has access to.

        Returns:
            List of organisation objects.
        """
        response = self.get("organisations", include_org=False)
        return response.get("data", []) if isinstance(response, dict) else response

    def list_projects(self, page: int = 1, size: int = 50) -> dict:
        """List projects in the current organisation.

        Args:
            page: Page number (1-indexed).
            size: Items per page.

        Returns:
            Paginated response with projects.
        """
        if not self._organisation_id:
            raise ValidationError("No organisation selected. Use set_organisation() first.")

        return self.get("projects", params={"page": page, "size": size})

    def list_experiments(self, page: int = 1, size: int = 50) -> dict:
        """List experiments in the current project.

        Args:
            page: Page number (1-indexed).
            size: Items per page.

        Returns:
            Paginated response with experiments.
        """
        if not self._project_id:
            raise ValidationError("No project selected. Use set_project() first.")

        return self.get(
            "experiments",
            params={"page": page, "size": size},
            include_project=True,
        )

    def get_experiment(self, experiment_id: str) -> dict:
        """Get a specific experiment.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Experiment object.
        """
        return self.get(f"experiments/{experiment_id}", include_project=True)

    def get_experiment_status(self, experiment_id: str) -> dict:
        """Get experiment status.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Status object with status field.
        """
        return self.get(f"experiments/{experiment_id}/status", include_project=True)

    def get_experiment_logs(
        self,
        experiment_id: str,
        page: int = 1,
        size: int = 50,
        result: Optional[str] = None,
    ) -> dict:
        """Get logs for an experiment.

        Args:
            experiment_id: Experiment UUID.
            page: Page number.
            size: Items per page.
            result: Filter by result (pass/fail).

        Returns:
            Paginated response with logs.
        """
        params: Dict[str, Any] = {"page": page, "size": size}
        endpoint = f"experiments/{experiment_id}/logs"
        if result:
            endpoint = f"experiments/{experiment_id}/logs/{result}"

        return self.get(endpoint, params=params, include_project=True)

    def get_project_logs(
        self,
        page: int = 1,
        size: int = 50,
        result: Optional[str] = None,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
        test_category: Optional[str] = None,
        last: Optional[int] = None,
    ) -> dict:
        """Get logs for the current project.

        Args:
            page: Page number.
            size: Items per page.
            result: Filter by result (pass/fail).
            from_date: Start date (ISO 8601).
            until_date: End date (ISO 8601).
            test_category: Filter by test category (substring match).
            last: Limit to last N experiments.

        Returns:
            Paginated response with logs.
        """
        if not self._project_id:
            raise ValidationError("No project selected. Use set_project() first.")

        params: Dict[str, Any] = {"page": page, "size": size}
        if from_date:
            params["from"] = from_date
        if until_date:
            params["to"] = until_date
        if test_category:
            params["test_category"] = test_category
        if last:
            params["last"] = last

        endpoint = f"projects/{self._project_id}/logs"
        if result:
            endpoint = f"projects/{self._project_id}/logs/{result}"

        return self.get(endpoint, params=params, include_project=True)

    # -------------------------------------------------------------------------
    # Provider Methods
    # -------------------------------------------------------------------------

    def list_providers(self) -> List[dict]:
        """List all model providers for the current organisation.

        Returns:
            List of provider objects.
        """
        if not self._organisation_id:
            raise ValidationError("No organisation selected. Use set_organisation() first.")

        response = self.get("providers")
        return response if isinstance(response, list) else response.get("data", response)

    def add_provider(self, name: str, integration: dict, is_default: bool = False) -> dict:
        """Add a new model provider.

        Args:
            name: Provider name (openai, claude, azureopenai, etc.).
            integration: Provider integration config (api_key, endpoint, model).
            is_default: Whether to set as default provider.

        Returns:
            Created provider object.
        """
        if not self._organisation_id:
            raise ValidationError("No organisation selected. Use set_organisation() first.")

        return self.post(
            "providers",
            data={
                "name": name,
                "integration": integration,
                "is_default": is_default,
            }
        )

    def update_provider(self, provider_id: str, data: dict) -> dict:
        """Update a model provider.

        Args:
            provider_id: Provider UUID.
            data: Update data (integration, is_default).

        Returns:
            Updated provider object.
        """
        return self.put(f"providers/{provider_id}", data=data)

    def remove_provider(self, provider_id: str) -> None:
        """Remove a model provider.

        Args:
            provider_id: Provider UUID.
        """
        self.delete(f"providers/{provider_id}")

    # -------------------------------------------------------------------------
    # Findings Methods
    # -------------------------------------------------------------------------

    def list_findings(self, project_id: str, status: Optional[str] = None, severity: Optional[str] = None, page: int = 1, size: int = 50) -> dict:
        """List findings for a project."""
        params = {"page": page, "size": size}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity
        return self.get(f"projects/{project_id}/findings", include_project=True, params=params)

    def update_finding(self, project_id: str, finding_id: str, data: dict) -> dict:
        """Update a finding."""
        return self.put(f"projects/{project_id}/findings/{finding_id}", data=data)

    # -------------------------------------------------------------------------
    # Experiment Extensions
    # -------------------------------------------------------------------------

    def terminate_experiment(self, experiment_id: str) -> dict:
        """Terminate a running experiment."""
        return self.post(f"experiments/{experiment_id}/terminate", include_project=True)

    def delete_experiment(self, experiment_id: str) -> Any:
        """Delete an experiment."""
        return self.delete(f"experiments/{experiment_id}", include_project=True)

    # -------------------------------------------------------------------------
    # Project Extensions
    # -------------------------------------------------------------------------

    def update_project(self, project_id: str, data: dict) -> dict:
        """Update a project."""
        return self.put(f"projects/{project_id}", data=data)

    def delete_project(self, project_id: str) -> Any:
        """Delete a project."""
        return self.delete(f"projects/{project_id}")

    # -------------------------------------------------------------------------
    # API Key Methods
    # -------------------------------------------------------------------------

    def list_api_keys(self, page: int = 1, limit: int = 50) -> Any:
        """List API keys."""
        return self.get("api-keys", params={"page": page, "limit": limit}, include_org=False)

    def create_api_key(self, name: str, scopes: str = "admin") -> dict:
        """Create a new API key."""
        return self.post("api-keys", data={"name": name, "scopes": scopes}, include_org=False)

    def delete_api_key(self, key_id: str) -> Any:
        """Delete an API key."""
        return self.delete(f"api-keys/{key_id}", include_org=False)

    def update_api_key(self, key_id: str, data: dict) -> dict:
        """Update an API key."""
        return self.put(f"api-keys/{key_id}", data=data, include_org=False)

    # -------------------------------------------------------------------------
    # Member Methods
    # -------------------------------------------------------------------------

    def list_members(self) -> Any:
        """List organisation members."""
        return self.get("members")

    def invite_member(self, email: str, access_level: str) -> dict:
        """Invite a member to the organisation."""
        return self.post("members", data={"email": email, "access_level": access_level})

    def remove_member(self, member_id: str) -> Any:
        """Remove a member from the organisation."""
        return self.delete(f"members/{member_id}")

    # -------------------------------------------------------------------------
    # Coverage Methods
    # -------------------------------------------------------------------------

    def get_coverage(self, project_id: str, include_gaps: bool = False) -> dict:
        """Get test coverage for a project."""
        params = {"include_gaps": "true"} if include_gaps else {}
        return self.get(f"projects/{project_id}/coverage", params=params)

    # -------------------------------------------------------------------------
    # Posture Trends Methods
    # -------------------------------------------------------------------------

    def get_posture_trends(self, project_id: str) -> Any:
        """Get posture trend history for a project."""
        return self.get(f"projects/{project_id}/posture/trends")

    # -------------------------------------------------------------------------
    # Campaign Methods
    # -------------------------------------------------------------------------

    def get_campaign(self, project_id: str) -> dict:
        """Get the current campaign for a project."""
        return self.get(f"projects/{project_id}/campaign")

    def terminate_campaign(self, project_id: str, campaign_id: str) -> dict:
        """Terminate a running campaign."""
        return self.post(f"projects/{project_id}/campaign/terminate", data={"campaign_id": campaign_id})

    # -------------------------------------------------------------------------
    # Upload Conversations Methods
    # -------------------------------------------------------------------------

    def upload_conversations(self, project_id: str, conversations: list, tag: Optional[str] = None, lang: Optional[str] = None) -> dict:
        """Upload conversation logs for evaluation."""
        data = {"conversations": conversations}
        if tag:
            data["tag"] = tag
        if lang:
            data["lang"] = lang
        return self.post(f"projects/{project_id}/datasets/conversations", data=data, include_project=True)


    # -------------------------------------------------------------------------
    # Subscription Methods
    # -------------------------------------------------------------------------

    def get_subscription(self, subscription_id: str) -> Any:
        """Get subscription details."""
        return self.get(f"subscriptions/{subscription_id}", include_org=False)

    # -------------------------------------------------------------------------
    # Webhook Methods
    # -------------------------------------------------------------------------

    def create_webhook(self, url: str, secret: str, name: str = "Untitled Webhook", event_types: Optional[List[str]] = None) -> dict:
        """Create a webhook for the current organisation."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        data = {"url": url, "secret": secret, "name": name, "event_types": event_types or [], "is_active": True}
        return self.post(f"organisations/{org_id}/webhooks", data=data, include_org=False)

    def delete_webhook(self, webhook_id: str) -> None:
        """Delete a webhook."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        self.delete(f"organisations/{org_id}/webhooks/{webhook_id}", include_org=False)

    def get_webhook(self, webhook_id: str) -> dict:
        """Get a single webhook."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        return self.get(f"organisations/{org_id}/webhooks/{webhook_id}", include_org=False)

    def list_webhook_deliveries(self, webhook_id: str, page: int = 1, size: int = 25) -> dict:
        """List delivery log for a webhook."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        return self.get(f"organisations/{org_id}/webhooks/{webhook_id}/deliveries", params={"page": page, "size": size}, include_org=False)

    def test_webhook(self, webhook_id: str) -> dict:
        """Send a test ping to a webhook."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        return self.post(f"organisations/{org_id}/webhooks/{webhook_id}/test", include_org=False)

    def replay_webhook(self, webhook_id: str, since: Optional[str] = None, until: Optional[str] = None, project_id: Optional[str] = None, event_type: Optional[str] = None) -> dict:
        """Replay historical events through a webhook."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        data = {}
        if since:
            data["since"] = since
        if until:
            data["until"] = until
        if project_id:
            data["project_id"] = project_id
        if event_type:
            data["event_type"] = event_type
        return self.post(f"organisations/{org_id}/webhooks/{webhook_id}/replay", data=data, include_org=False)

    # -------------------------------------------------------------------------
    # Connector & Inventory Methods (Shadow AI Discovery)
    # -------------------------------------------------------------------------

    def create_connector(self, vendor: str, tenant_id: str, client_id: str, client_secret: str,
                         display_name: Optional[str] = None, scopes: Optional[List[str]] = None) -> dict:
        """Register a new cloud connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        data = {
            "vendor": vendor,
            "credentials": {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        }
        if display_name:
            data["display_name"] = display_name
        if scopes:
            data["scopes"] = scopes
        return self.post("connectors", data=data)

    def list_connectors(self) -> list:
        """List all connectors for the current organisation."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.get("connectors")

    def get_connector(self, connector_id: str) -> dict:
        """Get a single connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.get(f"connectors/{connector_id}")

    def update_connector(self, connector_id: str, data: dict) -> dict:
        """Update a connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.put(f"connectors/{connector_id}", data=data)

    def delete_connector(self, connector_id: str) -> None:
        """Delete a connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        self.delete(f"connectors/{connector_id}")

    def test_connector(self, connector_id: str) -> dict:
        """Test connection validity for a connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.post(f"connectors/{connector_id}/test")

    def trigger_discovery(self, connector_id: str) -> dict:
        """Trigger a discovery scan for a connector."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.post(
            "discover",
            data={"connector_id": connector_id},
            timeout=LONG_TIMEOUT,
        )

    def list_inventory(self, category: Optional[str] = None, vendor: Optional[str] = None,
                       risk_level: Optional[str] = None, is_sanctioned: Optional[bool] = None,
                       page: int = 1, size: int = 50) -> dict:
        """List discovered inventory assets."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        params: Dict[str, Any] = {"page": page, "size": size}
        if category:
            params["category"] = category
        if vendor:
            params["vendor"] = vendor
        if risk_level:
            params["risk_level"] = risk_level
        if is_sanctioned is not None:
            params["is_sanctioned"] = str(is_sanctioned).lower()
        return self.get("inventory", params=params)

    def get_inventory_asset(self, asset_id: str) -> dict:
        """Get a single inventory asset."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.get(f"inventory/{asset_id}")

    def update_inventory_asset(self, asset_id: str, data: dict) -> dict:
        """Update governance fields on an inventory asset."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.put(f"inventory/{asset_id}", data=data)

    def archive_inventory_asset(self, asset_id: str) -> dict:
        """Archive an inventory asset."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        return self.put(f"inventory/{asset_id}/archive")

    def get_shadow_posture(self) -> dict:
        """Get shadow AI posture from the org posture endpoint."""
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        result = self.get(f"organisations/{org_id}/posture", include_org=False)
        shadow = result.get("dimensions", {}).get("shadow_ai")
        if not shadow:
            return {"score": 100.0, "grade": "A", "total_assets": 0,
                    "shadow_count": 0, "sanctioned_count": 0, "domain_scores": {}}
        return shadow

    def persist_discovery(self, nonce: str) -> dict:
        """Persist analysed discovery results to inventory.

        POST /organisations/{org_id}/analyse/persist with x-nonce header.

        Args:
            nonce: Single-use nonce from the /analyse response.

        Returns:
            Persistence summary dict.
        """
        org_id = self._organisation_id
        if not org_id:
            raise ValidationError("No organisation selected.")
        self._ensure_authenticated()
        headers = self._get_headers(include_org=False)
        headers["x-nonce"] = nonce
        response = requests.post(
            f"{self.base_url}/organisations/{org_id}/analyse/persist",
            headers=headers,
            json={},
            timeout=LONG_TIMEOUT,
        )
        return self._handle_response(response)

    def onboard_inventory_asset(self, asset_id: str, project_name: Optional[str] = None) -> dict:
        """Create a project from an inventory asset."""
        if not self._organisation_id:
            raise ValidationError("No organisation selected.")
        data = {}
        if project_name:
            data["name"] = project_name
        return self.post(f"inventory/{asset_id}/onboard", data=data)


# Import ValidationError to this module
from .exceptions import ValidationError
