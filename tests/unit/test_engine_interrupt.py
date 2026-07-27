# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Interrupting a local run must keep completed conversations.

Unit layer: the ``EngineCallbacks`` delivery contract and its wiring — every
orchestrator routes logs through ``deliver_logs``, and the local runner opts
into flush-every-log.

Integration layer, sharing one deterministic harness (a worker genuinely stuck
mid-conversation when the interrupt lands): a regression guard proving the old
batched drop-on-cancel behaviour loses finished work, and the real ``hb test``
command with the real ``LocalTestRunner`` thread and a genuine
``KeyboardInterrupt`` in the wait loop, saving partial results to disk. Only
the LLM/network leaves and the telemetry transport are mocked.
"""

from __future__ import annotations

import importlib
import json
import threading
import time as _time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from humanbound_cli.engine.callbacks import EngineCallbacks
from humanbound_cli.engine.local_runner import _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig
from humanbound_cli.main import cli

ORCH = importlib.import_module("humanbound_cli.engine.orchestrators.owasp_agentic.orchestrator")

ORCHESTRATOR_MODULES = [
    "humanbound_cli.engine.orchestrators.owasp_agentic.orchestrator",
    "humanbound_cli.engine.orchestrators.owasp_single_turn.orchestrator",
    "humanbound_cli.engine.orchestrators.behavioral_qa.orchestrator",
]

TOTAL = 5  # conversations the run would produce
STICK_AT = 3  # the Nth conversation blocks mid-flight when the interrupt lands


# ── unit: delivery contract ───────────────────────────────────────────────


def test_deliver_logs_drops_after_cancel_for_batched_sinks():
    received: list = []
    cb = EngineCallbacks(on_logs=received.extend, is_terminated=lambda: True, flush_every_log=False)
    cb.deliver_logs([1, 2])
    assert received == []


def test_deliver_logs_delivers_after_cancel_for_local_sinks():
    received: list = []
    cb = EngineCallbacks(on_logs=received.append, is_terminated=lambda: True, flush_every_log=True)
    buffer = [1, 2]
    cb.deliver_logs(buffer)
    buffer.append(3)
    assert received == [[1, 2]]  # delivered, and as a copy
    cb.deliver_logs([])
    assert received == [[1, 2]]  # empty batch is a no-op


def test_should_flush_every():
    assert EngineCallbacks().should_flush_every() is False
    assert EngineCallbacks(flush_every_log=True).should_flush_every() is True
    assert EngineCallbacks(max_workers=1).should_flush_every() is True  # debug mode


@pytest.mark.parametrize("module", ORCHESTRATOR_MODULES)
def test_orchestrators_route_logs_through_deliver_logs(module):
    register = getattr(importlib.import_module(module), "__do_register_logs")
    received: list = []
    cb = EngineCallbacks(on_logs=received.extend, is_terminated=lambda: True, flush_every_log=True)
    register("org", {"id": "exp-1"}, [{"thread_id": "t0"}], callbacks=cb)
    assert received == [{"thread_id": "t0"}]
    register("org", {"id": "exp-1"}, [{"thread_id": "t1"}], callbacks=None)  # must not raise


def test_local_runner_opts_into_flush_every():
    cb = _LocalRun("exp-1", _TestConfig()).make_callbacks()
    assert cb.flush_every_log is True
    debug_cb = _LocalRun("exp-1", _TestConfig(debug=True)).make_callbacks()
    assert debug_cb.max_workers == 1
    assert debug_cb.should_flush_every() is True


# ── integration harness ───────────────────────────────────────────────────


class _Harness:
    """Deterministic fakes: N-1 conversations complete, the Nth blocks until
    released so the interrupt lands while a worker is genuinely mid-conversation.
    """

    def __init__(self):
        self.completed = 0
        self.lock = threading.Lock()
        self.stuck = threading.Event()
        self.release = threading.Event()

    def conversationer_cls(harness):
        class FakeConversationer:
            number_of_iterations = 1

            def __init__(self, *a, **k):
                pass

            async def chat(self, *a, **k):
                with harness.lock:
                    n = harness.completed + 1
                if n == STICK_AT:
                    harness.stuck.set()
                    harness.release.wait(timeout=10)
                    raise RuntimeError("interrupted mid-conversation")
                with harness.lock:
                    harness.completed += 1
                return [{"u": f"attack-{n}", "a": f"response-{n}"}], f"tid-{n}", 0.01, None

        return FakeConversationer


class _FakeJudge:
    def __init__(self, *a, **k):
        pass

    def evaluate(self, conversation, telemetry_data=None):
        return {
            "result": "pass",
            "category": "",
            "explanation": "ok",
            "severity": 0,
            "confidence": 90,
        }


_FAKE_CONFIG = {"data": {"cat1": {"attack_gen_template": [f"t{i}" for i in range(TOTAL)]}}}


def test_old_batched_behavior_loses_completed_conversations():
    """Regression guard: without flush_every_log, cancelling drops the buffered
    conversations before they ever reach the sink."""
    harness = _Harness()
    sink: list = []
    terminated = threading.Event()
    cb = EngineCallbacks(
        on_logs=sink.extend, is_terminated=terminated.is_set, flush_every_log=False
    )
    experiment = {
        "id": "exp-e2e",
        "project_id": "",
        "configuration": {"scope": {}, "integration": {}, "context": ""},
        "lang": "english",
        "testing_level": "unit",
    }

    with (
        patch.object(ORCH, "Conversationer", harness.conversationer_cls()),
        patch.object(ORCH, "Judge", _FakeJudge),
        patch.object(ORCH, "Bot", lambda *a, **k: object()),
        patch.object(ORCH.TestingConfiguration, "config", _FAKE_CONFIG),
        patch.object(ORCH.time, "sleep", lambda *a, **k: None),
    ):
        thread = threading.Thread(
            target=ORCH.orchestrator_run,
            args=("org", {"name": "fake"}, experiment, {"cat1": []}, None, cb),
            daemon=True,
        )
        thread.start()
        try:
            assert harness.stuck.wait(timeout=5), "worker never reached the stuck conversation"
            terminated.set()  # the interrupt
        finally:
            harness.release.set()
            thread.join(timeout=5)

    assert harness.completed == STICK_AT - 1
    assert sink == []  # completed conversations were dropped — the original bug


def test_cli_ctrl_c_saves_partial_results(tmp_path, monkeypatch):
    """Real `hb test --local --wait` + real KeyboardInterrupt in the wait loop:
    the handler in commands/test.py must save completed conversations to disk."""
    from humanbound_cli.engine.local_runner import LocalTestRunner

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HUMANBOUND_DEV", "1")  # telemetry: dev installs never send
    monkeypatch.setenv("HOME", str(tmp_path))  # isolate ~/.humanbound

    (tmp_path / "bot-config.json").write_text(
        json.dumps(
            {
                "streaming": None,
                "chat_completion": {
                    "endpoint": "http://127.0.0.1:9/chat",
                    "headers": {},
                    "payload": {"content": "$PROMPT"},
                },
            }
        )
    )

    harness = _Harness()
    real_sleep = _time.sleep
    main_thread = threading.main_thread()

    def fake_sleep(seconds=0):
        # Main thread = the wait loop in test.py. Once a worker is stuck
        # mid-conversation, the next poll-sleep becomes the user's Ctrl+C.
        if threading.current_thread() is main_thread and harness.stuck.is_set():
            threading.Timer(0.2, harness.release.set).start()
            raise KeyboardInterrupt
        real_sleep(0)

    with (
        patch("humanbound_cli.commands.test.get_runner", return_value=LocalTestRunner()),
        patch(
            "humanbound_cli.engine.local_runner._resolve_provider",
            return_value={"name": "fake", "integration": {}},
        ),
        patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=None),
        patch("humanbound_cli.engine.scope.resolve", return_value={}),
        patch.object(ORCH, "orchestrator_generate", return_value={"cat1": []}),
        patch.object(ORCH, "Conversationer", harness.conversationer_cls()),
        patch.object(ORCH, "Judge", _FakeJudge),
        patch.object(ORCH, "Bot", lambda *a, **k: object()),
        patch.object(ORCH.TestingConfiguration, "config", _FAKE_CONFIG),
        patch("time.sleep", side_effect=fake_sleep),
        patch("os._exit", side_effect=SystemExit(0)),  # handler ends in os._exit(0)
        patch("humanbound_cli.telemetry.client._posthog", MagicMock()),
    ):
        result = CliRunner().invoke(
            cli, ["test", "--endpoint", "bot-config.json", "--local", "--wait"]
        )

    assert "Interrupted. Stopping test" in result.output
    assert "Partial results" in result.output

    exp_dirs = list((tmp_path / ".humanbound" / "results").iterdir())
    assert len(exp_dirs) == 1
    entries = [
        json.loads(line) for line in (exp_dirs[0] / "logs.jsonl").read_text().strip().splitlines()
    ]
    passed = [e for e in entries if e.get("result") == "pass"]
    assert harness.completed == STICK_AT - 1
    assert len(passed) == harness.completed, (
        f"completed {harness.completed} conversations but only {len(passed)} on disk"
    )
    assert (exp_dirs[0] / "meta.json").exists()
