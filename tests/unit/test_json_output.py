"""
Validate that every command supporting --json produces valid JSON output.

No live API or credentials required — all client calls are mocked.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from humanbound_cli.main import cli

runner = CliRunner()


def _make_mock_client():
    mock = MagicMock()
    mock.is_authenticated.return_value = True
    mock.organisation_id = "org-123"
    mock.project_id = "proj-456"
    mock._organisation_id = "org-123"
    mock._project_id = "proj-456"
    mock._username = "tester"
    mock._email = "test@example.com"
    mock.base_url = "http://test.local/api"
    return mock


# (command_args, patch_target, mock_setup)
# mock_setup is a callable that receives the mock and configures return values.


def _setup_findings(mock):
    mock.list_findings.return_value = {"data": [{"id": "f1", "title": "Test"}], "total": 1}


def _setup_members(mock):
    mock.list_members.return_value = {"data": [{"id": "m1", "email": "a@b.c"}]}


def _setup_api_keys(mock):
    mock.list_api_keys.return_value = {"data": [{"id": "k1", "name": "key"}]}


def _setup_assessments(mock):
    mock.get.return_value = {"data": [{"id": "a1", "status": "completed"}]}


def _setup_posture(mock):
    mock.get.return_value = {"score": 80.0, "grade": "B"}


def _setup_webhooks(mock):
    mock.get.return_value = {"data": [{"id": "w1", "name": "hook"}]}


def _setup_campaigns(mock):
    mock.get_campaign.return_value = {"id": "c1", "status": "idle"}


def _setup_monitor(mock):
    mock.get.return_value = {"score": 80, "grade": "B", "dimensions": {}}


JSON_COMMANDS = [
    (["findings", "--json"], "humanbound_cli.commands.findings.HumanboundClient", _setup_findings),
    (["members", "--json"], "humanbound_cli.commands.members.HumanboundClient", _setup_members),
    (["api-keys", "--json"], "humanbound_cli.commands.api_keys.HumanboundClient", _setup_api_keys),
    (
        ["assessments", "--json"],
        "humanbound_cli.commands.assessments.HumanboundClient",
        _setup_assessments,
    ),
    (["posture", "--json"], "humanbound_cli.commands.posture.get_runner", _setup_posture),
    (["webhooks", "--json"], "humanbound_cli.commands.webhooks.HumanboundClient", _setup_webhooks),
    (
        ["campaigns", "--json"],
        "humanbound_cli.commands.campaigns.HumanboundClient",
        _setup_campaigns,
    ),
]


@pytest.mark.parametrize(
    "cmd_args,patch_target,setup_fn",
    JSON_COMMANDS,
    ids=[" ".join(c[0]) for c in JSON_COMMANDS],
)
def test_json_output_is_valid(cmd_args, patch_target, setup_fn):
    """--json flag must produce parseable JSON on stdout."""
    from conftest import platform_runner

    with patch(patch_target) as Mocked:
        mock = _make_mock_client()
        setup_fn(mock)
        if patch_target.endswith(".get_runner"):
            Mocked.return_value = platform_runner(mock)
        else:
            Mocked.return_value = mock
        result = runner.invoke(cli, cmd_args)

        assert result.exit_code == 0, (
            f"`hb {' '.join(cmd_args)}` failed (exit {result.exit_code}):\n{result.output}"
        )

        # Strip any Rich markup or status spinner lines that might leak to stdout
        output = result.output.strip()
        assert len(output) > 0, f"`hb {' '.join(cmd_args)}` produced no output"

        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"`hb {' '.join(cmd_args)}` produced invalid JSON:\n"
                f"Error: {e}\n"
                f"Output:\n{output[:500]}"
            )

        assert isinstance(data, (dict, list)), f"Expected dict or list, got {type(data)}"


@pytest.mark.parametrize(
    "cmd_args,patch_target,setup_fn",
    JSON_COMMANDS,
    ids=[" ".join(c[0]) for c in JSON_COMMANDS],
)
def test_json_output_differs_from_default(cmd_args, patch_target, setup_fn):
    """--json output should differ from default Rich table output (no ANSI codes)."""
    from conftest import platform_runner

    with patch(patch_target) as Mocked:
        mock = _make_mock_client()
        setup_fn(mock)
        if patch_target.endswith(".get_runner"):
            Mocked.return_value = platform_runner(mock)
        else:
            Mocked.return_value = mock
        result = runner.invoke(cli, cmd_args)

        if result.exit_code != 0:
            pytest.skip("Command failed, skipping format check")

        output = result.output.strip()
        # JSON output should not contain Rich/ANSI escape sequences
        assert "\x1b[" not in output, (
            f"`hb {' '.join(cmd_args)}` --json output contains ANSI escape codes"
        )
