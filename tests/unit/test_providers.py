"""
Unit tests for `hb providers` commands.

Mocked HumanboundClient — no live API needed.
"""

import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(__file__))

from conftest import MOCK_PROVIDER, MOCK_PROVIDER_2

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.providers.HumanboundClient"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m._username = "testuser"
    m._email = "test@example.com"
    m.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(PATCH_TARGET)
    def test_list_providers(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 0
        assert "OPENAI" in result.output or "openai" in result.output.lower()
        assert "CLAUDE" in result.output or "claude" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_list_providers_via_group_default(self, MockClient):
        """Invoking `providers` with no subcommand should list."""
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers"])
        assert result.exit_code == 0
        assert "OPENAI" in result.output or "openai" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_delete_provider_with_force(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        mock.remove_provider.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "delete", "prov-001", "--force"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()
        mock.remove_provider.assert_called_once_with("prov-001")

    @patch(PATCH_TARGET)
    def test_update_provider(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        mock.update_provider.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "providers",
                "update",
                "prov-001",
                "--model",
                "gpt-4-turbo",
            ],
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()
        mock.update_provider.assert_called_once()

    @patch(PATCH_TARGET)
    def test_update_provider_set_default(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        mock.update_provider.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "update", "prov-002", "--default"])
        assert result.exit_code == 0
        call_args = mock.update_provider.call_args
        assert call_args[0][1]["is_default"] is True

    @patch(PATCH_TARGET)
    def test_create_help(self, MockClient):
        """Create has interactive mode — just verify --help works."""
        result = runner.invoke(cli, ["providers", "create", "--help"])
        assert result.exit_code == 0
        assert "Add a new model provider" in result.output


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_list_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_list_no_org(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code != 0
        assert "No organisation selected" in result.output

    @patch(PATCH_TARGET)
    def test_delete_provider_not_found(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "delete", "nonexistent", "--force"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_delete_api_error(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER]
        mock.remove_provider.side_effect = APIError("Server error", status_code=500)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "delete", "prov-001", "--force"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_update_no_options(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "update", "prov-001"])
        assert result.exit_code != 0
        assert "No updates specified" in result.output


# ---------------------------------------------------------------------------
# Flag tests
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH_TARGET)
    def test_delete_without_force_aborts(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "delete", "prov-001"], input="n\n")
        mock.remove_provider.assert_not_called()

    @patch(PATCH_TARGET)
    def test_update_with_api_key(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER]
        mock.update_provider.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "providers",
                "update",
                "prov-001",
                "--api-key",
                "sk-new",
            ],
        )
        assert result.exit_code == 0
        call_args = mock.update_provider.call_args
        assert "api_key" in call_args[0][1].get("integration", {})


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_list_table_shows_provider_names(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER, MOCK_PROVIDER_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 0
        assert "prov-001" in result.output
        assert "prov-002" in result.output

    @patch(PATCH_TARGET)
    def test_list_shows_model_info(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = [MOCK_PROVIDER]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 0
        assert "gpt-4o" in result.output

    @patch(PATCH_TARGET)
    def test_empty_providers_list(self, MockClient):
        mock = _make_client()
        mock.list_providers.return_value = []
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 0
        assert "No providers configured" in result.output
