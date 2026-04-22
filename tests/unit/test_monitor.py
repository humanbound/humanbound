"""Unit tests for the monitor command."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_PROJECT,
    assert_exit_error,
    assert_exit_ok,
    assert_valid_json,
)

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.monitor.HumanboundClient"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestHappyPath:
    @patch(PATCH_TARGET)
    def test_monitor_status(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with("projects/proj-456", include_project=False)

    @patch(PATCH_TARGET)
    def test_monitor_status_json(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--json"])
        data = assert_valid_json(result)
        assert data["id"] == "proj-456"
        assert "ascam_paused" in data

    @patch(PATCH_TARGET)
    def test_monitor_pause(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--pause"])
        assert_exit_ok(result)
        mock.put.assert_called_once_with(
            "projects/proj-456/ascam/pause",
            data={"paused": True},
        )
        assert "paused" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_monitor_resume(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--resume"])
        assert_exit_ok(result)
        mock.put.assert_called_once_with(
            "projects/proj-456/ascam/pause",
            data={"paused": False},
        )
        assert "resumed" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_monitor_with_project_override(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--project", "proj-other"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with("projects/proj-other", include_project=False)


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor"])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(PATCH_TARGET)
    def test_pause_and_resume_together(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--pause", "--resume"])
        assert_exit_error(result)
        assert "Cannot use --pause and --resume together" in result.output

    @patch(PATCH_TARGET)
    def test_pause_api_error(self, MockClient):
        mock = _make_client()
        mock.put.side_effect = APIError("Permission denied", 403)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--pause"])
        assert_exit_error(result)
        assert "Permission denied" in result.output

    @patch(PATCH_TARGET)
    def test_resume_api_error(self, MockClient):
        mock = _make_client()
        mock.put.side_effect = APIError("Server error", 500)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--resume"])
        assert_exit_error(result)
        assert "Server error" in result.output

    @patch(PATCH_TARGET)
    def test_status_api_error(self, MockClient):
        mock = _make_client()
        mock.get.side_effect = APIError("Not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor"])
        assert_exit_error(result)


class TestFlags:
    @patch(PATCH_TARGET)
    def test_project_flag_overrides_current(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "-p", "proj-override"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with("projects/proj-override", include_project=False)

    @patch(PATCH_TARGET)
    def test_json_flag(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_PROJECT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--json"])
        data = assert_valid_json(result)
        assert isinstance(data, dict)

    @patch(PATCH_TARGET)
    def test_pause_with_project_flag(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor", "--pause", "-p", "proj-other"])
        assert_exit_ok(result)
        mock.put.assert_called_once_with(
            "projects/proj-other/ascam/pause",
            data={"paused": True},
        )
