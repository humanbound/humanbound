"""
Smoke tests: every registered CLI command responds to --help without errors.

These tests require NO credentials and NO running API server.
They catch import errors, missing modules, and broken command registration.
"""

import pytest
from click.testing import CliRunner

from humanbound_cli.main import cli

runner = CliRunner()


def _collect_commands(group, prefix=""):
    """Recursively collect all command paths from a Click group."""
    items = []
    for name, cmd in sorted(group.commands.items()):
        full = f"{prefix} {name}".strip()
        items.append(full)
        if hasattr(cmd, "commands"):
            items.extend(_collect_commands(cmd, full))
    return items


ALL_COMMANDS = _collect_commands(cli)


@pytest.mark.parametrize("cmd_path", ALL_COMMANDS)
def test_help_exits_zero(cmd_path):
    """Every command must respond to --help with exit code 0."""
    args = cmd_path.split() + ["--help"]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, (
        f"`hb {cmd_path} --help` failed (exit {result.exit_code}):\n{result.output}"
    )


@pytest.mark.parametrize("cmd_path", ALL_COMMANDS)
def test_help_has_output(cmd_path):
    """Every --help must produce non-empty output."""
    args = cmd_path.split() + ["--help"]
    result = runner.invoke(cli, args)
    assert len(result.output.strip()) > 0, f"`hb {cmd_path} --help` produced no output"


def test_all_commands_registered():
    """Ensure a minimum number of commands are registered (catches silent import failures)."""
    assert len(ALL_COMMANDS) >= 15, (
        f"Only {len(ALL_COMMANDS)} commands found — expected at least 15. Got: {ALL_COMMANDS}"
    )


def test_top_level_help():
    """Top-level hb --help must work."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "humanbound" in result.output.lower() or "hb" in result.output.lower()


def test_version_flag():
    """hb --version must work."""
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "hb" in result.output.lower()
