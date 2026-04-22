"""
Unit tests for the `hb posture` command.

Mocked HumanboundClient — no live API needed.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import (
    MOCK_POSTURE_TRENDS,
    assert_exit_ok,
    assert_valid_json,
    platform_runner,
)

from humanbound_cli.exceptions import APIError, NotAuthenticatedError
from humanbound_cli.main import cli

RUNNER_PATCH = "humanbound_cli.commands.posture.get_runner"
runner = CliRunner()

# Build a full posture response as the API returns it
POSTURE_RESPONSE = {
    "overall_score": 72.5,
    "grade": "C",
    "finding_metrics": {"score": 65.0, "avg_confidence": 70.0},
    "coverage_metrics": {"score": 80.0},
    "resilience_metrics": {"score": 85.0},
    "recommendations": ["Address failing security tests"],
    "last_tested": "2025-06-01",
}

ORG_POSTURE_RESPONSE = {
    "score": 72.5,
    "grade": "C",
    "dimensions": {
        "agent_security": {"score": 65.0},
        "shadow_ai": {"score": 80.0},
        "quality": {"score": 70.0},
    },
}

TRENDS_RESPONSE = {
    "snapshots": MOCK_POSTURE_TRENDS,
}

COVERAGE_RESPONSE = {
    "overall_coverage": 75.0,
    "categories": [
        {"category": "prompt_injection", "total": 20, "pass": 15},
        {"category": "data_leakage", "total": 10, "pass": 8},
    ],
    "gaps": ["tool_abuse", "social_engineering"],
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


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(RUNNER_PATCH)
    def test_basic_posture(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert_exit_ok(result)
        assert "72" in result.output or "C" in result.output

    @patch(RUNNER_PATCH)
    def test_json_output(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--json"])
        data = assert_valid_json(result)
        assert data.get("overall_score") == 72.5

    @patch(RUNNER_PATCH)
    def test_trends(self, mock_get_runner):
        mock = _make_client()
        mock.get_posture_trends.return_value = TRENDS_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--trends"])
        assert_exit_ok(result)
        assert "History" in result.output or "60" in result.output

    @patch(RUNNER_PATCH)
    def test_trends_json(self, mock_get_runner):
        mock = _make_client()
        mock.get_posture_trends.return_value = TRENDS_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--trends", "--json"])
        data = assert_valid_json(result)
        assert "snapshots" in data

    @patch(RUNNER_PATCH)
    def test_org_posture(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = ORG_POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--org"])
        assert_exit_ok(result)
        assert "Organisation" in result.output or "72" in result.output

    @patch(RUNNER_PATCH)
    def test_org_posture_json(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = ORG_POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--org", "--json"])
        data = assert_valid_json(result)
        assert data.get("score") == 72.5

    @patch(RUNNER_PATCH)
    def test_coverage_flag(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock.get_coverage.return_value = COVERAGE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--coverage"])
        assert_exit_ok(result)
        assert "Coverage" in result.output or "75" in result.output


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(RUNNER_PATCH)
    def test_not_authenticated(self, mock_get_runner):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        mock.get.side_effect = NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(RUNNER_PATCH)
    def test_no_project(self, mock_get_runner):
        mock = _make_client()
        mock.project_id = None
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert result.exit_code != 0
        assert "No project" in result.output

    @patch(RUNNER_PATCH)
    def test_org_no_org(self, mock_get_runner):
        mock = _make_client()
        mock.organisation_id = None
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--org"])
        assert result.exit_code != 0
        assert "organisation" in result.output.lower() or "org" in result.output.lower()

    @patch(RUNNER_PATCH)
    def test_api_error(self, mock_get_runner):
        mock = _make_client()
        mock.get.side_effect = APIError("Server error", 500)
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(RUNNER_PATCH)
    def test_project_flag(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--project", "proj-other"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "projects/proj-other/posture",
            include_project=True,
        )

    @patch(RUNNER_PATCH)
    def test_org_calls_correct_endpoint(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = ORG_POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--org"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with(
            "organisations/org-123/posture",
            include_project=False,
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(RUNNER_PATCH)
    def test_help_text(self, mock_get_runner):
        result = runner.invoke(cli, ["posture", "--help"])
        assert_exit_ok(result)
        assert "posture" in result.output.lower()

    @patch(RUNNER_PATCH)
    def test_displays_grade(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert_exit_ok(result)
        assert "C" in result.output

    @patch(RUNNER_PATCH)
    def test_displays_score(self, mock_get_runner):
        mock = _make_client()
        mock.get.return_value = POSTURE_RESPONSE
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert_exit_ok(result)
        assert "72" in result.output
