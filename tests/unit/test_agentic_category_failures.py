# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Regression tests for terminal status after agentic category failures."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from humanbound_cli.engine.callbacks import EngineCallbacks
from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig
from humanbound_cli.engine.schemas import Status

ORCH = importlib.import_module("humanbound_cli.engine.orchestrators.owasp_agentic.orchestrator")

EXPERIMENT = {
    "id": "exp-category-failure",
    "configuration": {"integration": {}},
}


class _Future:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.cancelled = False

    def result(self, timeout=None):
        if self.error:
            raise self.error

    def cancel(self):
        self.cancelled = True


class _Executor:
    def __init__(self, futures):
        self.futures = iter(futures)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, *args, **kwargs):
        return next(self.futures)


def _run_with_futures(futures, callbacks):
    executor = _Executor(futures)
    with (
        patch.object(ORCH, "Bot", return_value=object()),
        patch.object(ORCH, "ThreadPoolExecutor", return_value=executor),
    ):
        ORCH.orchestrator_run(
            organisation_id="org",
            model_provider={},
            experiment=EXPERIMENT,
            prompts={"first": [], "second": []},
            few_shots_model=None,
            callbacks=callbacks,
        )


def test_category_worker_failure_marks_agentic_run_failed_and_reports_error():
    completed = []
    errors = []
    callbacks = EngineCallbacks(
        on_complete=completed.append,
        on_error=lambda title, details: errors.append((title, details)),
    )

    _run_with_futures([_Future(), _Future(RuntimeError("second category failed"))], callbacks)

    assert completed == [Status.Failed.value]
    assert len(errors) == 1
    title, details = errors[0]
    assert title == "RuntimeError"
    assert details["where"] == "OWASP Agentic :: Category worker"
    assert details["category"] == "second"
    assert details["e"] == "second category failed"
    assert "RuntimeError: second category failed" in details["trace"]


def test_all_category_workers_complete_marks_agentic_run_finished():
    completed = []
    errors = []
    callbacks = EngineCallbacks(
        on_complete=completed.append,
        on_error=lambda title, details: errors.append((title, details)),
    )

    _run_with_futures([_Future(), _Future()], callbacks)

    assert completed == [Status.Finished.value]
    assert errors == []


def test_local_run_preserves_failed_status_reported_by_orchestrator():
    orchestrator = MagicMock()
    orchestrator.orchestrator_generate.return_value = {}
    orchestrator.orchestrator_run.side_effect = lambda **kwargs: kwargs["callbacks"].on_complete(
        Status.Failed.value
    )
    run = _LocalRun(
        "exp-category-failure",
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

    assert run.status == Status.Failed.value
    presenter.assert_not_called()
    save_results.assert_not_called()
