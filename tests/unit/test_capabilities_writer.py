# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Merge and diff helpers for scope.capabilities."""

from humanbound_cli.engine.capabilities_writer import (
    diff_capabilities,
    merge_capabilities,
)


def test_merge_set_only_with_existing_values():
    current = {"tools": False, "memory": True, "inter_agent": False, "reasoning_model": False}
    override = {"tools": True}
    assert merge_capabilities(current, override) == {
        "tools": True,
        "memory": True,
        "inter_agent": False,
        "reasoning_model": False,
    }


def test_merge_starts_from_all_false_when_current_is_none():
    assert merge_capabilities(None, {"tools": True}) == {
        "tools": True,
        "memory": False,
        "inter_agent": False,
        "reasoning_model": False,
    }


def test_merge_preserves_unknown_current_keys():
    """If BE someday adds a key the CLI doesn't know about, leave it alone."""
    current = {
        "tools": False,
        "memory": True,
        "inter_agent": False,
        "reasoning_model": False,
        "future_key": True,
    }
    override = {"tools": True}
    result = merge_capabilities(current, override)
    assert result["future_key"] is True


def test_diff_returns_sorted_tuples_for_each_key():
    old = {"tools": False, "memory": True, "inter_agent": False, "reasoning_model": False}
    new = {"tools": True, "memory": True, "inter_agent": False, "reasoning_model": False}
    diff = diff_capabilities(old, new)
    assert diff == [
        ("inter_agent", False, False),
        ("memory", True, True),
        ("reasoning_model", False, False),
        ("tools", False, True),
    ]


from unittest.mock import MagicMock

import pytest
from rich.console import Console

from humanbound_cli.engine.capabilities_writer import write_capabilities


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.get_project.return_value = {
        "id": "p1",
        "name": "Test",
        "scope": {
            "overall_business_scope": "Customer support agent for flight bookings",
            "intents": {"permitted": ["search"], "restricted": []},
            "capabilities": {
                "tools": False,
                "memory": False,
                "inter_agent": False,
                "reasoning_model": False,
            },
        },
    }
    client.update_project.return_value = {"ok": True}
    return client


def test_write_capabilities_happy_path(fake_client):
    console = Console(record=True)
    result = write_capabilities(
        fake_client, "p1", override={"tools": True}, yes=True, console=console
    )

    assert result.no_op is False
    assert result.cancelled is False
    assert result.final_capabilities["tools"] is True
    fake_client.update_project.assert_called_once()
    payload = fake_client.update_project.call_args.args[1]
    # Full scope sent back, with tools flipped.
    assert payload["scope"]["capabilities"]["tools"] is True
    assert (
        payload["scope"]["overall_business_scope"] == "Customer support agent for flight bookings"
    )


def test_write_capabilities_no_op_skips_put(fake_client):
    # Override matches existing → no-op detection.
    console = Console(record=True)
    result = write_capabilities(
        fake_client, "p1", override={"tools": False}, yes=True, console=console
    )
    assert result.no_op is True
    fake_client.update_project.assert_not_called()


def test_write_capabilities_rejects_missing_overall_business_scope(fake_client):
    fake_client.get_project.return_value = {
        "id": "p1",
        "scope": {"overall_business_scope": "", "intents": {"permitted": [], "restricted": []}},
    }
    console = Console(record=True)
    with pytest.raises(SystemExit):
        write_capabilities(fake_client, "p1", override={"tools": True}, yes=True, console=console)


def test_write_capabilities_user_cancels(fake_client):
    # yes=False and the (mock) confirm returns False → no PUT.
    console = Console(record=True)
    result = write_capabilities(
        fake_client,
        "p1",
        override={"tools": True},
        yes=False,
        console=console,
        confirm_callback=lambda _msg: False,
    )
    assert result.cancelled is True
    fake_client.update_project.assert_not_called()
