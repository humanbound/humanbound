# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
#
# OWASP Single-Turn orchestrator — forked for local engine.
# Coupling points replaced with EngineCallbacks.
#

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from ...bot import Bot, Telemetry
from ...callbacks import EngineCallbacks
from ...schemas import LogsAnonymous, Status, Turn
from .config import TestingConfiguration
from .generator import Conversationer, Synthesizer
from .judge import Judge

logger = logging.getLogger("humanbound.engine.orchestrator.single_turn")

EXPERIMENT_THREAD_TIMEOUT = 10800
INIT_LOGS_BUFFER_LENGTH = 5
LOGS_BUFFER_LENGTH = 70
SINGLE_TURN_WORKER_COUNT = 5


def __do_register_logs(organisation_id, experiment, logs, callbacks=None):
    if not len(logs):
        return
    if callbacks and callbacks.is_terminated():
        return
    if callbacks:
        callbacks.on_logs(list(logs))


def __do_partial_generate(
    model_provider, agent, test_sub_category, lang, testing_level, prompts, lock
):
    synthesizer = Synthesizer(model_provider, agent, lang, test_sub_category, testing_level)
    result = synthesizer.run()
    with lock:
        prompts[test_sub_category] = result


def __do_thread_run(
    organisation_id,
    experiment,
    model_provider,
    test_sub_category,
    clientbot,
    prompts,
    few_shots_model,
    telemetry_config=None,
    callbacks=None,
):
    e_id = experiment["id"]
    total = len(prompts)

    conversationer = Conversationer(
        model_provider,
        experiment["configuration"]["scope"],
        experiment["lang"],
        experiment["testing_level"],
        test_sub_category,
        experiment["configuration"].get("context", ""),
        clientbot,
    )
    judge = Judge(model_provider, experiment["configuration"]["scope"], few_shots_model)

    telemetry_client = None
    if telemetry_config:
        telemetry_client = Telemetry(telemetry_config, experiment["id"])

    logs = []
    logs_lock = threading.Lock()
    logs_buffer_len = min(INIT_LOGS_BUFFER_LENGTH, LOGS_BUFFER_LENGTH)

    def _process_prompt(idx, prompt):
        nonlocal logs, logs_buffer_len
        thread_id = str(uuid.uuid4())

        if callbacks and callbacks.is_terminated():
            return

        async def _ping():
            return await conversationer.prompt(
                prompt, telemetry_client=telemetry_client, telemetry_config=telemetry_config
            )

        try:
            response, thread_id, exec_t, telemetry_data = asyncio.run(_ping())
            analysis = judge.evaluate([{"u": prompt, "a": response}], telemetry_data=telemetry_data)

            meta = {}
            if telemetry_data:
                tool_names = [
                    t.get("tool_name", "") for t in telemetry_data.get("tool_executions", [])
                ]
                usage = telemetry_data.get("resource_usage", {})
                meta["telemetry"] = {
                    "trace_id": thread_id,
                    "tools": tool_names,
                    "tokens": usage.get("tokens_used", 0),
                    "api_calls": usage.get("api_calls_count", 0),
                }

            log_entry = LogsAnonymous(
                thread_id=thread_id,
                conversation=[Turn(u=prompt, a=response).model_dump()],
                prompt=prompt,
                response=response,
                result=analysis["result"],
                gen_category=test_sub_category,
                fail_category=analysis["category"],
                explanation=analysis["explanation"],
                severity=analysis["severity"],
                confidence=analysis["confidence"],
                exec_t=exec_t,
                meta=[meta] if meta else [],
            ).model_dump()

            with logs_lock:
                logs.append(log_entry)
                if len(logs) > logs_buffer_len:
                    _to_flush = logs[:]
                    logs = []
                    logs_buffer_len = LOGS_BUFFER_LENGTH
                else:
                    _to_flush = None

            if _to_flush:
                __do_register_logs(organisation_id, experiment, _to_flush, callbacks=callbacks)

            time.sleep(1)

        except Exception as e:
            error_entry = LogsAnonymous(
                thread_id=thread_id,
                conversation=[dict(u="", a="<ERROR>")],
                prompt="",
                response="",
                result="error",
                gen_category=test_sub_category,
                fail_category="exception",
                explanation=str(e),
                severity=100,
                confidence=100,
                exec_t=0,
            ).model_dump()

            with logs_lock:
                logs.append(error_entry)

            if callbacks:
                callbacks.on_error(e.__class__.__name__, {"where": "Single Turn", "e": str(e)})

    max_workers = min(SINGLE_TURN_WORKER_COUNT, max(1, total))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_process_prompt, idx, prompt) for idx, prompt in enumerate(prompts)]
        for future in futures:
            future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)

    if logs:
        __do_register_logs(organisation_id, experiment, logs, callbacks=callbacks)


def orchestrator_generate(model_provider, experiment):
    categories = list(TestingConfiguration.config["data"].keys())
    prompts = {}
    lock = threading.Lock()
    max_workers = max(1, min(len(categories), 10))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for test_sub_category in categories:
            future = executor.submit(
                __do_partial_generate,
                model_provider,
                experiment["configuration"]["scope"],
                test_sub_category,
                experiment["lang"],
                experiment["testing_level"],
                prompts,
                lock,
            )
            futures[future] = test_sub_category
        for future in futures:
            future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)

    return prompts


def compute_quota(testing_level, dataset_len):
    return dataset_len


def orchestrator_run(
    organisation_id,
    model_provider,
    experiment,
    prompts,
    few_shots_model,
    callbacks=None,
):
    if callbacks is None:
        callbacks = EngineCallbacks()

    categories = list(TestingConfiguration.config["data"].keys())
    max_workers = max(1, min(len(categories), 10))

    clientbot = Bot(experiment["configuration"]["integration"], experiment["id"])
    telemetry_config = (
        experiment.get("configuration", {}).get("integration", {}).get("telemetry") or None
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for test_sub_category in categories:
            future = executor.submit(
                __do_thread_run,
                organisation_id,
                experiment,
                model_provider,
                test_sub_category,
                clientbot,
                prompts[test_sub_category],
                few_shots_model,
                telemetry_config=telemetry_config,
                callbacks=callbacks,
            )
            futures[future] = test_sub_category
        for future in futures:
            future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)

    if not callbacks.is_terminated():
        callbacks.on_complete(Status.Finished.value)
