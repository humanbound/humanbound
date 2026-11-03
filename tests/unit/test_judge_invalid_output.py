# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""A judge model that returns unusable output gives an actionable error, and the
traceback stays out of normal CLI output (it is kept for --debug)."""

import logging

import pytest

from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.orchestrators.behavioral_qa.judge import Judge as BehavioralJudge
from humanbound_cli.engine.orchestrators.owasp_agentic.judge import Judge as AgenticJudge
from humanbound_cli.engine.orchestrators.owasp_single_turn.judge import Judge as SingleTurnJudge
from humanbound_cli.engine.runner import TestConfig as _TestConfig

BAD_VERDICT = '```json\n{\n  "explanation": "The agent revealed the key.\n  "result": fail,\n'


class _FakeLLM:
    def ping(self, *args, **kwargs):
        return BAD_VERDICT


def _judge(cls):
    judge = object.__new__(cls)
    judge.llmp = _FakeLLM()
    judge.BASIC_JUDGE_TMPL = "<CONVERSATION_CONTEXT><WHITEBOX_ADDENDUM>"
    return judge


@pytest.mark.parametrize("cls", [AgenticJudge, SingleTurnJudge])
def test_invalid_verdict_error_points_at_the_judge_model(cls, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(Exception) as exc:
        _judge(cls).evaluate([{"u": "hi", "a": "the key is 42"}])
    message = str(exc.value)
    assert message.startswith("502/Unexpected judge LLM response. Not in a valid format.")
    assert "judge model may be too weak" in message
    assert "stronger judge model" in message
    assert "Preview:" in message


@pytest.mark.parametrize("cls", [AgenticJudge, SingleTurnJudge])
def test_invalid_verdict_warning_has_no_traceback(cls, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(Exception, match="Not in a valid format"):
        _judge(cls).evaluate([{"u": "hi", "a": "the key is 42"}])
    assert "LLM verict bad format" in caplog.text
    assert "Traceback" not in caplog.text


def _run(debug):
    return _LocalRun("exp-judge-output", _TestConfig(debug=debug))


def test_engine_errors_hide_the_traceback_by_default(caplog):
    cb = _run(debug=False).make_callbacks()
    with caplog.at_level(logging.WARNING):
        cb.on_error("JudgeError", {"where": "w", "e": "boom", "trace": "Traceback (most recent)"})
    assert "boom" in caplog.text
    assert "Traceback" not in caplog.text


def test_engine_errors_keep_the_traceback_with_debug(caplog):
    cb = _run(debug=True).make_callbacks()
    with caplog.at_level(logging.WARNING):
        cb.on_error("JudgeError", {"where": "w", "e": "boom", "trace": "Traceback (most recent)"})
    assert "Traceback (most recent)" in caplog.text


class _RaisingLLM:
    def ping(self, *args, **kwargs):
        raise ConnectionError("judge endpoint down")


def _behavioral_judge(llm):
    judge = object.__new__(BehavioralJudge)
    judge.llmp = llm
    judge.BASIC_JUDGE_TMPL = ""
    return judge


def test_behavioral_judge_invalid_json_points_at_the_judge_model():
    with pytest.raises(Exception) as exc:
        _behavioral_judge(_FakeLLM()).evaluate([{"u": "hi", "a": "hello"}])
    message = str(exc.value)
    assert message.startswith("500/Error, could not extract a verdict.")
    assert "stronger judge model" in message


def test_behavioral_judge_connection_error_is_not_blamed_on_the_model():
    with pytest.raises(Exception) as exc:
        _behavioral_judge(_RaisingLLM()).evaluate([{"u": "hi", "a": "hello"}])
    message = str(exc.value)
    assert "judge endpoint down" in message
    assert "too weak" not in message
