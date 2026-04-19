#
# OWASP Agentic orchestrator — multi-turn adversarial testing.
# Uses EngineCallbacks for I/O abstraction.
#

import asyncio
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from ...bot import Bot, Telemetry
from ...schemas import Status, LogsAnonymous
from ...llm import get_llm_pinger
from ...callbacks import EngineCallbacks
from .config import TestingConfiguration
from .judge import Judge
from .generator import Conversationer, Synthesizer

logger = logging.getLogger("humanbound.engine.orchestrator")

# Constants
EXPERIMENT_THREAD_TIMEOUT = 10800  # 3 hours
INIT_LOGS_BUFFER_LENGTH = 5

LOGS_BUFFER_LENGTH = (
    20  # number of logs to buffer before sending them in a single request
)


#
# Utility functions
#


async def __do_single_pipeline_run(
    conversationer,
    judge,
    attack_gen_template,
    test_sub_category,
    organisation_id,
    experiment,
    logs,
    logs_buffer_len,
    telemetry_config=None,
    telemetry_client=None,
    opening=None,
    cross_conv_registry=None,
    canary_meta=None,
    callbacks=None,
):
    e_id = experiment["id"]
    conversation = None
    try:
        # Skip if experiment was terminated
        if callbacks and callbacks.is_terminated():
            return logs, logs_buffer_len

        # Extract [PS:{id}] marker from project strategy templates
        strategy_id = None
        clean_template = attack_gen_template
        if isinstance(attack_gen_template, str) and attack_gen_template.startswith("[PS:"):
            marker_end = attack_gen_template.index("]")
            strategy_id = attack_gen_template[4:marker_end]
            clean_template = attack_gen_template[marker_end + 1:].lstrip("\n")

        payload = None
        pre_conversation = []
        if opening:
            pre_conversation, _, _, payload = await conversationer.prompt(opening)
        conversation, thread_id, exec_t, telemetry_data = await conversationer.chat(
            clean_template, payload=payload, conversation=pre_conversation,
            cross_conv_registry=cross_conv_registry,
            telemetry_client=telemetry_client, telemetry_config=telemetry_config,
        )

        # Debug: emit per-turn info
        if callbacks and callbacks.on_turn.__code__ != (lambda x: None).__code__:
            for i, turn in enumerate(conversation):
                callbacks.on_turn({
                    "category": test_sub_category,
                    "turn": i + 1,
                    "total_turns": len(conversation),
                    "user_msg": turn.get("u", ""),
                    "bot_response": turn.get("a", ""),
                })

        analysis = judge.evaluate(conversation, telemetry_data=telemetry_data)

        # Debug: emit verdict
        if callbacks and callbacks.on_verdict.__code__ != (lambda x: None).__code__:
            callbacks.on_verdict({
                "category": test_sub_category,
                "strategy": clean_template[:80] if isinstance(clean_template, str) else "",
                "result": analysis["result"],
                "severity": analysis.get("severity", 0),
                "confidence": analysis.get("confidence", 0),
                "explanation": analysis.get("explanation", ""),
                "turns": len(conversation),
                "exec_t": exec_t if 'exec_t' in dir() else 0,
            })

        attack_trace = None
        if strategy_id:
            attack_trace = [f"[PS:{strategy_id}]"]

        # Build meta array
        meta = []
        if canary_meta:
            meta.append(canary_meta)
        if telemetry_data:
            tool_names = [t.get("tool_name", "") for t in telemetry_data.get("tool_executions", [])]
            usage = telemetry_data.get("resource_usage", {})
            meta.append({
                "telemetry": {
                    "trace_id": thread_id,
                    "tools": tool_names,
                    "tokens": usage.get("tokens_used", 0),
                    "api_calls": usage.get("api_calls_count", 0),
                }
            })

        logs.append(
            LogsAnonymous(
                thread_id=thread_id,
                conversation=conversation,
                prompt=conversation[0]["u"],
                response=conversation[0]["a"],
                result=analysis["result"],
                gen_category=test_sub_category,
                fail_category=analysis["category"],
                explanation=analysis["explanation"],
                severity=analysis["severity"],
                confidence=analysis["confidence"],
                exec_t=exec_t,
                attack_trace=attack_trace,
                meta=meta,
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
                thread_id="",
                conversation=(
                    [dict(u="", a="<ERROR>")] if conversation is None else conversation
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
            callbacks.on_error(e.__class__.__name__, {
                "where": "OWASP Agentic :: Chat",
                "e": str(e),
                "trace": str(traceback.format_exc()),
            })
    return logs, logs_buffer_len


def __do_register_logs(
    organisation_id,
    experiment,
    logs,
    callbacks=None,
):
    if not len(logs):
        return

    if callbacks and callbacks.is_terminated():
        return

    # Emit logs via callback
    if callbacks:
        callbacks.on_logs(list(logs))


def __do_thread_run(
    organisation_id,
    experiment,
    model_provider,
    test_sub_category,
    clientbot,
    prompts,
    few_shots_model,
    telemetry_config=None,
    cross_conv_registry=None,
    callbacks=None,
):

    async def run_async(
        organisation_id,
        experiment,
        model_provider,
        test_sub_category,
        clientbot,
        prompts,
        few_shots_model,
        telemetry_config,
        cross_conv_registry,
        callbacks,
    ):
        e_id = experiment["id"]
        logs = []
        # Debug mode: flush after every conversation (no buffering)
        if callbacks and callbacks.max_workers == 1:
            logs_buffer_len = 0
        else:
            logs_buffer_len = min(INIT_LOGS_BUFFER_LENGTH, LOGS_BUFFER_LENGTH)

        judge = Judge(
            model_provider,
            experiment["configuration"]["scope"],
            few_shots_model,
            context=experiment["configuration"].get("context", ""),
        )

        config_data = TestingConfiguration.config["data"]
        attack_templates = config_data[test_sub_category]["attack_gen_template"]

        # Append project-specific learned strategies (via callback — empty locally)
        project_id = experiment.get("project_id", "")
        if callbacks:
            project_strategies = callbacks.get_strategies(project_id)
            if project_strategies:
                attack_templates = list(attack_templates) + project_strategies

        conversationer = Conversationer(
            model_provider,
            experiment["configuration"]["scope"],
            experiment["lang"],
            experiment["testing_level"],
            test_sub_category,
            experiment["configuration"].get("context", ""),
            clientbot,
        )

        # Set up telemetry client if configured (presence = enabled)
        telemetry_client = None
        if telemetry_config:
            telemetry_client = Telemetry(telemetry_config, experiment["id"])

        # Canary planting for cross-session leakage detection
        canary_meta = None
        canary_config = config_data[test_sub_category].get("canary")
        if canary_config and canary_config.get("enabled"):
            from .generator import CanaryGenerator
            canary_gen = CanaryGenerator()
            canaries, marker, planting_strategy = canary_gen.generate(
                get_llm_pinger(model_provider),
                experiment["configuration"]["scope"]["overall_business_scope"],
                canary_config.get("count", 3),
            )
            canary_tokens = [c["token"] for c in canaries]

            # Plant canaries in a single natural conversation
            await conversationer.plant(planting_strategy)

            # Pass canary tokens to judge
            judge.set_canary_tokens(canary_tokens)

            canary_meta = {"canary": {"tokens": canary_tokens, "marker": marker}}

        num_iterations = conversationer.number_of_iterations
        openings = prompts

        for _1 in range(num_iterations):
            if callbacks and callbacks.is_terminated():
                break

            for _2, attack_gen_template in enumerate(attack_templates):
                if callbacks and callbacks.is_terminated():
                    break

                opening = None
                if openings:
                    opening_idx = (_1 * len(attack_templates) + _2) % len(openings)
                    opening = openings[opening_idx]

                logs, logs_buffer_len = await __do_single_pipeline_run(
                    conversationer,
                    judge,
                    attack_gen_template,
                    test_sub_category,
                    organisation_id,
                    experiment,
                    logs,
                    logs_buffer_len,
                    telemetry_config=telemetry_config,
                    telemetry_client=telemetry_client,
                    opening=opening,
                    cross_conv_registry=cross_conv_registry,
                    canary_meta=canary_meta,
                    callbacks=callbacks,
                )

        # Flush remaining logs
        if len(logs) > 0:
            __do_register_logs(organisation_id, experiment, logs, callbacks=callbacks)

    return asyncio.run(
        run_async(
            organisation_id,
            experiment,
            model_provider,
            test_sub_category,
            clientbot,
            prompts,
            few_shots_model,
            telemetry_config,
            cross_conv_registry,
            callbacks,
        )
    )


def _has_telemetry(experiment):
    """Check if telemetry is configured for this experiment (whitebox mode).
    If telemetry block exists, it's enabled — no separate flag needed."""
    telemetry = experiment.get("configuration", {}).get("integration", {}).get("telemetry")
    return bool(telemetry)


#
# EXPOSE ORCHESTRATOR
# 1) orchestrator_generate: Generate the datasets
# 2) compute_quota: Estimate the cost (in logs) for this experiment
# 3) orchestrator_run: Run the experiment
#
def orchestrator_generate(model_provider, experiment):
    agent = experiment["configuration"]["scope"]
    lang = experiment["lang"]
    testing_level = experiment["testing_level"]

    telemetry_on = _has_telemetry(experiment)
    active_categories = TestingConfiguration.get_active_categories(telemetry_enabled=telemetry_on)

    synthesizer = Synthesizer(model_provider, agent, lang, testing_level)
    opening_pool = synthesizer.run()

    return {cat: opening_pool for cat in active_categories}


def compute_quota(testing_level, dataset_len):
    total_templates = 0
    for test_sub_category in TestingConfiguration.config["data"].keys():
        total_templates += len(
            TestingConfiguration.config["data"][test_sub_category][
                "attack_gen_template"
            ]
        )

    t1, t2 = TestingConfiguration.get_testing_params(testing_level)
    total_quota = total_templates * t1 * t2
    return int(total_quota)


def orchestrator_run(
    organisation_id, model_provider, experiment, prompts, few_shots_model,
    callbacks=None,
):
    """Run the experiment. Logs emitted via callbacks.on_logs().

    Args:
        callbacks: EngineCallbacks for I/O decoupling. If None, uses defaults (no-op).
    """
    if callbacks is None:
        callbacks = EngineCallbacks()

    # Extract telemetry config from integration (presence = enabled)
    telemetry_config = experiment.get("configuration", {}).get("integration", {}).get("telemetry") or None

    clientbot = Bot(
        experiment["configuration"]["integration"],
        experiment["id"],
    )

    active_categories = list(prompts.keys())

    # Shared cross-conversation registry for technique intelligence
    cross_conv_registry = []

    max_workers = max(1, min(len(active_categories), 10))
    if callbacks.max_workers > 0:
        max_workers = callbacks.max_workers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for test_sub_category in active_categories:
            if callbacks.is_terminated():
                break

            cat_prompts = prompts.get(test_sub_category, [])
            future = executor.submit(
                __do_thread_run,
                organisation_id,
                experiment,
                model_provider,
                test_sub_category,
                clientbot,
                cat_prompts,
                few_shots_model,
                telemetry_config,
                cross_conv_registry,
                callbacks,
            )
            futures[future] = test_sub_category

        for future in futures:
            try:
                if callbacks.is_terminated():
                    future.cancel()
                    continue
                future.result(timeout=EXPERIMENT_THREAD_TIMEOUT)
            except Exception as e:
                continue

    # Signal completion via callback
    if not callbacks.is_terminated():
        callbacks.on_complete(Status.Finished.value)
