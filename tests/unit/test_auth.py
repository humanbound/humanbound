"""
Unit tests for `hb whoami` and `hb logout` commands.

Mocked HumanboundClient — no live API needed.
Login opens a browser so it is not tested here.
"""

import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(__file__))

from conftest import MOCK_ORG, MOCK_PROJECT

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.auth.HumanboundClient"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m._username = "testuser"
    m._email = "test@example.com"
    m._default_organisation_id = "org-123"
    m.base_url = "http://test.local/api"
    # Properties accessed as attributes
    m.username = "testuser"
    m.email = "test@example.com"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(PATCH_TARGET)
    def test_whoami_authenticated(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        assert "testuser" in result.output or "test@example.com" in result.output

    @patch(PATCH_TARGET)
    def test_whoami_shows_email(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        assert "test@example.com" in result.output

    @patch(PATCH_TARGET)
    def test_whoami_shows_org_name(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        assert "Test Org" in result.output

    @patch(PATCH_TARGET)
    def test_whoami_via_auth_subcommand(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["auth", "whoami"])
        assert result.exit_code == 0
        assert "Authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_logout(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        mock.logout.assert_called_once()

    @patch(PATCH_TARGET)
    def test_logout_via_auth_subcommand(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["auth", "logout"])
        assert result.exit_code == 0
        mock.logout.assert_called_once()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_whoami_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0  # whoami doesn't exit(1), it shows status
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_whoami_org_resolve_fails(self, MockClient):
        """Even if org name resolution fails, whoami should not crash."""
        mock = _make_client()
        mock.list_organisations.side_effect = APIError("Network error")
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        # Should still show something — the org ID at minimum
        assert "org-123" in result.output


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_whoami_output_contains_status_panel(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        # Rich panel title
        assert "Humanbound Status" in result.output or "Authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_whoami_unauthenticated_suggests_login(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0
        assert "hb login" in result.output or "login" in result.output.lower()
