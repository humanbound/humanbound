"""Unit tests for the campaigns command group."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_CAMPAIGN,
    assert_exit_error,
    assert_exit_ok,
    assert_valid_json,
)

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.campaigns.HumanboundClient"


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
    def test_campaign_status(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = MOCK_CAMPAIGN
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert_exit_ok(result)
        mock.get_campaign.assert_called_once_with("proj-456")

    @patch(PATCH_TARGET)
    def test_campaign_status_json(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = MOCK_CAMPAIGN
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "--json"])
        data = assert_valid_json(result)
        assert data["id"] == "camp-001"

    @patch(PATCH_TARGET)
    def test_no_campaign_returns_error(self, MockClient):
        """When no campaign exists the API returns 404."""
        mock = _make_client()
        mock.get_campaign.side_effect = APIError("Not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert_exit_error(result)
        assert "Not found" in result.output

    @patch(PATCH_TARGET)
    def test_terminate_campaign(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"campaign": {"id": "camp-001", "status": "running"}}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_ok(result)
        mock.terminate_campaign.assert_called_once_with("proj-456", "camp-001")

    @patch(PATCH_TARGET)
    def test_terminate_already_completed(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"campaign": {"id": "camp-001", "status": "completed"}}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_ok(result)
        assert "already completed" in result.output
        mock.terminate_campaign.assert_not_called()


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(PATCH_TARGET)
    def test_terminate_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_terminate_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_terminate_api_error(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"campaign": {"id": "camp-001", "status": "running"}}
        mock.terminate_campaign.side_effect = APIError("Terminate failed", 500)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_error(result)
        assert "Terminate failed" in result.output

    @patch(PATCH_TARGET)
    def test_terminate_no_active_campaign(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"campaign": {"id": "", "status": ""}}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "terminate", "--force"])
        assert_exit_ok(result)
        assert "No active campaign" in result.output
        mock.terminate_campaign.assert_not_called()


class TestFlags:
    @patch(PATCH_TARGET)
    def test_json_flag(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = MOCK_CAMPAIGN
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns", "--json"])
        data = assert_valid_json(result)
        assert "status" in data
