# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A conversation the judge cannot assess is logged as a judge error and counts
against the posture grade, instead of silently dropping out of the result."""

import asyncio
import importlib
from unittest.mock import patch

from humanbound_cli.engine.callbacks import EngineCallbacks
from humanbound_cli.engine.presenter import run as presenter_run
from humanbound_cli.engine.schemas import JUDGE_ERROR_CATEGORY, ExperimentResults, Stats

AGENTIC = importlib.import_module("humanbound_cli.engine.orchestrators.owasp_agentic.orchestrator")
SINGLE_TURN = importlib.import_module(
    "humanbound_cli.engine.orchestrators.owasp_single_turn.orchestrator"
)


class _Judge:
    def evaluate(self, conversation, telemetry_data=None):
        raise Exception("502/Unexpected judge LLM response. Not in a valid format.")


class _Conversationer:
    def __init__(self, *args, error=None, **kwargs):
        self.error = error

    async def chat(self, *args, **kwargs):
        if self.error:
            raise self.error
        return [{"u": "hi", "a": "leaked"}], "thread-1", 1.0, None

    async def prompt(self, *args, **kwargs):
        return "leaked", "thread-1", 1.0, None


def _agentic_log(conversationer):
    run = getattr(AGENTIC, "__do_single_pipeline_run")
    logs, _ = asyncio.run(
        run(conversationer, _Judge(), "tmpl", "llm001", None, {"id": "e"}, [], 10_000)
    )
    return logs[0]


def test_agentic_judge_failure_is_a_judge_error():
    assert _agentic_log(_Conversationer())["fail_category"] == JUDGE_ERROR_CATEGORY


def test_agentic_bot_failure_is_still_an_exception():
    log = _agentic_log(_Conversationer(error=ConnectionError("bot down")))
    assert log["fail_category"] == "exception"


def test_single_turn_judge_failure_is_a_judge_error():
    logs = []
    experiment = {
        "id": "e",
        "lang": "english",
        "testing_level": "unit",
        "configuration": {"scope": {}},
    }
    with (
        patch.object(SINGLE_TURN, "Conversationer", _Conversationer),
        patch.object(SINGLE_TURN, "Judge", return_value=_Judge()),
    ):
        getattr(SINGLE_TURN, "__do_thread_run")(
            None,
            experiment,
            {},
            "llm001",
            None,
            ["hi"],
            "",
            callbacks=EngineCallbacks(on_logs=logs.extend, flush_every_log=True),
        )
    assert logs[0]["fail_category"] == JUDGE_ERROR_CATEGORY


def _log(result, fail_category=""):
    return {"result": result, "fail_category": fail_category, "severity": 0, "confidence": 90}


def test_unjudged_conversations_count_against_the_grade():
    results = presenter_run(None, [_log("pass")] * 3 + [_log("error", JUDGE_ERROR_CATEGORY)])
    assert results["stats"]["unjudged"] == 1
    assert results["posture"]["posture"] == 75.0


def test_other_errors_leave_the_grade_unchanged():
    results = presenter_run(None, [_log("pass")] * 3 + [_log("error", "exception")])
    assert results["stats"]["unjudged"] == 0
    assert results["posture"]["posture"] == 100.0


def test_unjudged_count_survives_saving_the_results():
    stats = presenter_run(None, [_log("pass"), _log("error", JUDGE_ERROR_CATEGORY)])["stats"]
    saved = ExperimentResults(stats=Stats(**stats)).model_dump()
    assert saved["stats"]["unjudged"] == 1
