"""
Unit tests for the `hb findings` command group.

Mocked HumanboundClient — no live API needed.
"""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import (
    MOCK_FINDING,
    MOCK_FINDING_2,
    assert_exit_ok,
    assert_valid_json,
)

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

PATCH = "humanbound_cli.commands.findings.HumanboundClient"
runner = CliRunner()

FINDINGS_RESPONSE = {
    "data": [MOCK_FINDING, MOCK_FINDING_2],
    "total": 2,
    "has_next_page": False,
}

FINDINGS_EMPTY = {
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
    m.list_findings.return_value = FINDINGS_RESPONSE
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(PATCH)
    def test_list_with_data(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert_exit_ok(result)
        # Rich table truncates IDs/titles; check for table header or severity
        assert "Findings" in result.output or "high" in result.output.lower()

    @patch(PATCH)
    def test_list_empty(self, MockCls):
        mock = _make_client()
        mock.list_findings.return_value = FINDINGS_EMPTY
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert_exit_ok(result)
        assert "No findings" in result.output

    @patch(PATCH)
    def test_json_output(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "--json"])
        assert_exit_ok(result)
        data = json.loads(result.output)
        assert "data" in data
        assert len(data["data"]) == 2

    @patch(PATCH)
    def test_output_to_file(self, MockCls, tmp_path):
        mock = _make_client()
        MockCls.return_value = mock
        outfile = str(tmp_path / "findings.json")
        result = runner.invoke(cli, ["findings", "--output", outfile])
        assert_exit_ok(result)
        import pathlib

        content = pathlib.Path(outfile).read_text()
        data = json.loads(content)
        assert "data" in data

    @patch(PATCH)
    def test_update_status(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "update", "find-001", "--status", "fixed"])
        assert_exit_ok(result)
        mock.update_finding.assert_called_once()
        call_args = mock.update_finding.call_args
        assert call_args[0][2].get("status") == "fixed"

    @patch(PATCH)
    def test_assign_finding(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "assign", "find-001", "--assignee", "mem-001"])
        assert_exit_ok(result)
        mock.update_finding.assert_called_once()
        call_args = mock.update_finding.call_args
        assert call_args[0][2].get("assignee_id") == "mem-001"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH)
    def test_not_authenticated(self, MockCls):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH)
    def test_no_project(self, MockCls):
        mock = _make_client()
        mock.project_id = None
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert result.exit_code != 0
        assert "No project" in result.output

    @patch(PATCH)
    def test_api_error(self, MockCls):
        mock = _make_client()
        mock.list_findings.side_effect = APIError("Server error", 500)
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert result.exit_code != 0

    @patch(PATCH)
    def test_update_not_authenticated(self, MockCls):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "update", "find-001", "--status", "fixed"])
        assert result.exit_code != 0

    @patch(PATCH)
    def test_update_no_flags(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "update", "find-001"])
        assert result.exit_code != 0
        assert "Nothing to update" in result.output


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH)
    def test_filter_status_open(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "--status", "open"])
        assert_exit_ok(result)
        mock.list_findings.assert_called_once_with(
            "proj-456",
            status="open",
            severity=None,
            page=1,
            size=20,
        )

    @patch(PATCH)
    def test_filter_severity_high(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "--severity", "high"])
        assert_exit_ok(result)
        mock.list_findings.assert_called_once_with(
            "proj-456",
            status=None,
            severity="high",
            page=1,
            size=20,
        )

    @patch(PATCH)
    def test_page_and_size(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "--page", "3", "--size", "5"])
        assert_exit_ok(result)
        mock.list_findings.assert_called_once_with(
            "proj-456",
            status=None,
            severity=None,
            page=3,
            size=5,
        )

    @patch(PATCH)
    def test_assign_delegation_status(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(
            cli,
            [
                "findings",
                "assign",
                "find-001",
                "--assignee",
                "mem-001",
                "--delegation-status",
                "in_progress",
            ],
        )
        assert_exit_ok(result)
        call_args = mock.update_finding.call_args
        assert call_args[0][2].get("delegation_status") == "in_progress"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH)
    def test_help_text(self, MockCls):
        result = runner.invoke(cli, ["findings", "--help"])
        assert_exit_ok(result)
        assert "findings" in result.output.lower()

    @patch(PATCH)
    def test_table_shows_severity(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert_exit_ok(result)
        # Should show severity column content
        assert "high" in result.output.lower() or "medium" in result.output.lower()

    @patch(PATCH)
    def test_json_is_valid(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "--json"])
        data = assert_valid_json(result)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Regression retest (retest + regressions)
# ---------------------------------------------------------------------------


RETEST_RESPONSE = {"experiment_id": "exp-reg-1", "status": "running"}

REGRESSIONS_HISTORY = [
    {
        "experiment_id": "exp-reg-2",
        "outcome": "not_reproduced",
        "partial": False,
        "testing_level": "unit",
        "created_at": "2026-07-19T10:00:00Z",
    },
    {
        "experiment_id": "exp-reg-1",
        "outcome": "still_vulnerable",
        "partial": True,
        "testing_level": "system",
        "created_at": "2026-07-18T09:00:00Z",
    },
]


class TestRetest:
    @patch(PATCH)
    def test_fire_and_return(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001"])
        assert_exit_ok(result)
        assert "exp-reg-1" in result.output
        mock.retest_finding.assert_called_once_with("find-001", testing_level="unit")
        # Fire-and-return must NOT poll.
        mock.get_experiment_status.assert_not_called()

    @patch(PATCH)
    def test_testing_level_passed(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        MockCls.return_value = mock
        result = runner.invoke(
            cli, ["findings", "retest", "find-001", "--testing-level", "acceptance"]
        )
        assert_exit_ok(result)
        mock.retest_finding.assert_called_once_with("find-001", testing_level="acceptance")

    @patch(PATCH)
    def test_deep_shortcut_maps_to_system(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--deep"])
        assert_exit_ok(result)
        mock.retest_finding.assert_called_once_with("find-001", testing_level="system")

    @patch(PATCH)
    def test_full_shortcut_maps_to_acceptance(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--full"])
        assert_exit_ok(result)
        mock.retest_finding.assert_called_once_with("find-001", testing_level="acceptance")

    @patch(PATCH)
    def test_invalid_testing_level_rejected(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--testing-level", "bogus"])
        assert result.exit_code != 0

    @patch(PATCH)
    def test_json_fire_and_return(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--json"])
        assert_exit_ok(result)
        data = json.loads(result.output)
        assert data["experiment_id"] == "exp-reg-1"

    @patch(PATCH)
    def test_watch_clean_outcome(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        mock.get_experiment_status.return_value = {"status": "Finished"}
        mock.get_experiment.return_value = {
            "results": {"regression": {"outcome": "not_reproduced", "partial": False}}
        }
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--watch"])
        assert_exit_ok(result)
        assert "not_reproduced" in result.output
        mock.get_experiment_status.assert_called()

    @patch(PATCH)
    def test_watch_still_vulnerable_exits_nonzero(self, MockCls):
        mock = _make_client()
        mock.retest_finding.return_value = RETEST_RESPONSE
        mock.get_experiment_status.return_value = {"status": "Finished"}
        mock.get_experiment.return_value = {
            "results": {"regression": {"outcome": "still_vulnerable"}}
        }
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001", "--watch"])
        assert result.exit_code != 0
        assert "still_vulnerable" in result.output

    @patch(PATCH)
    def test_not_authenticated(self, MockCls):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH)
    def test_no_project(self, MockCls):
        mock = _make_client()
        mock.project_id = None
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001"])
        assert result.exit_code != 0
        assert "No project" in result.output

    @patch(PATCH)
    def test_api_error(self, MockCls):
        mock = _make_client()
        mock.retest_finding.side_effect = APIError("Server error", 500)
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "retest", "find-001"])
        assert result.exit_code != 0


class TestRegressions:
    @patch(PATCH)
    def test_history_table(self, MockCls):
        mock = _make_client()
        mock.list_finding_regressions.return_value = REGRESSIONS_HISTORY
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "regressions", "find-001"])
        assert_exit_ok(result)
        assert "not_reproduced" in result.output
        mock.list_finding_regressions.assert_called_once_with("find-001")

    @patch(PATCH)
    def test_history_empty(self, MockCls):
        mock = _make_client()
        mock.list_finding_regressions.return_value = []
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "regressions", "find-001"])
        assert_exit_ok(result)
        assert "never been retested" in result.output

    @patch(PATCH)
    def test_history_json(self, MockCls):
        mock = _make_client()
        mock.list_finding_regressions.return_value = REGRESSIONS_HISTORY
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "regressions", "find-001", "--json"])
        assert_exit_ok(result)
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2

    @patch(PATCH)
    def test_api_error(self, MockCls):
        mock = _make_client()
        mock.list_finding_regressions.side_effect = APIError("Server error", 500)
        MockCls.return_value = mock
        result = runner.invoke(cli, ["findings", "regressions", "find-001"])
        assert result.exit_code != 0
