# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A local run reports its final status only after its results are on disk, and `hb test`
waits for the worker thread before it renders them, so a finished run's results are always
there to read."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.commands import test as test_cmd
from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig
from humanbound_cli.engine.schemas import Status

from .test_local_runner_partial_results import _log


def _execute(orchestrator_run_side_effect):
    orchestrator = MagicMock()
    orchestrator.orchestrator_generate.return_value = {}
    orchestrator.orchestrator_run.side_effect = orchestrator_run_side_effect
    run = _LocalRun("exp-race", _TestConfig(test_category="owasp_agentic", endpoint={}))
    saves = []

    def save(status=None):
        # what a poller would see while the files are being written
        saves.append({"visible": run.status, "saved": status})

    with (
        patch("humanbound_cli.engine.local_runner._resolve_provider", return_value={}),
        patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=None),
        patch("humanbound_cli.engine.scope.resolve", return_value={}),
        patch("humanbound_cli.engine.local_runner._load_orchestrator", return_value=orchestrator),
        patch("humanbound_cli.engine.local_runner.presenter_run", return_value={}),
        patch.object(run, "_save_results", side_effect=save),
    ):
        run.execute()
    return run, saves


def test_finished_only_after_results_are_saved():
    seen = []

    def side_effect(**kwargs):
        kwargs["callbacks"].on_logs([_log(1)])
        kwargs["callbacks"].on_complete(Status.Finished.value)
        seen.append(run_ref[0].status)

    run_ref = []
    orig_init = _LocalRun.__init__

    def init(self, *a, **kw):
        orig_init(self, *a, **kw)
        run_ref.append(self)

    with patch.object(_LocalRun, "__init__", init):
        run, saves = _execute(side_effect)

    # the orchestrator's on_complete("Finished") doesn't end the run: analysis follows
    assert seen == ["Running"]
    assert saves == [{"visible": "Analysing", "saved": "Finished"}]
    assert run.status == "Finished"


@pytest.mark.parametrize("status", [Status.Failed.value, "Terminated"])
def test_reported_end_status_is_visible_only_after_saving(status):
    def side_effect(**kwargs):
        kwargs["callbacks"].on_logs([_log(1)])
        kwargs["callbacks"].on_complete(status)

    run, saves = _execute(side_effect)
    assert saves == [{"visible": "Running", "saved": status}]
    assert run.status == status


def test_crash_is_visible_only_after_saving():
    def side_effect(**kwargs):
        kwargs["callbacks"].on_logs([_log(1)])
        raise ValueError("boom")

    run, saves = _execute(side_effect)
    assert saves == [{"visible": "Running", "saved": "Failed"}]
    assert run.status == "Failed" and run.error == "boom"


def test_save_results_defaults_to_the_current_status(tmp_path, monkeypatch):
    import json

    monkeypatch.chdir(tmp_path)
    run = _LocalRun("exp-default", _TestConfig(test_category="owasp_agentic", endpoint={}))
    run.status = "Failed"
    run._save_results()
    meta = json.loads((tmp_path / ".humanbound/results/exp-default/meta.json").read_text())
    assert meta["status"] == "Failed"
    run._save_results(status="Finished")
    meta = json.loads((tmp_path / ".humanbound/results/exp-default/meta.json").read_text())
    assert meta["status"] == "Finished"
    assert run.status == "Failed"  # saving never changes what pollers see


# ── hb test waits for the worker ──


def test_join_local_run_waits_for_the_worker():
    done = threading.Event()
    worker = threading.Thread(target=lambda: done.wait(0.2))
    worker.start()
    runner = MagicMock()
    runner._runs = {"exp-1": MagicMock(thread=worker)}
    test_cmd._join_local_run(runner, "exp-1")
    assert not worker.is_alive()


def test_join_local_run_uses_a_timeout():
    thread = MagicMock()
    runner = MagicMock()
    runner._runs = {"exp-1": MagicMock(thread=thread)}
    test_cmd._join_local_run(runner, "exp-1")
    thread.join.assert_called_once_with(timeout=test_cmd.LOCAL_JOIN_TIMEOUT_S)


def test_join_local_run_tolerates_other_runners():
    test_cmd._join_local_run(object(), "exp-1")  # no _runs (platform runner, mocks)
    runner = MagicMock()
    runner._runs = {}
    test_cmd._join_local_run(runner, "exp-1")
    runner._runs = {"exp-1": MagicMock(thread=None)}
    test_cmd._join_local_run(runner, "exp-1")
