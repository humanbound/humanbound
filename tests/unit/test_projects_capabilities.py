# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb projects update --capabilities integration tests."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.commands.projects import projects_group


def _make_client_mock(scope_capabilities):
    client = MagicMock()
    client.project_id = "p1"
    client.get_project.return_value = {
        "id": "p1",
        "name": "T",
        "scope": {
            "overall_business_scope": "Customer support agent for flight bookings",
            "intents": {"permitted": ["search"], "restricted": []},
            "capabilities": scope_capabilities,
        },
    }
    client.update_project.return_value = {"ok": True}
    return client


def test_update_capabilities_happy_path():
    client = _make_client_mock(
        {"tools": False, "memory": False, "inter_agent": False, "reasoning_model": False}
    )
    runner = CliRunner()
    with patch("humanbound_cli.commands.projects.HumanboundClient", return_value=client):
        result = runner.invoke(
            projects_group, ["update", "p1", "--capabilities", "tools=on", "--yes"]
        )
    assert result.exit_code == 0, result.output
    client.update_project.assert_called_once()
    payload = client.update_project.call_args.args[1]
    assert payload["scope"]["capabilities"]["tools"] is True


def test_update_capabilities_no_op_does_not_call_put():
    client = _make_client_mock(
        {"tools": True, "memory": False, "inter_agent": False, "reasoning_model": False}
    )
    runner = CliRunner()
    with patch("humanbound_cli.commands.projects.HumanboundClient", return_value=client):
        result = runner.invoke(
            projects_group, ["update", "p1", "--capabilities", "tools=on", "--yes"]
        )
    assert result.exit_code == 0
    client.update_project.assert_not_called()
    assert "No changes" in result.output


def test_update_capabilities_unknown_key_errors():
    client = _make_client_mock(
        {"tools": False, "memory": False, "inter_agent": False, "reasoning_model": False}
    )
    runner = CliRunner()
    with patch("humanbound_cli.commands.projects.HumanboundClient", return_value=client):
        result = runner.invoke(
            projects_group, ["update", "p1", "--capabilities", "tols=on", "--yes"]
        )
    assert result.exit_code != 0
    assert "Unknown capability" in result.output


def test_update_capabilities_pre_flight_rejects_short_business_scope():
    client = _make_client_mock(
        {"tools": False, "memory": False, "inter_agent": False, "reasoning_model": False}
    )
    client.get_project.return_value["scope"]["overall_business_scope"] = "short"  # <20 chars
    runner = CliRunner()
    with patch("humanbound_cli.commands.projects.HumanboundClient", return_value=client):
        result = runner.invoke(
            projects_group, ["update", "p1", "--capabilities", "tools=on", "--yes"]
        )
    assert result.exit_code != 0
    assert "scope is incomplete" in result.output


def test_existing_name_description_path_still_works():
    """Regression: the original --name/--description flow must keep working."""
    client = _make_client_mock(
        {"tools": False, "memory": False, "inter_agent": False, "reasoning_model": False}
    )
    runner = CliRunner()
    with patch("humanbound_cli.commands.projects.HumanboundClient", return_value=client):
        result = runner.invoke(projects_group, ["update", "p1", "--name", "NewName"])
    assert result.exit_code == 0
    client.update_project.assert_called_once_with("p1", {"name": "NewName"})
