#
# Behavioral QA orchestrator — forked for local engine.
# Coupling points replaced with EngineCallbacks.
#

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from ...bot import Bot, Telemetry
from ...schemas import Status, LogsAnonymous, Turn
from ...callbacks import EngineCallbacks
from .config import TestingConfiguration
from .judge import Judge
from .generator import Conversationer, Synthesizer

logger = logging.getLogger("humanbound.engine.orchestrator.behavioral_qa")

EXPERIMENT_THREAD_TIMEOUT = 10800
INIT_LOGS_BUFFER_LENGTH = 5
LOGS_BUFFER_LENGTH = 20


def __do_register_logs(organisation_id, experiment, logs, callbacks=None):
    if not len(logs):
        return
    if callbacks and callbacks.is_terminated():
        return
    if callbacks:
        callbacks.on_logs(list(logs))


def __do_partial_generate(model_provider, agent, test_sub_category, lang, testing_level, prompts, lock):
    synthesizer = Synthesizer(model_provider, agent, lang, test_sub_category, testing_level)
    result = synthesizer.run()
    with lock:
        prompts[test_sub_category] = result


def __do_thread_run(
    organisation_id, experiment, model_provider, test_sub_category,
    clientbot, prompts, telemetry_config=None, callbacks=None,
):
    async def run_async(
        organisation_id, experiment, model_provider, test_sub_category,
        clientbot, prompts, callbacks,
    ):
        logs, conversation, thread_id = [], [], str(uuid.uuid4())
        conversationer = Conversationer(
            model_provider,
            experiment["configuration"]["scope"],
            experiment["lang"],
            experiment["testing_level"],
            test_sub_category,
            experiment["configuration"].get("context", ""),
            clientbot,
        )
        judge = Judge(
            model_provider, experiment["configuration"]["scope"], test_sub_category
        )
        logs_buffer_len = min(INIT_LOGS_BUFFER_LENGTH, LOGS_BUFFER_LENGTH)

        telemetry_client = None
        if telemetry_config:
            telemetry_client = Telemetry(telemetry_config, experiment["id"])

        for _ in range(conversationer.number_of_iterations):
            for testing_scenario in TestingConfiguration.config["data"][
                test_sub_category
            ]["epic"]["testing_scenarios"]:
                if callbacks and callbacks.is_terminated():
                    break

                conversation = None
                try:
                    conversation, thread_id, exec_t, telemetry_data = await conversationer.chat(
                        testing_scenario,
                        telemetry_client=telemetry_client,
                        telemetry_config=telemetry_config,
                    )
                    summary, metrics = judge.evaluate(conversation, telemetry_data=telemetry_data)

                    meta = {}
                    if telemetry_data:
                        tool_names = [t.get("tool_name", "") for t in telemetry_data.get("tool_executions", [])]
                        usage = telemetry_data.get("resource_usage", {})
                        meta["telemetry"] = {
                            "trace_id": thread_id,
                            "tools": tool_names,
                            "tokens": usage.get("tokens_used", 0),
                            "api_calls": usage.get("api_calls_count", 0),
                        }

                    # Merge metrics into meta
                    log_meta = metrics if isinstance(metrics, list) else []
                    if meta:
                        log_meta.append(meta)

                    logs.append(
                        LogsAnonymous(
                            thread_id=thread_id,
                            conversation=[
                                Turn(u=c["u"], a=c["a"]).model_dump()
                                for c in conversation
                            ],
                            prompt=conversation[0]["u"],
                            response=conversation[0]["a"],
                            result=summary["result"],
                            gen_category=test_sub_category,
                            fail_category=summary["fail_category"],
                            explanation=summary["explanation"],
                            severity=summary["severity"],
                            confidence=summary["confidence"],
                            meta=log_meta,
                            exec_t=exec_t,
                        ).model_dump()
                    )
                    if len(logs) > logs_buffer_len:
                        __do_register_logs(organisation_id, experiment, logs, callbacks=callbacks)
                        logs_buffer_len = LOGS_BUFFER_LENGTH
                        logs = []

                    time.sleep(2)
                except Exception as e:
                    ex = str(e)
                    logs.append(
                        LogsAnonymous(
                            thread_id=thread_id,
                            conversation=(
                                [dict(u="", a="<ERROR>")]
                                if conversation is None
                                else conversation
                            ),
                            prompt="",
                            response="",
                            result="error",
                            gen_category=test_sub_category,
                            fail_category="exception",
                            explanation=ex,
                            severity=100,
                            confidence=100,
                            exec_t=0,
                        ).model_dump()
                    )

                    if callbacks:
                        callbacks.on_error(e.__class__.__name__, {"where": "Behavioral QA", "e": str(e)})

        if len(logs) > 0:
            __do_register_logs(organisation_id, experiment, logs, callbacks=callbacks)

    return asyncio.run(
        run_async(
            organisation_id, experiment, model_provider,
            test_sub_category, clientbot, prompts, callbacks,
        )
    )


def orchestrator_generate(model_provider, experiment):
    prompts = {}
    lock = threading.Lock()
    max_workers = max(1, min(len(TestingConfiguration.config["data"].keys()), 10))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for test_sub_category in TestingConfiguration.config["data"].keys():
            future = executor.submit(
                __do_partial_generate, model_provider,
                experiment["configuration"]["scope"],
                test_sub_category, experiment["lang"],
                experiment["testing_level"], prompts, lock,
            )
            futures.append(future)
        for future in futures:
            future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)

    return prompts


def compute_quota(testing_level, dataset_len):
    all_quota = 0
    for test_sub_category in TestingConfiguration.config["data"].keys():
        all_quota += len(
            TestingConfiguration.config["data"][test_sub_category]["epic"]["testing_scenarios"]
        )
    t1, t2 = TestingConfiguration.get_testing_params(testing_level)
    return all_quota * t1 * t2


def orchestrator_run(
    organisation_id, model_provider, experiment, prompts, few_shots_model,
    callbacks=None,
):
    if callbacks is None:
        callbacks = EngineCallbacks()

    max_workers = max(1, min(len(TestingConfiguration.config["data"].keys()), 10))

    clientbot = Bot(experiment["configuration"]["integration"], experiment["id"])
    telemetry_config = experiment.get("configuration", {}).get("integration", {}).get("telemetry") or None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for test_sub_category in TestingConfiguration.config["data"].keys():
            futures.append(
                executor.submit(
                    __do_thread_run, organisation_id, experiment,
                    model_provider, test_sub_category, clientbot,
                    prompts[test_sub_category],
                    telemetry_config=telemetry_config, callbacks=callbacks,
                )
            )
        for future in futures:
            future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)

    if not callbacks.is_terminated():
        callbacks.on_complete(Status.Finished.value)
