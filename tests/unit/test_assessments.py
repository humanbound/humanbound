"""Unit tests for the assessments command group."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.commands.assessments import ACTIVITY_STYLES, STATUS_STYLES
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
    def test_show_renders_pending_status_and_custom_activity(self, MockClient):
        """status='pending' + activity='custom' (the draft/compose-then-run
        case) render via the style dicts without KeyError."""
        mock = _make_client()
        data = {**MOCK_ASSESSMENT, "status": "pending", "activity": "custom"}
        mock.get.return_value = data
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "show", "asmnt-001"], env={"COLUMNS": "220"})
        assert_exit_ok(result)
        assert "pending" in result.output
        assert "custom" in result.output

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


class TestCreateAssessment:
    @patch(PATCH_TARGET)
    def test_create_success(self, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        with patch(
            "humanbound_cli.commands.assessments.Confirm.ask", return_value=True
        ) as mock_confirm:
            result = runner.invoke(cli, ["assessments", "create", "-t", "t1,t2,t3"])
        assert_exit_ok(result)
        mock.create_assessment.assert_called_once_with("proj-456", ["t1", "t2", "t3"], level=None)
        mock_confirm.assert_called_once()
        assert "with 3 test categories" in mock_confirm.call_args[0][0]
        assert "level: default" in mock_confirm.call_args[0][0]
        out = result.output
        assert "Assessment started" in out
        assert "asmnt-1" in out
        assert "Next:" in out
        assert "hb assessments show asmnt-1" in out
        assert "hb findings" in out

    @patch(PATCH_TARGET)
    def test_create_with_level(self, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        with patch(
            "humanbound_cli.commands.assessments.Confirm.ask", return_value=True
        ) as mock_confirm:
            result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "-l", "UNIT"])
        assert_exit_ok(result)
        mock.create_assessment.assert_called_once_with("proj-456", ["t1"], level="unit")
        assert "level: unit" in mock_confirm.call_args[0][0]

    @patch(PATCH_TARGET)
    def test_create_yes_skips_confirm(self, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        with patch("humanbound_cli.commands.assessments.Confirm.ask") as mock_confirm:
            result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes"])
        assert_exit_ok(result)
        mock_confirm.assert_not_called()
        mock.create_assessment.assert_called_once_with("proj-456", ["t1"], level=None)

    @patch(PATCH_TARGET)
    def test_create_confirm_declined(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        with patch("humanbound_cli.commands.assessments.Confirm.ask", return_value=False):
            result = runner.invoke(cli, ["assessments", "create", "-t", "t1"])
        assert_exit_ok(result)
        mock.create_assessment.assert_not_called()
        assert "Cancelled" in result.output

    @patch(PATCH_TARGET)
    def test_create_category_parsing_skips_blank_tokens(self, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1,,  ,t2,", "--yes"])
        assert_exit_ok(result)
        mock.create_assessment.assert_called_once_with("proj-456", ["t1", "t2"], level=None)

    @patch(PATCH_TARGET)
    def test_create_accepts_repeated_flag_and_dedupes(self, MockClient):
        """-t may be repeated or comma-separated; order is kept, duplicates dropped."""
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            ["assessments", "create", "-t", "cat/a,cat/b", "-t", "cat/c", "-t", "cat/a", "--yes"],
        )
        assert_exit_ok(result)
        mock.create_assessment.assert_called_once_with(
            "proj-456", ["cat/a", "cat/b", "cat/c"], level=None
        )

    @patch(PATCH_TARGET)
    def test_create_categories_empty_after_parsing_errors(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", " , ,", "--yes"])
        assert_exit_error(result)
        mock.create_assessment.assert_not_called()

    @patch(PATCH_TARGET)
    def test_create_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_create_no_project(self, MockClient):
        mock = _make_client(project_id=None, _project_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes"])
        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(PATCH_TARGET)
    def test_create_conflict_surfaces_server_message(self, MockClient):
        mock = _make_client()
        mock.create_assessment.side_effect = APIError(
            "Assessment already running (id: other-1); rerun after it finishes", 409
        )
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes"])
        assert_exit_error(result)
        assert "already running" in result.output

    @patch(PATCH_TARGET)
    def test_create_api_error(self, MockClient):
        mock = _make_client()
        mock.create_assessment.side_effect = APIError("Server error", 500)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes"])
        assert_exit_error(result)
        assert "Server error" in result.output

    @patch(PATCH_TARGET)
    def test_create_json_requires_yes(self, MockClient):
        MockClient.return_value = _make_client()
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--json"])
        assert_exit_error(result)
        data = json.loads(result.output.strip())
        assert data["error"] == "create requires --yes in --json mode"
        MockClient.assert_not_called()

    @patch(PATCH_TARGET)
    def test_create_json_requires_yes_before_category_validation(self, MockClient):
        """The --json/--yes guard runs before category parsing, so an invalid
        --test-category (e.g. all-blank) still yields a pure JSON error envelope
        instead of the rich-text empty-tests error."""
        result = runner.invoke(cli, ["assessments", "create", "-t", ",,", "--json"])
        assert_exit_error(result)
        data = json.loads(result.output.strip())
        assert data["error"] == "create requires --yes in --json mode"
        MockClient.assert_not_called()

    @patch(PATCH_TARGET)
    def test_create_json_with_yes(self, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--json", "--yes"])
        data = assert_valid_json(result)
        assert data["assessment_id"] == "asmnt-1"
        assert "Assessment started" not in result.output

    @patch(PATCH_TARGET)
    @patch("humanbound_cli.commands.assessments.time.sleep")
    def test_create_wait_reaches_completed(self, mock_sleep, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        mock.get_assessment.side_effect = [
            {"id": "asmnt-1", "status": "running", "test_count": 10},
            {
                "id": "asmnt-1",
                "status": "completed",
                "test_count": 10,
                "posture_before": {"posture": 60.0, "grade": "C"},
                "posture_after": {"posture": 72.5, "grade": "B"},
            },
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes", "--wait"])
        assert_exit_ok(result)
        assert mock.get_assessment.call_count == 2
        mock.get_assessment.assert_called_with("proj-456", "asmnt-1")
        mock_sleep.assert_called_once_with(10)
        assert "completed" in result.output.lower()

    @patch(PATCH_TARGET)
    @patch("humanbound_cli.commands.assessments.time.sleep")
    def test_create_wait_reaches_broken(self, mock_sleep, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        mock.get_assessment.return_value = {"id": "asmnt-1", "status": "broken", "test_count": 3}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "create", "-t", "t1", "--yes", "--wait"])
        assert_exit_error(result)
        assert "broken" in result.output.lower()

    @patch(PATCH_TARGET)
    @patch("humanbound_cli.commands.assessments.time.sleep")
    def test_create_wait_and_json_prints_final_detail(self, mock_sleep, MockClient):
        mock = _make_client()
        mock.create_assessment.return_value = {"assessment_id": "asmnt-1", "status": "running"}
        mock.get_assessment.return_value = {
            "id": "asmnt-1",
            "status": "completed",
            "test_count": 10,
        }
        MockClient.return_value = mock
        result = runner.invoke(
            cli, ["assessments", "create", "-t", "t1", "--yes", "--json", "--wait"]
        )
        data = assert_valid_json(result)
        assert data["status"] == "completed"


CUSTOM_DETAIL = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "activity": "custom",
    "discovery_plan": {
        "entries": [
            {"orchestrator": "humanbound/adversarial/autonomous_red_team", "level": "system"},
            {"orchestrator": "humanbound/behavioral/tone", "level": "system"},
        ]
    },
}


class TestCloneAssessment:
    @patch(PATCH_TARGET)
    def test_clone_success(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = CUSTOM_DETAIL
        mock.create_assessment.return_value = {"assessment_id": "asmnt-2", "status": "running"}
        MockClient.return_value = mock
        with patch(
            "humanbound_cli.commands.assessments.Confirm.ask", return_value=True
        ) as mock_confirm:
            result = runner.invoke(cli, ["assessments", "clone", CUSTOM_DETAIL["id"]])
        assert_exit_ok(result)
        mock.get_assessment.assert_called_once_with("proj-456", CUSTOM_DETAIL["id"])
        mock.create_assessment.assert_called_once_with(
            "proj-456",
            [
                "humanbound/adversarial/autonomous_red_team",
                "humanbound/behavioral/tone",
            ],
            level="system",
        )
        prompt = mock_confirm.call_args[0][0]
        assert "Clone assessment aaaaaaaa" in prompt
        assert "run 2 test categories" in prompt
        assert "level: system" in prompt
        assert "Assessment started" in result.output

    @patch(PATCH_TARGET)
    def test_clone_non_custom_refused(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = MOCK_ASSESSMENT  # activity: "investigate"
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "clone", "asmnt-001", "--yes"])
        assert_exit_error(result)
        assert "Only custom assessments can be cloned" in result.output
        mock.create_assessment.assert_not_called()

    @patch(PATCH_TARGET)
    def test_clone_mixed_levels_refused(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = {
            "id": "asmnt-src",
            "activity": "custom",
            "discovery_plan": {
                "entries": [
                    {"orchestrator": "orch-a", "level": "unit"},
                    {"orchestrator": "orch-b", "level": "acceptance"},
                ]
            },
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "clone", "asmnt-src", "--yes"])
        assert_exit_error(result)
        assert "mixed testing levels" in result.output
        assert "unit" in result.output
        assert "acceptance" in result.output
        mock.create_assessment.assert_not_called()

    @patch(PATCH_TARGET)
    def test_clone_empty_entries_refused(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = {
            "id": "asmnt-src",
            "activity": "custom",
            "discovery_plan": {"entries": []},
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "clone", "asmnt-src", "--yes"])
        assert_exit_error(result)
        mock.create_assessment.assert_not_called()

    @patch(PATCH_TARGET)
    def test_clone_malformed_entry_refused(self, MockClient):
        """A discovery-plan entry that isn't a dict, or is missing/blank
        'orchestrator', is treated as a malformed plan rather than raising
        a KeyError/TypeError."""
        mock = _make_client()
        mock.get_assessment.return_value = {
            "id": "asmnt-src",
            "activity": "custom",
            "discovery_plan": {
                "entries": [
                    {"orchestrator": "humanbound/adversarial/autonomous_red_team", "level": "unit"},
                    "not-a-dict",
                ]
            },
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "clone", "asmnt-src", "--yes"])
        assert_exit_error(result)
        assert "Assessment plan is malformed; cannot clone." in result.output
        mock.create_assessment.assert_not_called()

    @patch(PATCH_TARGET)
    def test_clone_json_requires_yes(self, MockClient):
        MockClient.return_value = _make_client()
        result = runner.invoke(cli, ["assessments", "clone", "asmnt-src", "--json"])
        assert_exit_error(result)
        data = json.loads(result.output.strip())
        assert data["error"] == "clone requires --yes in --json mode"
        MockClient.assert_not_called()

    @patch(PATCH_TARGET)
    def test_clone_json_with_yes(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = CUSTOM_DETAIL
        mock.create_assessment.return_value = {"assessment_id": "asmnt-2", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(
            cli, ["assessments", "clone", CUSTOM_DETAIL["id"], "--json", "--yes"]
        )
        data = assert_valid_json(result)
        assert data["assessment_id"] == "asmnt-2"
        assert "Assessment started" not in result.output

    @patch(PATCH_TARGET)
    def test_clone_yes_skips_confirm(self, MockClient):
        mock = _make_client()
        mock.get_assessment.return_value = CUSTOM_DETAIL
        mock.create_assessment.return_value = {"assessment_id": "asmnt-2", "status": "running"}
        MockClient.return_value = mock
        with patch("humanbound_cli.commands.assessments.Confirm.ask") as mock_confirm:
            result = runner.invoke(cli, ["assessments", "clone", CUSTOM_DETAIL["id"], "--yes"])
        assert_exit_ok(result)
        mock_confirm.assert_not_called()
        mock.create_assessment.assert_called_once()

    @patch(PATCH_TARGET)
    @patch("humanbound_cli.commands.assessments.time.sleep")
    def test_clone_wait_passthrough(self, mock_sleep, MockClient):
        """Proves clone exercises the same shared _submit_assessment path as create."""
        mock = _make_client()
        mock.get_assessment.side_effect = [
            CUSTOM_DETAIL,
            {"id": "asmnt-2", "status": "completed", "test_count": 2},
        ]
        mock.create_assessment.return_value = {"assessment_id": "asmnt-2", "status": "running"}
        MockClient.return_value = mock
        result = runner.invoke(
            cli, ["assessments", "clone", CUSTOM_DETAIL["id"], "--yes", "--wait"]
        )
        assert_exit_ok(result)
        mock.get_assessment.assert_called_with("proj-456", "asmnt-2")
        assert "completed" in result.output.lower()


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


class TestStyleDicts:
    def test_status_styles_cover_pending_and_broken(self):
        assert "pending" in STATUS_STYLES
        assert "broken" in STATUS_STYLES

    def test_activity_styles_cover_custom(self):
        assert "custom" in ACTIVITY_STYLES


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
