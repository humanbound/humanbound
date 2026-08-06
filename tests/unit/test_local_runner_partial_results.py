# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Failed local runs keep completed conversations as saved partial results,
whether the orchestrator reported the failure via on_complete("Failed") or
raised out of orchestrator_run entirely."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig
from humanbound_cli.engine.schemas import LogsAnonymous, Status


def _log(i: int, result: str = "pass") -> dict:
    return LogsAnonymous(
        thread_id=f"t{i}",
        conversation=[{"u": "hi", "a": "there"}],
        prompt="hi",
        response="there",
        result=result,
        gen_category="prompt_injection",
        fail_category="",
        explanation="",
        severity=0,
        confidence=90,
        exec_t=1,
    ).model_dump()


def _execute(orchestrator_run_side_effect):
    orchestrator = MagicMock()
    orchestrator.orchestrator_generate.return_value = {}
    orchestrator.orchestrator_run.side_effect = orchestrator_run_side_effect
    run = _LocalRun(
        "exp-partial",
        _TestConfig(test_category="owasp_agentic", endpoint={}),
    )

    with (
        patch("humanbound_cli.engine.local_runner._resolve_provider", return_value={}),
        patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=None),
        patch("humanbound_cli.engine.scope.resolve", return_value={}),
        patch("humanbound_cli.engine.local_runner._load_orchestrator", return_value=orchestrator),
        patch("humanbound_cli.engine.local_runner.presenter_run") as presenter,
        patch.object(run, "_save_results") as save_results,
    ):
        run.execute()

    return run, presenter, save_results


def test_orchestrator_reported_failure_saves_partial_results():
    def side_effect(**kwargs):
        kwargs["callbacks"].on_logs([_log(1), _log(2, "fail")])
        kwargs["callbacks"].on_complete(Status.Failed.value)

    run, presenter, save_results = _execute(side_effect)

    assert run.status == Status.Failed.value
    presenter.assert_called_once()
    save_results.assert_called_once()


def test_orchestrator_crash_saves_partial_results():
    def side_effect(**kwargs):
        kwargs["callbacks"].on_logs([_log(1), _log(2, "fail")])
        raise ValueError("model provider missing api key")

    run, presenter, save_results = _execute(side_effect)

    assert run.status == Status.Failed.value
    assert run.error == "model provider missing api key"
    presenter.assert_called_once()
    save_results.assert_called_once()


def test_orchestrator_crash_without_logs_saves_nothing():
    run, presenter, save_results = _execute(ValueError("boom before any conversation"))

    assert run.status == Status.Failed.value
    presenter.assert_not_called()
    save_results.assert_not_called()
