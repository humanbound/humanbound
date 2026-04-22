"""Unit tests for the redteam command group.

Redteam is complex and interactive; these tests focus on auth guards,
subcommand routing, help text, and the non-interactive subcommands
(analyze, sessions).
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_EXPERIMENT,
    assert_exit_error,
    assert_exit_ok,
)

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.redteam.HumanboundClient"


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
    def test_help_text(self):
        result = runner.invoke(cli, ["redteam", "--help"])
        assert_exit_ok(result)
        assert "redteam" in result.output.lower()
        assert "analyze" in result.output.lower() or "sessions" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_analyze(self, MockClient):
        mock = _make_client()
        mock.post.return_value = {
            "summary": "Found 3 potential attack vectors.",
            "weak_spots": [
                {"area": "prompt_injection", "severity": "high", "reason": "No input validation"}
            ],
            "coverage_gaps": [],
            "recommended_strategies": [
                {"goal": "Bypass system prompt", "method": "Direct injection"}
            ],
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "analyze", "--experiment", "exp-789"])
        assert_exit_ok(result)
        mock.post.assert_called_once_with(
            "experiments/exp-789/actions/analyze",
            data={},
            include_project=True,
            timeout=120,
        )
        assert "Attack Surface" in result.output or "attack" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_sessions_with_active_sessions(self, MockClient):
        mock = _make_client()
        mock.get_experiment.return_value = {
            **MOCK_EXPERIMENT,
            "orchestrator_state": {
                "active_sessions": {
                    "sess-001": {
                        "user_id": "testuser",
                        "status": "active",
                        "turn_count": 5,
                        "strategy": {"goal": "Bypass prompt guard"},
                    }
                }
            },
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "sessions", "--experiment", "exp-789"])
        assert_exit_ok(result)
        mock.get_experiment.assert_called_once_with("exp-789")

    @patch(PATCH_TARGET)
    def test_sessions_no_active(self, MockClient):
        mock = _make_client()
        mock.get_experiment.return_value = {
            **MOCK_EXPERIMENT,
            "orchestrator_state": {"active_sessions": {}},
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "sessions", "--experiment", "exp-789"])
        assert_exit_ok(result)
        assert "No active sessions" in result.output

    def test_analyze_help(self):
        result = runner.invoke(cli, ["redteam", "analyze", "--help"])
        assert_exit_ok(result)
        assert "--experiment" in result.output

    def test_sessions_help(self):
        result = runner.invoke(cli, ["redteam", "sessions", "--help"])
        assert_exit_ok(result)
        assert "--experiment" in result.output


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_analyze_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "analyze", "--experiment", "exp-789"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_analyze_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "analyze", "--experiment", "exp-789"])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(PATCH_TARGET)
    def test_sessions_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "sessions", "--experiment", "exp-789"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_sessions_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "sessions", "--experiment", "exp-789"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_analyze_experiment_not_found(self, MockClient):
        mock = _make_client()
        mock.post.side_effect = APIError("Experiment not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "analyze", "--experiment", "nonexistent"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_sessions_experiment_not_found(self, MockClient):
        mock = _make_client()
        mock.get_experiment.side_effect = APIError("Experiment not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["redteam", "sessions", "--experiment", "nonexistent"])
        assert_exit_error(result)

    def test_analyze_missing_experiment_flag(self):
        """--experiment is required for analyze."""
        result = runner.invoke(cli, ["redteam", "analyze"])
        assert result.exit_code != 0

    def test_sessions_missing_experiment_flag(self):
        """--experiment is required for sessions."""
        result = runner.invoke(cli, ["redteam", "sessions"])
        assert result.exit_code != 0
