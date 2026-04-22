"""
Unit tests for `hb projects` commands.

Mocked HumanboundClient — no live API needed.
"""

import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

# Ensure conftest constants are importable
sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    MOCK_PROJECT,
)

from humanbound_cli.exceptions import APIError, NotAuthenticatedError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.projects.HumanboundClient"


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
    def test_list_projects(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "list"])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    @patch(PATCH_TARGET)
    def test_list_projects_via_group_default(self, MockClient):
        """Invoking `projects` with no subcommand should list."""
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects"])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    @patch(PATCH_TARGET)
    def test_use_project(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "use", "proj-456"])
        assert result.exit_code == 0
        assert "Switched to project" in result.output
        mock.set_project.assert_called_once_with("proj-456")

    @patch(PATCH_TARGET)
    def test_current_project(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "current"])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    @patch(PATCH_TARGET)
    def test_show_project(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "show", "proj-456"])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    @patch(PATCH_TARGET)
    def test_update_project(self, MockClient):
        mock = _make_client()
        mock.update_project.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "update", "proj-456", "--name", "Renamed"])
        assert result.exit_code == 0
        assert "Project updated" in result.output
        mock.update_project.assert_called_once_with("proj-456", {"name": "Renamed"})

    @patch(PATCH_TARGET)
    def test_delete_project_confirmed(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        mock.delete_project.return_value = {}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "delete", "proj-456", "--force"])
        assert result.exit_code == 0
        assert "Project deleted" in result.output
        mock.delete_project.assert_called_once_with("proj-456")

    @patch(PATCH_TARGET)
    def test_project_status(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {
            "project_name": "My Agent",
            "active": False,
            "monitoring": "off",
            "running_experiments": 0,
            "posture_grade": "C",
            "posture_score": 72.5,
            "experiments": [],
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "status"])
        assert result.exit_code == 0
        assert "Idle" in result.output or "My Agent" in result.output


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_list_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.list_projects.side_effect = NotAuthenticatedError("Not authenticated")
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "list"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_use_project_not_found(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "use", "nonexistent-id"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_show_project_api_error(self, MockClient):
        mock = _make_client()
        mock.get.side_effect = APIError("Not found", status_code=404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "show", "bad-id"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_delete_project_api_error(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        mock.delete_project.side_effect = APIError("Forbidden", status_code=403)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "delete", "proj-456", "--force"])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch(PATCH_TARGET)
    def test_status_no_project_selected(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "status"])
        assert result.exit_code != 0
        assert "No project selected" in result.output


# ---------------------------------------------------------------------------
# Flag / pagination tests
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH_TARGET)
    def test_list_with_pagination(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "list", "--page", "2", "--size", "5"])
        assert result.exit_code == 0
        mock.list_projects.assert_called_once_with(page=2, size=5)

    @patch(PATCH_TARGET)
    def test_delete_without_force_aborts(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        # Provide "n" to the confirmation prompt
        result = runner.invoke(cli, ["projects", "delete", "proj-456"], input="n\n")
        # Should not call delete_project
        mock.delete_project.assert_not_called()


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_list_table_contains_project_name(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "list"])
        assert result.exit_code == 0
        assert "My Agent" in result.output
        assert "proj-456" in result.output

    @patch(PATCH_TARGET)
    def test_current_shows_project_id(self, MockClient):
        mock = _make_client()
        mock.list_projects.return_value = {"data": [MOCK_PROJECT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "current"])
        assert result.exit_code == 0
        assert "proj-456" in result.output
