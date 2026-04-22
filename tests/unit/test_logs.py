"""
Unit tests for the `hb logs` command group.

All mocked — no live API. The command accesses the API via `get_runner().client`,
so we patch `get_runner` and wire in a mock client through the shared
`platform_runner(client)` helper.
"""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import (
    MOCK_EXPERIMENT,
    MOCK_LOG,
    MOCK_LOG_PASS,
    assert_exit_ok,
    platform_runner,
)

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

RUNNER_PATCH = "humanbound_cli.commands.logs.get_runner"
runner = CliRunner()

LOGS_RESPONSE = {
    "data": [MOCK_LOG, MOCK_LOG_PASS],
    "total": 2,
    "has_next_page": False,
}

LOGS_EMPTY = {
    "data": [],
    "total": 0,
    "has_next_page": False,
}


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    m.get_project_logs.return_value = LOGS_RESPONSE
    m.get_experiment_logs.return_value = LOGS_RESPONSE
    m.list_experiments.return_value = {
        "data": [MOCK_EXPERIMENT],
        "total": 1,
        "has_next_page": False,
    }
    m.get_experiment.return_value = MOCK_EXPERIMENT
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(RUNNER_PATCH)
    def test_project_logs_default(self, mock_get_runner):
        """No experiment_id — uses most recent experiment."""
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs"])

        assert_exit_ok(result)
        # Should resolve the most recent experiment from list_experiments
        client.list_experiments.assert_called()

    @patch(RUNNER_PATCH)
    def test_experiment_logs(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "exp-789"])

        assert_exit_ok(result)
        client.get_experiment_logs.assert_called_once_with(
            "exp-789",
            page=1,
            size=50,
            result=None,
        )

    @patch(RUNNER_PATCH)
    def test_empty_logs(self, mock_get_runner):
        client = _make_client()
        client.get_experiment_logs.return_value = LOGS_EMPTY
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "exp-789"])

        assert_exit_ok(result)
        assert "No logs" in result.output

    @patch(RUNNER_PATCH)
    def test_project_level_last_n(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--last", "3"])

        assert_exit_ok(result)
        client.get_project_logs.assert_called_once()
        call_kwargs = client.get_project_logs.call_args[1]
        assert call_kwargs.get("last") == 3


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(RUNNER_PATCH)
    def test_not_authenticated(self, mock_get_runner):
        client = _make_client()
        client.is_authenticated.return_value = False
        client.list_experiments.side_effect = __import__(
            "humanbound_cli.exceptions", fromlist=["NotAuthenticatedError"]
        ).NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs"])

        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(RUNNER_PATCH)
    def test_no_project(self, mock_get_runner):
        client = _make_client()
        client.project_id = None
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs"])

        assert result.exit_code != 0
        assert "No project" in result.output

    @patch(RUNNER_PATCH)
    def test_experiment_api_error(self, mock_get_runner):
        client = _make_client()
        client.get_experiment_logs.side_effect = APIError("Not found", 404)
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "exp-bad"])

        assert result.exit_code != 0

    @patch(RUNNER_PATCH)
    def test_no_experiments_found(self, mock_get_runner):
        client = _make_client()
        client.list_experiments.return_value = {
            "data": [],
            "total": 0,
            "has_next_page": False,
        }
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs"])

        assert result.exit_code != 0
        assert "No experiments" in result.output


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(RUNNER_PATCH)
    def test_verdict_pass(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--verdict", "pass", "exp-789"])

        assert_exit_ok(result)
        client.get_experiment_logs.assert_called_once_with(
            "exp-789",
            page=1,
            size=50,
            result="pass",
        )

    @patch(RUNNER_PATCH)
    def test_verdict_fail(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--verdict", "fail", "exp-789"])

        assert_exit_ok(result)
        client.get_experiment_logs.assert_called_once_with(
            "exp-789",
            page=1,
            size=50,
            result="fail",
        )

    @patch(RUNNER_PATCH)
    def test_page_and_size(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--page", "2", "--size", "10", "exp-789"])

        assert_exit_ok(result)
        client.get_experiment_logs.assert_called_once_with(
            "exp-789",
            page=2,
            size=10,
            result=None,
        )

    @patch(RUNNER_PATCH)
    def test_category_filter(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--category", "adversarial"])

        assert_exit_ok(result)
        client.get_project_logs.assert_called_once()
        call_kwargs = client.get_project_logs.call_args[1]
        assert call_kwargs.get("test_category") == "adversarial"

    @patch(RUNNER_PATCH)
    def test_from_until_filter(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(
            cli,
            [
                "logs",
                "--from",
                "2025-01-01",
                "--until",
                "2025-06-01",
            ],
        )

        assert_exit_ok(result)
        client.get_project_logs.assert_called_once()
        call_kwargs = client.get_project_logs.call_args[1]
        assert call_kwargs.get("from_date") == "2025-01-01"
        assert call_kwargs.get("until_date") == "2025-06-01"

    @patch(RUNNER_PATCH)
    def test_days_shortcut(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--days", "7"])

        assert_exit_ok(result)
        client.get_project_logs.assert_called_once()
        call_kwargs = client.get_project_logs.call_args[1]
        assert call_kwargs.get("from_date") is not None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_help_text(self):
        # --help short-circuits before any runner is built; no patching needed.
        result = runner.invoke(cli, ["logs", "--help"])
        assert_exit_ok(result)
        assert "logs" in result.output.lower()

    @patch(RUNNER_PATCH)
    def test_json_format(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "--format", "json", "exp-789"])

        assert_exit_ok(result)
        data = json.loads(result.output)
        assert "logs" in data or "data" in data

    @patch(RUNNER_PATCH)
    def test_json_output_to_file(self, mock_get_runner, tmp_path):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        outfile = str(tmp_path / "logs.json")
        result = runner.invoke(
            cli,
            [
                "logs",
                "--format",
                "json",
                "--output",
                outfile,
                "exp-789",
            ],
        )

        assert_exit_ok(result)
        data = json.loads((tmp_path / "logs.json").read_text())
        assert "logs" in data or "data" in data

    @patch(RUNNER_PATCH)
    def test_table_shows_verdict(self, mock_get_runner):
        client = _make_client()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["logs", "exp-789"])

        assert_exit_ok(result)
        assert "pass" in result.output.lower() or "fail" in result.output.lower()
