"""
Unit tests for `hb api-keys` commands.

Mocked HumanboundClient — no live API needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(__file__))

from conftest import MOCK_API_KEY

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.api_keys.HumanboundClient"


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
    def test_list_api_keys(self, MockClient):
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "list"])
        assert result.exit_code == 0
        assert "ci-pipeline" in result.output

    @patch(PATCH_TARGET)
    def test_list_api_keys_via_group_default(self, MockClient):
        """Invoking `api-keys` with no subcommand should list."""
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys"])
        assert result.exit_code == 0
        assert "ci-pipeline" in result.output

    @patch(PATCH_TARGET)
    def test_create_api_key(self, MockClient):
        mock = _make_client()
        mock.create_api_key.return_value = {"id": "key-new", "key": "hb_secret_xxx"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "create", "--name", "test-key"])
        assert result.exit_code == 0
        assert "hb_secret_xxx" in result.output
        mock.create_api_key.assert_called_once_with("test-key", "admin")

    @patch(PATCH_TARGET)
    def test_create_api_key_with_scopes(self, MockClient):
        mock = _make_client()
        mock.create_api_key.return_value = {"id": "key-new", "key": "hb_read_xxx"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "create", "--name", "reader", "--scopes", "read"])
        assert result.exit_code == 0
        mock.create_api_key.assert_called_once_with("reader", "read")

    @patch(PATCH_TARGET)
    def test_delete_api_key_with_force(self, MockClient):
        mock = _make_client()
        mock.delete_api_key.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "api-keys",
                "delete",
                "key-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",  # >= 32 chars
                "--force",
            ],
        )
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_update_api_key(self, MockClient):
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        mock.update_api_key.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "api-keys",
                "update",
                "key-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "--name",
                "renamed-key",
            ],
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_list_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "list"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_create_api_error(self, MockClient):
        mock = _make_client()
        mock.create_api_key.side_effect = APIError("Quota exceeded", status_code=429)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "create", "--name", "fail-key"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_delete_api_error(self, MockClient):
        mock = _make_client()
        mock.delete_api_key.side_effect = APIError("Not found", status_code=404)
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "api-keys",
                "delete",
                "key-bad-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "--force",
            ],
        )
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_create_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "create", "--name", "x"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output


# ---------------------------------------------------------------------------
# Flag tests
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH_TARGET)
    def test_list_json_output(self, MockClient):
        mock = _make_client()
        response_data = {"data": [MOCK_API_KEY]}
        mock.list_api_keys.return_value = response_data
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "data" in parsed

    @patch(PATCH_TARGET)
    def test_list_explicit_json_flag(self, MockClient):
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    @patch(PATCH_TARGET)
    def test_delete_without_force_aborts(self, MockClient):
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "api-keys",
                "delete",
                "key-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            ],
            input="n\n",
        )
        mock.delete_api_key.assert_not_called()


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_table_shows_key_name_and_scopes(self, MockClient):
        mock = _make_client()
        mock.list_api_keys.return_value = {"data": [MOCK_API_KEY]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "list"])
        assert result.exit_code == 0
        assert "ci-pipeline" in result.output
        assert "key-001" in result.output

    @patch(PATCH_TARGET)
    def test_create_shows_secret_key(self, MockClient):
        mock = _make_client()
        mock.create_api_key.return_value = {"id": "key-new", "key": "hb_secret_abc123"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "create", "--name", "my-key"])
        assert result.exit_code == 0
        assert "hb_secret_abc123" in result.output
        # Should warn the user to save it
        assert "not be shown again" in result.output.lower() or "Save" in result.output
