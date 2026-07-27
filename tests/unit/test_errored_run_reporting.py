# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A run where every conversation errored carries no security signal and must
not be reported as a pass. Covers `_all_errored`, `_resolve_exit` (the single
source of truth for hb test's exit code), and the results-panel rendering."""

import io

import pytest
from rich.console import Console

import humanbound_cli.commands.test as test_cmd
from humanbound_cli.commands.test import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_RUN_FAILED,
    _all_errored,
    _build_results_panel,
    _display_results,
    _resolve_exit,
)
from humanbound_cli.engine.runner import Posture
from humanbound_cli.engine.runner import TestResult as _TestResult


def _result(stats, insights=None, status="Finished"):
    return _TestResult(
        experiment_id="exp-1",
        name="t",
        status=status,
        stats=stats,
        insights=insights or [],
    )


# ────────────────────────────────────────────────────────────────
# _all_errored — verdict predicate
# ────────────────────────────────────────────────────────────────


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


# ────────────────────────────────────────────────────────────────
# _resolve_exit — exit-code policy
# ────────────────────────────────────────────────────────────────

_CLEAN = {"total": 3, "pass": 3, "fail": 0, "error": 0}
_ALL_ERRORED = {"total": 3, "pass": 0, "fail": 0, "error": 3}
_HIGH_INSIGHT = [{"result": "fail", "severity": "high", "explanation": "x"}]


@pytest.mark.parametrize(
    "stats,insights,final_status,fail_on,expected",
    [
        (_CLEAN, None, "Finished", "", EXIT_OK),
        (_CLEAN, _HIGH_INSIGHT, "Finished", "", EXIT_OK),  # findings but no --fail-on
        (_CLEAN, _HIGH_INSIGHT, "Finished", "high", EXIT_FINDINGS),
        (_CLEAN, _HIGH_INSIGHT, "Finished", "any", EXIT_FINDINGS),
        (_CLEAN, _HIGH_INSIGHT, "Finished", "critical", EXIT_OK),  # below threshold
        (_ALL_ERRORED, None, "Finished", "", EXIT_RUN_FAILED),
        (_ALL_ERRORED, None, "Finished", "any", EXIT_RUN_FAILED),  # run failure wins
        (_CLEAN, _HIGH_INSIGHT, "Failed", "high", EXIT_RUN_FAILED),  # Failed wins over fail-on
        ({"total": 5, "pass": 2, "fail": 0, "error": 3}, None, "Finished", "", EXIT_OK),  # partial
    ],
)
def test_resolve_exit_policy(stats, insights, final_status, fail_on, expected):
    code, reason = _resolve_exit(_result(stats, insights), final_status, fail_on)
    assert code == expected
    assert (reason is None) is (code == EXIT_OK)


# ────────────────────────────────────────────────────────────────
# _build_results_panel — structure, no console needed
# ────────────────────────────────────────────────────────────────


def test_panel_warns_and_goes_red_when_all_errored():
    title, lines, border = _build_results_panel(_result(_ALL_ERRORED), Posture(), all_errored=True)
    body = "\n".join(lines)
    assert title == "Experiment Complete — no results"
    assert border == "red"
    assert "Errored:[/yellow] 3" in body
    assert "No conversations completed" in body
    assert "NOT a passing result" in body


def test_panel_shows_errored_line_without_warning_on_partial_errors():
    stats = {"total": 5, "pass": 2, "fail": 0, "error": 3}
    title, lines, border = _build_results_panel(_result(stats), Posture(), all_errored=False)
    body = "\n".join(lines)
    assert title == "Experiment Complete"
    assert border == "green"
    assert "Errored:[/yellow] 3" in body
    assert "No conversations completed" not in body


def test_panel_is_clean_on_a_normal_pass():
    title, lines, border = _build_results_panel(
        _result(_CLEAN), Posture(overall_score=100.0, grade="A"), all_errored=False
    )
    body = "\n".join(lines)
    assert title == "Experiment Complete"
    assert border == "green"
    assert "Errored" not in body
    assert "Posture Grade" in body


# ────────────────────────────────────────────────────────────────
# _display_results — rendering smoke test
# ────────────────────────────────────────────────────────────────


def test_display_renders_the_all_errored_panel(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(test_cmd, "console", Console(file=buf, force_terminal=False, width=100))
    _display_results(_result(_ALL_ERRORED), Posture(), all_errored=True)
    out = buf.getvalue()
    assert "No conversations completed" in out
    assert "NOT a passing result" in out
