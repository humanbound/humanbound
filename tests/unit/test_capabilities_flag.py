# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""--capabilities flag parser."""

import pytest

from humanbound_cli.commands._capabilities_flag import parse_capabilities_spec

# ---- value forms ----


@pytest.mark.parametrize(
    "value,expected",
    [
        ("on", True),
        ("ON", True),
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("off", False),
        ("OFF", False),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("NO", False),
    ],
)
def test_value_forms(value, expected):
    assert parse_capabilities_spec(f"tools={value}") == {"tools": expected}


def test_bare_key_implies_on():
    assert parse_capabilities_spec("tools") == {"tools": True}


# ---- multi-key, last-wins ----


def test_multiple_keys():
    assert parse_capabilities_spec("tools=on,memory=off") == {"tools": True, "memory": False}


def test_duplicate_key_last_wins():
    assert parse_capabilities_spec("tools=on,tools=off") == {"tools": False}


# ---- all=on/off shorthand + left-to-right ----


def test_all_on_sets_all_four():
    assert parse_capabilities_spec("all=on") == {
        "tools": True,
        "memory": True,
        "inter_agent": True,
        "reasoning_model": True,
    }


def test_all_off_sets_all_four_false():
    assert parse_capabilities_spec("all=off") == {
        "tools": False,
        "memory": False,
        "inter_agent": False,
        "reasoning_model": False,
    }


def test_all_off_then_specific_on_left_to_right():
    assert parse_capabilities_spec("all=off,tools=on") == {
        "tools": True,
        "memory": False,
        "inter_agent": False,
        "reasoning_model": False,
    }


def test_specific_on_then_all_off_left_to_right():
    assert parse_capabilities_spec("tools=on,all=off") == {
        "tools": False,
        "memory": False,
        "inter_agent": False,
        "reasoning_model": False,
    }


# ---- error cases ----


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="Unknown capability"):
        parse_capabilities_spec("tols=on")


def test_unparseable_value_raises():
    with pytest.raises(ValueError, match="accepted forms"):
        parse_capabilities_spec("tools=maybe")


def test_empty_spec_raises():
    with pytest.raises(ValueError, match="at least one"):
        parse_capabilities_spec("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError, match="at least one"):
        parse_capabilities_spec("   ")
