"""
Unit tests for `hb members` commands.

Mocked HumanboundClient — no live API needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(__file__))

from conftest import MOCK_MEMBER

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.members.HumanboundClient"


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
    def test_list_members(self, MockClient):
        mock = _make_client()
        mock.list_members.return_value = {"data": [MOCK_MEMBER]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "list"])
        assert result.exit_code == 0
        assert "alice@example.com" in result.output

    @patch(PATCH_TARGET)
    def test_list_members_via_group_default(self, MockClient):
        """Invoking `members` with no subcommand should list."""
        mock = _make_client()
        mock.list_members.return_value = {"data": [MOCK_MEMBER]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members"])
        assert result.exit_code == 0
        assert "alice@example.com" in result.output

    @patch(PATCH_TARGET)
    def test_invite_member(self, MockClient):
        mock = _make_client()
        mock.invite_member.return_value = {"id": "mem-new"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "invite", "bob@example.com", "--role", "admin"])
        assert result.exit_code == 0
        assert "Invitation sent" in result.output
        mock.invite_member.assert_called_once_with("bob@example.com", "admin")

    @patch(PATCH_TARGET)
    def test_delete_member_with_force(self, MockClient):
        mock = _make_client()
        mock.remove_member.return_value = {}
        # _resolve_member_id calls list_members for short IDs; use full-length ID
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "members",
                "delete",
                "mem-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",  # >= 32 chars to skip resolve
                "--force",
            ],
        )
        assert result.exit_code == 0
        assert "Member removed" in result.output

    @patch(PATCH_TARGET)
    def test_invite_member_default_role(self, MockClient):
        mock = _make_client()
        mock.invite_member.return_value = {"id": "mem-new"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "invite", "carol@example.com"])
        assert result.exit_code == 0
        mock.invite_member.assert_called_once_with("carol@example.com", "developer")


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_list_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "list"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_list_no_org(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "list"])
        assert result.exit_code != 0
        assert "No organisation selected" in result.output

    @patch(PATCH_TARGET)
    def test_invite_api_error(self, MockClient):
        mock = _make_client()
        mock.invite_member.side_effect = APIError("Validation failed", status_code=422)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "invite", "bad@example.com", "--role", "admin"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_delete_api_error(self, MockClient):
        mock = _make_client()
        mock.remove_member.side_effect = APIError("Not found", status_code=404)
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "members",
                "delete",
                "mem-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "--force",
            ],
        )
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_invite_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "invite", "x@example.com"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output


# ---------------------------------------------------------------------------
# Flag tests
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH_TARGET)
    def test_list_json_output(self, MockClient):
        mock = _make_client()
        response_data = {"data": [MOCK_MEMBER]}
        mock.list_members.return_value = response_data
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "data" in parsed

    @patch(PATCH_TARGET)
    def test_list_explicit_json_flag(self, MockClient):
        mock = _make_client()
        mock.list_members.return_value = {"data": [MOCK_MEMBER]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    @patch(PATCH_TARGET)
    def test_delete_without_force_aborts(self, MockClient):
        mock = _make_client()
        mock.list_members.return_value = {"data": [MOCK_MEMBER]}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "members",
                "delete",
                "mem-001-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            ],
            input="n\n",
        )
        mock.remove_member.assert_not_called()


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_table_shows_email_and_role(self, MockClient):
        mock = _make_client()
        mock.list_members.return_value = {"data": [MOCK_MEMBER]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "list"])
        assert result.exit_code == 0
        assert "alice@example.com" in result.output
        assert "admin" in result.output.lower()
