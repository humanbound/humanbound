"""
Unit tests for `hb orgs` commands.

Mocked HumanboundClient — no live API needed.
"""

import os
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    MOCK_ORG,
    MOCK_ORG_2,
    MOCK_SUBSCRIPTION,
)

from humanbound_cli.exceptions import NotAuthenticatedError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.orgs.HumanboundClient"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m._username = "testuser"
    m._email = "test@example.com"
    m.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(PATCH_TARGET)
    def test_list_orgs(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code == 0
        assert "Test Org" in result.output
        assert "Other Org" in result.output

    @patch(PATCH_TARGET)
    def test_list_orgs_via_group_default(self, MockClient):
        """Invoking `orgs` with no subcommand should list."""
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs"])
        assert result.exit_code == 0
        assert "Test Org" in result.output

    @patch(PATCH_TARGET)
    def test_use_org(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "use", "org-123"])
        assert result.exit_code == 0
        assert "Switched to organisation" in result.output
        mock.set_organisation.assert_called_once_with("org-123")

    @patch(PATCH_TARGET)
    def test_current_org(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "current"])
        assert result.exit_code == 0
        assert "Test Org" in result.output
        assert "org-123" in result.output

    @patch(PATCH_TARGET)
    def test_subscription(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get_subscription.return_value = [MOCK_SUBSCRIPTION]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code == 0
        assert "Community" in result.output
        assert "active" in result.output

    @patch(PATCH_TARGET)
    def test_subscription_unpaid_shows_read_only(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get_subscription.return_value = [
            {**MOCK_SUBSCRIPTION, "plan_level": "team", "status": "unpaid"}
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code == 0
        assert "unpaid" in result.output
        assert "Read-only" in result.output

    @patch(PATCH_TARGET)
    def test_subscription_scheduled_switch(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get_subscription.return_value = [
            {
                **MOCK_SUBSCRIPTION,
                "plan_level": "team",
                "scheduled_plan_level": "community",
                "current_period_end": 1796947200,  # 11 Dec 2026 UTC
            }
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code == 0
        assert "Switches to Community on 2026-12-11" in result.output

    @patch(PATCH_TARGET)
    def test_subscription_features_and_quota_readable(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        mock.get_subscription.return_value = [
            {
                **MOCK_SUBSCRIPTION,
                "plan_level": "enterprise",
                "quota": {"credits": 198163544, "members": None},
                "features": {
                    "webhooks": True,
                    "siem_integration": False,
                    "sso": "oauth",
                    "forensic_window_days": 90,
                    "monitoring_cadence": None,
                },
            }
        ]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code == 0
        out = result.output
        assert "credits: 198,163,544" in out
        assert "members: unlimited" in out
        assert "webhooks: enabled" in out
        assert "siem_integration: disabled" in out
        assert "sso: oauth" in out
        assert "forensic_window_days: 90" in out
        assert "monitoring_cadence: custom" in out
        assert "None" not in out


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_list_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.list_organisations.side_effect = NotAuthenticatedError("Not authenticated")
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_use_org_not_found(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "use", "nonexistent-id"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_current_no_org_selected(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "current"])
        assert result.exit_code == 0  # prints warning but does not error
        assert "No organisation selected" in result.output

    @patch(PATCH_TARGET)
    def test_subscription_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_subscription_no_org(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "subscription"])
        assert result.exit_code != 0
        assert "No organisation selected" in result.output


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH_TARGET)
    def test_list_table_shows_org_names(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code == 0
        assert "Test Org" in result.output
        assert "Other Org" in result.output
        assert "org-123" in result.output
        assert "org-456" in result.output

    @patch(PATCH_TARGET)
    def test_list_marks_active_org(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = [MOCK_ORG, MOCK_ORG_2]
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code == 0
        assert "active" in result.output

    @patch(PATCH_TARGET)
    def test_empty_org_list(self, MockClient):
        mock = _make_client()
        mock.list_organisations.return_value = []
        MockClient.return_value = mock
        result = runner.invoke(cli, ["orgs", "list"])
        assert result.exit_code == 0
        assert "No organisations found" in result.output
