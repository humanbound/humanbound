"""Unit tests for the report command.

The standalone report_command (from humanbound_cli.commands.report) provides
--org, --json, and --assessment flags. It is tested directly since it may
not yet be registered at top level in main.py.
"""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.commands.report import report_command
from humanbound_cli.exceptions import APIError, NotAuthenticatedError

from .conftest import (
    assert_exit_error,
    assert_exit_ok,
    platform_runner,
)

runner = CliRunner()

RUNNER_PATCH = "humanbound_cli.commands.report.get_runner"

MOCK_REPORT_RESPONSE = {
    "html": "<html><body>Security Report</body></html>",
    "summary": {"score": 72.5, "grade": "C", "findings_count": 3},
}

MOCK_ORG_REPORT_RESPONSE = {
    "html": "<html><body>Org Report</body></html>",
    "summary": {"projects_count": 2, "avg_score": 68.0},
}


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
    @patch(RUNNER_PATCH)
    def test_project_report(self, mock_get_runner, tmp_path, monkeypatch):
        """Default report generates a file for the current project."""
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, [])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/report",
            include_project=True,
            params={},
        )
        assert "saved" in result.output.lower() or "Report" in result.output

    @patch(RUNNER_PATCH)
    def test_project_report_json(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--json"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/report",
            include_project=True,
            params={"format": "json"},
        )

    @patch(RUNNER_PATCH)
    def test_org_report(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_ORG_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--org"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "organisations/org-123/report",
            include_project=False,
            params={},
        )

    @patch(RUNNER_PATCH)
    def test_org_report_json(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_ORG_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--org", "--json"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "organisations/org-123/report",
            include_project=False,
            params={"format": "json"},
        )

    @patch(RUNNER_PATCH)
    def test_report_custom_output_path(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        outfile = str(tmp_path / "my-report.html")
        result = runner.invoke(report_command, ["-o", outfile])
        assert_exit_ok(result)
        import pathlib

        assert pathlib.Path(outfile).exists()

    @patch(RUNNER_PATCH)
    def test_json_writes_json_file(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--json"])
        assert_exit_ok(result)
        # Should write a .json file
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) >= 1
        content = json_files[0].read_text()
        data = json.loads(content)
        assert isinstance(data, dict)


class TestErrorCases:
    @patch(RUNNER_PATCH)
    def test_not_authenticated(self, mock_get_runner):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        mock.get.side_effect = NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, [])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(RUNNER_PATCH)
    def test_no_project(self, mock_get_runner):
        mock = _make_client(project_id=None, _project_id=None)
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, [])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(RUNNER_PATCH)
    def test_org_report_no_org(self, mock_get_runner):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--org"])
        assert_exit_error(result)
        assert "No organisation" in result.output

    @patch(RUNNER_PATCH)
    def test_api_error(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.side_effect = APIError("Report generation failed", 500)
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, [])
        assert_exit_error(result)
        assert "Report generation failed" in result.output

    @patch(RUNNER_PATCH)
    def test_assessment_report_no_project(self, mock_get_runner):
        mock = _make_client(project_id=None, _project_id=None)
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--assessment", "asmnt-001"])
        assert_exit_error(result)
        assert "No project selected" in result.output


class TestFlags:
    @patch(RUNNER_PATCH)
    def test_assessment_flag(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(report_command, ["--assessment", "asmnt-001"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-456/assessments/asmnt-001/report",
            include_project=True,
            params={},
        )

    @patch(RUNNER_PATCH)
    def test_output_flag(self, mock_get_runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock = _make_client()
        mock.get.return_value = MOCK_REPORT_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        outfile = str(tmp_path / "custom.html")
        result = runner.invoke(report_command, ["-o", outfile])
        assert_exit_ok(result)
        import pathlib

        assert pathlib.Path(outfile).exists()
