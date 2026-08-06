"""Unit tests for the assessments command group."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_ASSESSMENT,
    assert_exit_error,
    assert_exit_ok,
    assert_valid_json,
)

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.assessments.HumanboundClient"


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
    def test_list_assessments(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_ASSESSMENT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/assessments",
            params={"page": 1, "size": 20},
        )

    @patch(PATCH_TARGET)
    def test_list_shows_posture_drift_new_findings(self, MockClient):
        """The list renders posture grade+score, drift, and the renamed
        'New Findings' column from the real assessment shape."""
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_ASSESSMENT], "total": 1}
        MockClient.return_value = mock
        # Widen the console so the 8-column table doesn't truncate.
        result = runner.invoke(cli, ["assessments"], env={"COLUMNS": "220"})
        assert_exit_ok(result)
        out = result.output
        assert "New Findings" in out  # renamed column header
        assert "Domain" in out and "security" in out  # scope→domain
        assert "Posture" in out and "Drift" in out
        assert "B" in out and "72" in out  # posture grade + score
        assert "-0.08" in out  # drift
        assert "3" in out  # new-findings delta
        assert "2026-06-19" in out  # started/completed epoch rendered as date

    @patch(PATCH_TARGET)
    def test_list_assessments_empty(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [], "total": 0}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert_exit_ok(result)
        assert "No assessments found" in result.output

    @patch(PATCH_TARGET)
    def test_show_assessment(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_ASSESSMENT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with("projects/proj-456/assessments/asmnt-001")

    @patch(PATCH_TARGET)
    def test_show_renders_rich_card(self, MockClient):
        """The detail card adds info the list row can't: posture trajectory +
        trend, drift, coverage breadth, domain, and run duration."""
        mock = _make_client()
        mock.get.return_value = MOCK_ASSESSMENT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001"], env={"COLUMNS": "220"})
        assert_exit_ok(result)
        out = result.output
        assert "C" in out and "B" in out  # posture before → after grades
        assert "improved" in out  # trend (60 → 72)
        assert "Drift" in out
        assert "Coverage" in out and "acceptance" in out  # plan levels, no orchestrator names
        assert "security" in out  # domain
        assert "25m" in out  # duration (1517s)

    @patch(PATCH_TARGET)
    def test_show_defaults_to_latest(self, MockClient):
        """`hb assessments show` with no id resolves and renders the latest."""
        mock = _make_client()
        mock.get_campaign.return_value = {"id": "asmnt-001", "status": "completed"}
        mock.get.return_value = MOCK_ASSESSMENT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show"], env={"COLUMNS": "220"})
        assert_exit_ok(result)
        mock.get_campaign.assert_called_once_with("proj-456")
        mock.get.assert_called_once_with("projects/proj-456/assessments/asmnt-001")
        assert "improved" in result.output  # rich card rendered for the latest

    @patch(PATCH_TARGET)
    def test_terminate_latest(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"id": "camp-1", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "terminate", "--force"])
        assert_exit_ok(result)
        mock.terminate_campaign.assert_called_once_with("proj-456", "camp-1")

    @patch(PATCH_TARGET)
    def test_terminate_with_explicit_id(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "terminate", "abc-123", "--force"])
        assert_exit_ok(result)
        mock.terminate_campaign.assert_called_once_with("proj-456", "abc-123")
        mock.get_campaign.assert_not_called()  # explicit id ⇒ no lookup

    @patch(PATCH_TARGET)
    def test_terminate_none_active(self, MockClient):
        mock = _make_client()
        mock.get_campaign.return_value = {"id": "", "status": ""}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "terminate", "--force"])
        assert_exit_ok(result)
        assert "No active assessment" in result.output
        mock.terminate_campaign.assert_not_called()

    @patch(PATCH_TARGET)
    def test_list_json(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_ASSESSMENT], "total": 1}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "--json"])
        data = assert_valid_json(result)
        assert "data" in data

    @patch(PATCH_TARGET)
    def test_show_json(self, MockClient):
        mock = _make_client()
        mock.get.return_value = MOCK_ASSESSMENT
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001", "--json"])
        data = assert_valid_json(result)
        assert data["id"] == "asmnt-001"


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(PATCH_TARGET)
    def test_show_not_found(self, MockClient):
        mock = _make_client()
        mock.get.side_effect = APIError("Not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "nonexistent"])
        assert_exit_error(result)
        assert "Not found" in result.output

    @patch(PATCH_TARGET)
    def test_show_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_show_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_api_error_on_list(self, MockClient):
        mock = _make_client()
        mock.get.side_effect = APIError("Server error", 500)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert_exit_error(result)
        assert "Server error" in result.output


class TestFlags:
    @patch(PATCH_TARGET)
    def test_page_flag(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_ASSESSMENT], "total": 50}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "--page", "3"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/assessments",
            params={"page": 3, "size": 20},
        )

    @patch(PATCH_TARGET)
    def test_size_flag(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [], "total": 0}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "--size", "5"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/assessments",
            params={"page": 1, "size": 5},
        )

    @patch(PATCH_TARGET)
    def test_page_and_size_combined(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_ASSESSMENT], "total": 100}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "--page", "2", "--size", "10"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/assessments",
            params={"page": 2, "size": 10},
        )
