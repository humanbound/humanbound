"""
Unit tests for the `hb connect` command.

Mocked HumanboundClient — no live API needed.
Kept minimal since connect is complex and calls into init helpers.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import (
    MOCK_PROVIDER,
    assert_exit_ok,
)

from humanbound_cli.main import cli

PATCH = "humanbound_cli.commands.connect.HumanboundClient"
runner = CliRunner()


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    m.list_providers.return_value = [MOCK_PROVIDER]
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @patch(PATCH)
    def test_help_text(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert_exit_ok(result)
        assert "connect" in result.output.lower()
        assert "--endpoint" in result.output

    @patch(PATCH)
    def test_no_flags_shows_usage(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["connect"])
        # Should exit with error and show usage guidance
        assert result.exit_code != 0
        assert "endpoint" in result.output.lower() or "vendor" in result.output.lower()

    @patch(PATCH)
    @patch("humanbound_cli.commands.connect._connect_agent")
    def test_endpoint_routes_to_agent_path(self, mock_connect_agent, MockCls):
        """Verify --endpoint triggers the agent path."""
        mock = _make_client()
        MockCls.return_value = mock
        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        result = runner.invoke(cli, ["connect", "--endpoint", endpoint_json, "--yes"])
        # _connect_agent should have been called (we patched it to avoid side effects)
        mock_connect_agent.assert_called_once()

    @patch(PATCH)
    @patch("humanbound_cli.commands.connect._connect_platform")
    def test_vendor_routes_to_platform_path(self, mock_connect_platform, MockCls):
        """Verify --vendor triggers the platform path."""
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(cli, ["connect", "--vendor", "microsoft", "--yes"])
        mock_connect_platform.assert_called_once()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @patch(PATCH)
    def test_not_authenticated(self, MockCls):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockCls.return_value = mock
        # Pass an endpoint so we enter _connect_agent which checks auth
        result = runner.invoke(cli, ["connect", "--endpoint", '{"chat_completion":{}}'])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    @patch(PATCH)
    def test_no_org(self, MockCls):
        mock = _make_client()
        mock.organisation_id = None
        mock._organisation_id = None
        MockCls.return_value = mock
        result = runner.invoke(cli, ["connect", "--endpoint", '{"chat_completion":{}}'])
        assert result.exit_code != 0
        assert "organisation" in result.output.lower() or "org" in result.output.lower()

    @patch(PATCH)
    def test_mixed_agent_and_platform_flags(self, MockCls):
        mock = _make_client()
        MockCls.return_value = mock
        result = runner.invoke(
            cli,
            [
                "connect",
                "--endpoint",
                '{"chat_completion":{}}',
                "--vendor",
                "microsoft",
            ],
        )
        assert result.exit_code != 0
        assert "Cannot combine" in result.output


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    @patch(PATCH)
    def test_name_flag_in_help(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert "--name" in result.output

    @patch(PATCH)
    def test_level_flag_in_help(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert "--level" in result.output

    @patch(PATCH)
    def test_yes_flag_in_help(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert "--yes" in result.output

    @patch(PATCH)
    def test_context_flag_in_help(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert "--context" in result.output


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TestOutputFormat:
    @patch(PATCH)
    def test_help_mentions_agent_path(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert_exit_ok(result)
        assert "agent" in result.output.lower()

    @patch(PATCH)
    def test_help_mentions_platform_path(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert_exit_ok(result)
        assert "platform" in result.output.lower() or "vendor" in result.output.lower()
