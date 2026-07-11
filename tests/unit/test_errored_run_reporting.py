# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A run where every conversation errored carries no security signal and must
not be reported as a pass. Covers `_all_errored` and `_display_results`."""

import io

import pytest
from rich.console import Console

import humanbound_cli.commands.test as test_cmd
from humanbound_cli.commands.test import _all_errored, _display_results
from humanbound_cli.engine.runner import Posture
from humanbound_cli.engine.runner import TestResult as _TestResult


@pytest.mark.parametrize(
    "stats,expected",
    [
        ({"total": 3, "pass": 0, "fail": 0, "error": 3}, True),  # everything errored
        ({"total": 5, "pass": 2, "fail": 0, "error": 3}, False),  # some completed
        ({"total": 5, "pass": 0, "fail": 1, "error": 4}, False),  # a fail counts as signal
        ({"total": 0, "pass": 0, "fail": 0, "error": 0}, False),  # empty run, different case
        ({"total": 3, "pass": 3, "fail": 0, "error": 0}, False),  # clean pass
        ({"total": 3, "pass": 0, "fail": 0}, False),  # no error key at all
    ],
)
def test_all_errored_truth_table(stats, expected):
    assert _all_errored(stats) is expected


def _capture(result, posture):
    """Render _display_results into a string, returning (all_errored, output)."""
    buf = io.StringIO()
    original = test_cmd.console
    test_cmd.console = Console(file=buf, force_terminal=False, width=100)
    try:
        flag = _display_results(result, posture)
    finally:
        test_cmd.console = original
    return flag, buf.getvalue()


def test_display_flags_and_warns_when_all_errored():
    result = _TestResult(
        experiment_id="exp-1",
        name="t",
        status="Finished",
        stats={"total": 3, "pass": 0, "fail": 0, "error": 3},
    )
    flag, out = _capture(result, Posture())
    assert flag is True
    assert "Errored" in out
    assert "No conversations completed" in out
    assert "NOT a passing result" in out


def test_display_does_not_warn_on_a_normal_pass():
    result = _TestResult(
        experiment_id="exp-2",
        name="t",
        status="Finished",
        stats={"total": 3, "pass": 3, "fail": 0, "error": 0},
    )
    flag, out = _capture(result, Posture(overall_score=100.0, grade="A"))
    assert flag is False
    assert "No conversations completed" not in out
