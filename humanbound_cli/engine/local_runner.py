"""LocalTestRunner — runs engine in-process, results to files.

Provider from env vars or ~/.humanbound/config.yaml.
Results written to .humanbound/results/exp-{timestamp}/
"""

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from .runner import TestRunner, TestConfig, TestStatus, TestResult, Posture, PaginatedLogs
from .callbacks import EngineCallbacks
from .presenter import run as presenter_run

logger = logging.getLogger("humanbound.engine.local")


class _LocalRun:
    """A single local test execution running in a background thread."""

    def __init__(self, experiment_id, config: TestConfig):
        self.experiment_id = experiment_id
        self.config = config
        self.status = "Created"
        self.logs = []
        self.results = None
        self.error = None
        self.thread = None
        self._terminated = threading.Event()
        self._created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def make_callbacks(self):
        cb = EngineCallbacks(
            on_logs=lambda logs: self.logs.extend(logs),
            on_complete=lambda status: setattr(self, 'status', status),
            is_terminated=self._terminated.is_set,
            on_error=lambda title, details: logger.warning(f"[{title}] {details}"),
            get_strategies=lambda pid: [],  # no cross-session FSLF locally
        )

        if self.config.debug:
            cb.max_workers = 1
            cb.on_turn = _debug_on_turn
            cb.on_verdict = _debug_on_verdict

        return cb

    def execute(self):
        """Run the full engine pipeline. Called in background thread."""
        try:
            # Resolve provider
            provider = _resolve_provider()

            # Resolve scope
            from .scope import resolve as resolve_scope
            from .llm import get_llm_pinger
            llm = get_llm_pinger(provider)

            scope = resolve_scope(
                repo_path=self.config.repo_path,
                prompt_path=self.config.prompt_path,
                scope_path=self.config.scope_path,
                integration=self.config.endpoint,
                llm_pinger=llm,
            )

            # Build experiment dict (matches engine's expected shape)
            experiment = {
                "id": self.experiment_id,
                "project_id": "",
                "configuration": {
                    "scope": scope,
                    "integration": self.config.endpoint or {},
                    "context": self.config.context,
                },
                "lang": self.config.lang,
                "testing_level": self.config.testing_level,
            }

            callbacks = self.make_callbacks()

            # Load orchestrator based on test_category
            orch_module = _load_orchestrator(self.config.test_category)

            # Phase 1: Generate prompts
            self.status = "Generating"
            if self.config.debug:
                print("  Generating attack prompts...", flush=True)
            prompts = orch_module.orchestrator_generate(provider, experiment)
            if self.config.debug:
                total_prompts = sum(len(v) for v in prompts.values())
                print(f"  Generated {total_prompts} prompts across {len(prompts)} categories\n", flush=True)

            # Phase 2: Run conversations
            self.status = "Running"
            orch_module.orchestrator_run(
                organisation_id=None,
                model_provider=provider,
                experiment=experiment,
                prompts=prompts,
                few_shots_model=None,
                callbacks=callbacks,
            )

            # Phase 3: Post-processing
            self.status = "Analysing"
            self.results = presenter_run(
                None, self.logs,
                test_category=self.config.test_category,
            )

            # Write results to files
            self._save_results()

            self.status = "Finished"

        except Exception as e:
            self.error = str(e)
            self.status = "Failed"
            logger.error(f"Local test failed: {e}\n{traceback.format_exc()}")

    def _save_results(self):
        """Write meta.json + logs.jsonl to .humanbound/results/

        Uses Pydantic models for validation — ensures output matches API schema.
        """
        from .schemas import (
            ExperimentMeta, ExperimentResults, Stats, ExecT, Insight,
            ExperimentPosture, LogsAnonymous,
        )

        results_dir = Path(".humanbound/results") / self.experiment_id
        results_dir.mkdir(parents=True, exist_ok=True)

        # Build validated ExperimentMeta
        exp_results = ExperimentResults()
        if self.results:
            stats_data = self.results.get("stats", {})
            exp_results = ExperimentResults(
                stats=Stats(**stats_data) if stats_data else Stats(),
                insights=[
                    Insight(**i) if isinstance(i, dict) else i
                    for i in self.results.get("insights", [])
                ],
                posture=(
                    ExperimentPosture(**self.results["posture"])
                    if self.results.get("posture") else None
                ),
                exec_t=ExecT(**self.results.get("exec_t", {})) if self.results.get("exec_t") else ExecT(),
            )

        meta = ExperimentMeta(
            id=self.experiment_id,
            name=self.config.name,
            status=self.status,
            test_category=self.config.test_category,
            testing_level=self.config.testing_level,
            lang=self.config.lang,
            results=exp_results,
            created_at=self._created_at,
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        (results_dir / "meta.json").write_text(
            json.dumps(meta.model_dump(), indent=2, default=str)
        )

        # logs.jsonl — validated LogEntry schema
        with open(results_dir / "logs.jsonl", "w") as f:
            for log in self.logs:
                log_obj = LogsAnonymous(**log) if isinstance(log, dict) else log
                public = log_obj.to_public()
                f.write(json.dumps(public.model_dump(), default=str) + "\n")

        logger.info(f"Results saved to {results_dir}")


class LocalTestRunner(TestRunner):
    """Runs the engine in-process. Results saved to local files."""

    def __init__(self):
        self._runs = {}

    def start(self, config: TestConfig) -> str:
        if not config.endpoint:
            raise ValueError(
                "Endpoint config is required for local testing.\n"
                "Usage: hb test --endpoint ./bot-config.json --repo . --wait"
            )

        experiment_id = f"exp-{time.strftime('%Y%m%d-%H%M%S')}"

        run = _LocalRun(experiment_id, config)
        self._runs[experiment_id] = run

        run.thread = threading.Thread(target=run.execute, daemon=True)
        run.thread.start()

        return experiment_id

    def get_status(self, experiment_id: str) -> TestStatus:
        run = self._runs.get(experiment_id)
        if not run:
            return TestStatus(experiment_id=experiment_id, status="Unknown")

        return TestStatus(
            experiment_id=experiment_id,
            status=run.status,
            log_count=len(run.logs),
        )

    def get_result(self, experiment_id: str) -> TestResult:
        run = self._runs.get(experiment_id)
        if not run:
            # Try reading from files
            return self._read_result_from_files(experiment_id)

        if not run.results:
            return TestResult(
                experiment_id=experiment_id,
                name=run.config.name,
                status=run.status,
            )

        return TestResult(
            experiment_id=experiment_id,
            name=run.config.name,
            status=run.status,
            test_category=run.config.test_category,
            testing_level=run.config.testing_level,
            stats=run.results.get("stats", {}),
            insights=run.results.get("insights", []),
            posture=run.results.get("posture", {}),
            exec_t=run.results.get("exec_t", {}),
        )

    def get_logs(self, experiment_id: str, result: Optional[str] = None,
                 page: int = 1, size: int = 50) -> PaginatedLogs:
        run = self._runs.get(experiment_id)
        logs = run.logs if run else self._read_logs_from_files(experiment_id)

        # Filter
        if result:
            logs = [l for l in logs if l.get("result") == result]

        # Paginate
        total = len(logs)
        start = (page - 1) * size
        page_logs = logs[start:start + size]

        return PaginatedLogs(
            data=page_logs,
            total=total,
            page=page,
            size=size,
            has_next_page=(start + size) < total,
        )

    def get_posture(self, experiment_id: Optional[str] = None) -> Posture:
        if experiment_id:
            run = self._runs.get(experiment_id)
            posture_data = run.results.get("posture", {}) if run and run.results else {}
        else:
            # Read from latest local results
            posture_data = self._read_latest_posture()

        if not posture_data:
            return Posture()

        return Posture(
            overall_score=posture_data.get("posture"),
            grade=posture_data.get("grade"),
        )

    def terminate(self, experiment_id: str) -> None:
        run = self._runs.get(experiment_id)
        if run:
            run._terminated.set()

    def list_experiments(self, page: int = 1, size: int = 50) -> dict:
        results_dir = Path(".humanbound/results")
        if not results_dir.exists():
            return {"data": [], "total": 0}

        experiments = []
        for d in sorted(results_dir.iterdir(), reverse=True):
            meta_file = d / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text())
                experiments.append(meta)

        total = len(experiments)
        start = (page - 1) * size
        return {
            "data": experiments[start:start + size],
            "total": total,
            "page": page,
            "has_next_page": (start + size) < total,
        }

    # --- File reading helpers ---

    def _read_result_from_files(self, experiment_id):
        from .schemas import ExperimentMeta

        meta_file = Path(f".humanbound/results/{experiment_id}/meta.json")
        if not meta_file.exists():
            return TestResult(experiment_id=experiment_id, name="", status="Unknown")

        raw = json.loads(meta_file.read_text())
        meta = ExperimentMeta(**raw)
        results = meta.results.model_dump()
        return TestResult(
            experiment_id=experiment_id,
            name=meta.name,
            status=meta.status,
            test_category=meta.test_category,
            testing_level=meta.testing_level,
            stats=results.get("stats", {}),
            insights=results.get("insights", []),
            posture=results.get("posture") or {},
            exec_t=results.get("exec_t", {}),
        )

    def _read_logs_from_files(self, experiment_id):
        logs_file = Path(f".humanbound/results/{experiment_id}/logs.jsonl")
        if not logs_file.exists():
            return []
        logs = []
        for line in logs_file.read_text().strip().split("\n"):
            if line.strip():
                logs.append(json.loads(line))
        return logs

    def _read_latest_posture(self):
        results_dir = Path(".humanbound/results")
        if not results_dir.exists():
            return {}
        exp_dirs = sorted(results_dir.iterdir(), reverse=True)
        for d in exp_dirs:
            meta_file = d / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text())
                results = meta.get("results", {})
                posture = results.get("posture") or meta.get("posture")
                if posture:
                    return posture
        return {}


def _debug_on_turn(turn_info: dict):
    """Print per-turn debug output."""
    cat = turn_info.get("category", "")
    turn = turn_info.get("turn", 0)
    total = turn_info.get("total_turns", 0)
    user_msg = (turn_info.get("user_msg", "") or "")[:120]
    bot_resp = (turn_info.get("bot_response", "") or "")[:120]
    score = turn_info.get("score", "")

    score_str = f" | score={score}/10" if score != "" else ""
    print(f"  [{cat}] Turn {turn}/{total}{score_str}")
    print(f"    U: {user_msg}{'...' if len(turn_info.get('user_msg', '')) > 120 else ''}")
    print(f"    A: {bot_resp}{'...' if len(turn_info.get('bot_response', '')) > 120 else ''}")


def _debug_on_verdict(verdict_info: dict):
    """Print per-conversation verdict in debug mode."""
    cat = verdict_info.get("category", "")
    strategy = (verdict_info.get("strategy", "") or "")[:80]
    result = verdict_info.get("result", "")
    severity = verdict_info.get("severity", 0)
    confidence = verdict_info.get("confidence", 0)
    explanation = (verdict_info.get("explanation", "") or "")[:150]
    turns = verdict_info.get("turns", 0)
    exec_t = verdict_info.get("exec_t", 0)

    result_marker = "\033[32mPASS\033[0m" if result == "pass" else "\033[31mFAIL\033[0m"
    print(f"\n  [{cat}] {result_marker} severity={severity} confidence={confidence} ({turns} turns, {exec_t:.1f}s)")
    if strategy:
        print(f"    Strategy: {strategy}...")
    if result == "fail" and explanation:
        print(f"    {explanation}...")
    print()


def _load_orchestrator(test_category: str):
    """Dynamically load the orchestrator module for the given test category.

    Supports:
    - humanbound/adversarial/owasp_agentic (or just owasp_agentic)
    - humanbound/adversarial/owasp_single_turn (or just owasp_single_turn)
    - humanbound/behavioral/qa (or just behavioral, or --qa flag)

    Returns module with orchestrator_generate, orchestrator_run, compute_quota.
    """
    # Normalize category name
    cat = test_category.lower().strip("/")
    short = cat.split("/")[-1] if "/" in cat else cat

    if short in ("owasp_agentic", "owasp_agentic_multi_turn"):
        from .orchestrators.owasp_agentic import orchestrator
        return orchestrator
    elif short in ("owasp_single_turn",):
        from .orchestrators.owasp_single_turn import orchestrator
        return orchestrator
    elif short in ("qa", "behavioral"):
        from .orchestrators.behavioral_qa import orchestrator
        return orchestrator
    else:
        # Try loading from ~/.humanbound/orchestrators/ (custom)
        custom_path = Path.home() / ".humanbound" / "orchestrators" / short
        if custom_path.exists() and (custom_path / "orchestrator.py").exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"custom_orchestrator_{short}",
                str(custom_path / "orchestrator.py"),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        raise ValueError(
            f"Unknown orchestrator: {test_category}\n\n"
            f"Available orchestrators:\n"
            f"  humanbound/adversarial/owasp_agentic      (default)\n"
            f"  humanbound/adversarial/owasp_single_turn\n"
            f"  humanbound/behavioral/qa\n\n"
            f"Install custom: hb orchestrators install --source ./my-orchestrator"
        )


def _resolve_provider():
    """Resolve LLM provider from env vars or config file.

    Priority: env vars > config file > error
    """
    name = os.environ.get("HB_PROVIDER")
    api_key = os.environ.get("HB_API_KEY")
    model = os.environ.get("HB_MODEL")
    endpoint = os.environ.get("HB_ENDPOINT")

    # Fallback to config file
    if not name:
        config = _read_config_file()
        name = config.get("provider")
        api_key = api_key or config.get("api_key")
        model = model or config.get("model")
        endpoint = endpoint or config.get("endpoint")

    if not name:
        raise ValueError(
            "No LLM provider configured.\n\n"
            "Option 1: Set environment variables\n"
            "  export HB_PROVIDER=openai\n"
            "  export HB_API_KEY=sk-...\n\n"
            "Option 2: Use config file\n"
            "  hb config set provider openai\n"
            "  hb config set api-key sk-...\n\n"
            "Option 3: Use ollama (full local isolation)\n"
            "  export HB_PROVIDER=ollama\n"
            "  export HB_MODEL=llama3.1:8b\n\n"
            "Option 4: Use managed LLM (requires login)\n"
            "  hb login"
        )

    integration = {}
    if api_key:
        integration["api_key"] = api_key
    if model:
        integration["model"] = model
    if endpoint:
        integration["endpoint"] = endpoint

    return {"name": name, "integration": integration}


def _read_config_file():
    """Read ~/.humanbound/config.yaml if it exists."""
    config_path = Path.home() / ".humanbound" / "config.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml
        return yaml.safe_load(config_path.read_text()) or {}
    except ImportError:
        # Fallback to simple key=value parsing
        config = {}
        for line in config_path.read_text().strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                config[key.strip()] = value.strip()
        return config
