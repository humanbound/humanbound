"""
Unit tests for CLI commands with a mocked HumanboundClient.

No live API or credentials required. Each test patches HumanboundClient()
so the command runs against fake data and we verify output/exit codes.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from humanbound_cli.exceptions import NotAuthenticatedError
from humanbound_cli.main import cli

runner = CliRunner()


def _make_mock_client(**overrides):
    """Build a pre-configured mock HumanboundClient."""
    mock = MagicMock()
    mock.is_authenticated.return_value = True
    mock.organisation_id = "org-123"
    mock.project_id = "proj-456"
    mock._organisation_id = "org-123"
    mock._project_id = "proj-456"
    mock._username = "tester"
    mock._email = "test@example.com"
    mock.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


# ---------------------------------------------------------------------------
# Auth commands
# ---------------------------------------------------------------------------


class TestAuthCommands:
    @patch("humanbound_cli.commands.auth.HumanboundClient")
    def test_whoami_authenticated(self, MockClient):
        mock = _make_mock_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.auth.HumanboundClient")
    def test_whoami_not_authenticated(self, MockClient):
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        mock._api_token = None
        MockClient.return_value = mock
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# Organisation commands
# ---------------------------------------------------------------------------


class TestOrgCommands:
    @patch("humanbound_cli.commands.orgs.HumanboundClient")
    def test_orgs_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_organisations.return_value = [
            {"id": "org-1", "name": "Test Org", "role": "admin"}
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code == 0
        assert "Test Org" in result.output or "org-1" in result.output

    @patch("humanbound_cli.commands.orgs.HumanboundClient")
    def test_orgs_use(self, MockClient):
        mock = _make_mock_client()
        mock.list_organisations.return_value = [
            {"id": "org-new", "name": "New Org", "role": "admin"}
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "use", "org-new"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Project commands
# ---------------------------------------------------------------------------


class TestProjectCommands:
    @patch("humanbound_cli.commands.projects.HumanboundClient")
    def test_projects_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_projects.return_value = {
            "data": [{"id": "p1", "name": "My Project", "status": "active"}],
            "total": 1,
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "list"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.projects.HumanboundClient")
    def test_projects_use(self, MockClient):
        mock = _make_mock_client()
        mock.list_projects.return_value = {
            "data": [{"id": "proj-new", "name": "New Project"}],
            "total": 1,
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "use", "proj-new"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.projects.HumanboundClient")
    def test_projects_show(self, MockClient):
        mock = _make_mock_client()
        mock.get.return_value = {
            "id": "proj-456",
            "name": "My Project",
            "status": "active",
            "scope": {"overall_business_scope": "Testing"},
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["projects", "show", "proj-456"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Findings commands
# ---------------------------------------------------------------------------


class TestFindingsCommands:
    @patch("humanbound_cli.commands.findings.HumanboundClient")
    def test_findings_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_findings.return_value = {
            "data": [
                {
                    "id": "f1",
                    "title": "Prompt injection",
                    "severity": "high",
                    "status": "open",
                    "test_category": "prompt_injection",
                    "created_at": "2025-01-01T00:00:00Z",
                }
            ],
            "total": 1,
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.findings.HumanboundClient")
    def test_findings_json(self, MockClient):
        mock = _make_mock_client()
        mock.list_findings.return_value = {"data": [], "total": 0}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["findings", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    @patch("humanbound_cli.commands.findings.HumanboundClient")
    def test_findings_not_authenticated(self, MockClient):
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["findings"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Members commands
# ---------------------------------------------------------------------------


class TestMembersCommands:
    @patch("humanbound_cli.commands.members.HumanboundClient")
    def test_members_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_members.return_value = {
            "data": [
                {"id": "m1", "email": "alice@test.com", "access_level": "admin", "status": "active"}
            ]
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.members.HumanboundClient")
    def test_members_json(self, MockClient):
        mock = _make_mock_client()
        mock.list_members.return_value = {"data": []}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["members", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# API Keys commands
# ---------------------------------------------------------------------------


class TestAPIKeysCommands:
    @patch("humanbound_cli.commands.api_keys.HumanboundClient")
    def test_api_keys_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_api_keys.return_value = {
            "data": [
                {
                    "id": "k1",
                    "name": "test-key",
                    "prefix": "hb_abc",
                    "scopes": "admin",
                    "last_used_at": None,
                    "created_at": "2025-01-01T00:00:00Z",
                }
            ]
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.api_keys.HumanboundClient")
    def test_api_keys_json(self, MockClient):
        mock = _make_mock_client()
        mock.list_api_keys.return_value = {"data": []}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["api-keys", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Assessments commands
# ---------------------------------------------------------------------------


class TestAssessmentsCommands:
    @patch("humanbound_cli.commands.assessments.HumanboundClient")
    def test_assessments_list(self, MockClient):
        mock = _make_mock_client()
        mock.get.return_value = {
            "data": [
                {
                    "id": "a1",
                    "type": "assess",
                    "status": "completed",
                    "grade": "B",
                    "score": 72.5,
                    "tests_run": 50,
                    "tests_passed": 36,
                    "created_at": "2025-01-01T00:00:00Z",
                }
            ]
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.assessments.HumanboundClient")
    def test_assessments_json(self, MockClient):
        mock = _make_mock_client()
        mock.get.return_value = {"data": []}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["assessments", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Campaigns commands
# ---------------------------------------------------------------------------


class TestCampaignsCommands:
    @patch("humanbound_cli.commands.campaigns.HumanboundClient")
    def test_campaigns_status(self, MockClient):
        mock = _make_mock_client()
        mock.get_campaign.return_value = {
            "id": "camp-1",
            "status": "running",
            "progress": {"completed": 5, "total": 10},
            "created_at": "2025-01-01T00:00:00Z",
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.campaigns.HumanboundClient")
    def test_campaigns_not_authenticated(self, MockClient):
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["campaigns"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Webhooks commands
# ---------------------------------------------------------------------------


class TestWebhooksCommands:
    @patch("humanbound_cli.commands.webhooks.HumanboundClient")
    def test_webhooks_list(self, MockClient):
        mock = _make_mock_client()
        mock.get.return_value = {
            "data": [
                {
                    "id": "wh1",
                    "name": "My Hook",
                    "url": "https://example.com/hook",
                    "is_active": True,
                    "event_types": ["experiment.completed"],
                }
            ]
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.webhooks.HumanboundClient")
    def test_webhooks_json(self, MockClient):
        mock = _make_mock_client()
        mock.get.return_value = {"data": []}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Posture commands
# ---------------------------------------------------------------------------


class TestPostureCommands:
    @patch("humanbound_cli.commands.posture.get_runner")
    def test_posture(self, mock_get_runner):
        from conftest import platform_runner

        mock = _make_mock_client()
        mock.get.return_value = {
            "score": 75.0,
            "grade": "C",
            "dimensions": {},
            "experiments_count": 3,
        }
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.posture.get_runner")
    def test_posture_json(self, mock_get_runner):
        from conftest import platform_runner

        mock = _make_mock_client()
        mock.get.return_value = {"score": 75.0, "grade": "C"}
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "score" in data or "grade" in data

    @patch("humanbound_cli.commands.posture.get_runner")
    def test_posture_not_authenticated(self, mock_get_runner):
        from conftest import platform_runner

        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        mock.get.side_effect = NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["posture"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Monitor commands
# ---------------------------------------------------------------------------


class TestMonitorCommands:
    @patch("humanbound_cli.commands.monitor.HumanboundClient")
    def test_monitor_not_authenticated(self, MockClient):
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["monitor"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Experiments commands
# ---------------------------------------------------------------------------


class TestExperimentCommands:
    @patch("humanbound_cli.commands.experiments.HumanboundClient")
    def test_experiments_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_experiments.return_value = {
            "data": [
                {
                    "id": "exp-1",
                    "status": "completed",
                    "testing_level": "unit",
                    "created_at": "2025-01-01T00:00:00Z",
                }
            ],
            "total": 1,
        }
        MockClient.return_value = mock
        result = runner.invoke(cli, ["experiments", "list"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.experiments.HumanboundClient")
    def test_experiments_list_no_project(self, MockClient):
        mock = _make_mock_client()
        mock.project_id = None
        mock._project_id = None
        MockClient.return_value = mock
        result = runner.invoke(cli, ["experiments", "list"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Providers commands
# ---------------------------------------------------------------------------


class TestProvidersCommands:
    @patch("humanbound_cli.commands.providers.HumanboundClient")
    def test_providers_list(self, MockClient):
        mock = _make_mock_client()
        mock.list_providers.return_value = [
            {
                "id": "prov-1",
                "name": "openai",
                "is_default": True,
                "integration": {"model": "gpt-4"},
            }
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 0

    @patch("humanbound_cli.commands.providers.HumanboundClient")
    def test_providers_not_authenticated(self, MockClient):
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["providers", "list"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Firewall commands
# ---------------------------------------------------------------------------


class TestFirewallCommands:
    def test_firewall_help(self):
        """Firewall --help should work without auth."""
        result = runner.invoke(cli, ["firewall", "--help"])
        assert result.exit_code == 0
        assert "firewall" in result.output.lower()


# ---------------------------------------------------------------------------
# Redteam commands
# ---------------------------------------------------------------------------


class TestRedteamCommands:
    @patch("humanbound_cli.commands.redteam.HumanboundClient")
    def test_redteam_help(self, MockClient):
        result = runner.invoke(cli, ["redteam", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Logs commands
# ---------------------------------------------------------------------------


class TestLogsCommands:
    @patch("humanbound_cli.commands.logs.get_runner")
    def test_logs_not_authenticated(self, mock_get_runner):
        from conftest import platform_runner

        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        mock.get.side_effect = NotAuthenticatedError()
        mock.list_experiments.side_effect = NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Edge cases: unauthenticated access across commands
# ---------------------------------------------------------------------------

# Commands that construct HumanboundClient directly.
COMMANDS_WITH_DIRECT_CLIENT = [
    ["findings"],
    ["members"],
    ["api-keys"],
    ["assessments"],
    ["campaigns"],
    ["webhooks"],
    ["providers", "list"],
]

# Commands that access the API via get_runner().client.
COMMANDS_WITH_RUNNER = [
    ["posture"],
    ["logs"],
]

COMMANDS_REQUIRING_AUTH = COMMANDS_WITH_DIRECT_CLIENT + COMMANDS_WITH_RUNNER


@pytest.mark.parametrize("cmd", COMMANDS_REQUIRING_AUTH)
def test_unauthenticated_exits_nonzero(cmd):
    """Commands requiring auth must fail gracefully when not authenticated."""
    from conftest import platform_runner

    module_name = cmd[0].replace("-", "_")
    mock = _make_mock_client()
    mock.is_authenticated.return_value = False
    # Make every client call raise the auth error — covers whichever method
    # a given command reaches first.
    for method in (
        "get",
        "post",
        "put",
        "delete",
        "list_experiments",
        "list_providers",
        "list_findings",
        "list_projects",
        "list_members",
        "list_api_keys",
        "list_campaigns",
        "list_assessments",
        "list_webhooks",
        "get_project_logs",
        "get_experiment_logs",
    ):
        getattr(mock, method).side_effect = NotAuthenticatedError()

    if cmd in COMMANDS_WITH_RUNNER:
        patch_path = f"humanbound_cli.commands.{module_name}.get_runner"
        with patch(patch_path) as mock_get_runner:
            mock_get_runner.return_value = platform_runner(mock)
            result = runner.invoke(cli, cmd)
    else:
        patch_path = f"humanbound_cli.commands.{module_name}.HumanboundClient"
        with patch(patch_path) as MockClient:
            MockClient.return_value = mock
            result = runner.invoke(cli, cmd)

    assert result.exit_code != 0, f"`hb {' '.join(cmd)}` should fail when unauthenticated"
