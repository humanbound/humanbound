# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb orchestrators list / new / validate`, and the scaffold `new` writes."""

import json
import sys

import pytest
from click.testing import CliRunner

from humanbound_cli.engine.callbacks import EngineCallbacks
from humanbound_cli.engine.local_runner import _load_orchestrator
from humanbound_cli.engine.presenter import run as presenter_run
from humanbound_cli.main import cli

runner = CliRunner()


@pytest.fixture
def orchestrators_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".humanbound" / "orchestrators"
    yield root
    for name in [n for n in sys.modules if n.startswith("humanbound_custom_orchestrator_")]:
        del sys.modules[name]


def _hb(*args):
    return runner.invoke(cli, ["orchestrators", *args])


def _write(path, orchestrator_py, manifest=None):
    path.mkdir(parents=True)
    (path / "orchestrator.py").write_text(orchestrator_py)
    if manifest is not None:
        (path / "manifest.yaml").write_text(manifest)


VALID_ORCHESTRATOR = (
    "def orchestrator_generate(model_provider, experiment):\n    return {}\n\n\n"
    "def orchestrator_run(organisation_id, model_provider, experiment, prompts,\n"
    "                     few_shots_model, callbacks=None):\n    return None\n"
)


# ── list ──


def test_list_shows_builtins_without_a_custom_dir(orchestrators_dir):
    result = _hb("list")

    assert result.exit_code == 0, result.output
    for name in ("owasp_agentic", "owasp_single_turn", "behavioral_qa"):
        assert name in result.output
    assert "hb orchestrators new <name>" in result.output


def test_list_shows_custom_orchestrators_from_their_manifest(orchestrators_dir):
    _write(
        orchestrators_dir / "pii_leak",
        VALID_ORCHESTRATOR,
        "name: pii_leak\nversion: 2.3.1\ndescription: Finds PII\n",
    )

    result = _hb("list")

    assert result.exit_code == 0, result.output
    assert "pii_leak" in result.output
    assert "2.3.1" in result.output
    assert "Finds PII" in result.output


def test_list_flags_a_directory_without_orchestrator_py(orchestrators_dir):
    (orchestrators_dir / "half_done").mkdir(parents=True)

    result = _hb("list")

    assert result.exit_code == 0, result.output
    assert "half_done" in result.output
    assert "no orchestrator.py" in result.output


# ── new ──


def test_new_scaffold_passes_validate(orchestrators_dir):
    result = _hb("new", "pii_leak", "--description", 'Finds "PII": names, emails')

    assert result.exit_code == 0, result.output
    path = orchestrators_dir / "pii_leak"
    assert sorted(p.name for p in path.iterdir()) == [
        "config.py",
        "generator.py",
        "judge.py",
        "manifest.yaml",
        "orchestrator.py",
    ]
    assert "$name" not in (path / "orchestrator.py").read_text()

    import yaml

    manifest = yaml.safe_load((path / "manifest.yaml").read_text())
    assert manifest["name"] == "pii_leak"
    assert manifest["description"] == 'Finds "PII": names, emails'

    result = _hb("validate", "pii_leak")
    assert result.exit_code == 0, result.output
    assert "run it with -t pii_leak" in result.output


@pytest.mark.parametrize("name", ["qa", "owasp_agentic", "behavioral_qa"])
def test_new_refuses_a_builtin_name(orchestrators_dir, name):
    result = _hb("new", name)

    assert result.exit_code == 2
    assert "built-in" in result.output
    assert not (orchestrators_dir / name).exists()


@pytest.mark.parametrize("name", ["PII", "1st", "pii-leak", "../escape"])
def test_new_refuses_names_that_are_not_identifiers(orchestrators_dir, name):
    result = _hb("new", name)

    assert result.exit_code == 2
    assert not orchestrators_dir.exists()


def test_new_does_not_overwrite_an_existing_directory(orchestrators_dir):
    path = orchestrators_dir / "pii_leak"
    path.mkdir(parents=True)
    (path / "config.py").write_text("MINE = True\n")

    result = _hb("new", "pii_leak")

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert (path / "config.py").read_text() == "MINE = True\n"


def test_new_with_dir_then_validate_by_path(orchestrators_dir, tmp_path):
    work = tmp_path / "repo"

    result = _hb("new", "pii_leak", "--dir", str(work))
    assert result.exit_code == 0, result.output
    assert not orchestrators_dir.exists()

    result = _hb("validate", str(work / "pii_leak"))
    assert result.exit_code == 0, result.output
    assert "Copy or link it into" in result.output


# ── validate ──


def test_validate_reports_a_missing_entry_point(orchestrators_dir):
    _write(orchestrators_dir / "broken", "def orchestrator_generate(p, e):\n    return {}\n")

    result = _hb("validate", "broken")

    assert result.exit_code == 1
    assert "does not define: orchestrator_run" in result.output


def test_validate_reports_an_import_error(orchestrators_dir):
    _write(orchestrators_dir / "broken", "from .nope import thing\n" + VALID_ORCHESTRATOR)

    result = _hb("validate", "broken")

    assert result.exit_code == 1
    assert "ModuleNotFoundError" in result.output


def test_validate_reports_a_signature_hb_test_cannot_call(orchestrators_dir):
    _write(
        orchestrators_dir / "broken",
        "def orchestrator_generate(experiment):\n    return {}\n\n\n"
        "def orchestrator_run(model_provider, experiment, prompts):\n    return None\n",
    )

    result = _hb("validate", "broken")

    assert result.exit_code == 1
    assert "orchestrator_generate cannot be called" in result.output
    assert "orchestrator_run cannot be called" in result.output


def test_validate_reports_invalid_manifest_yaml(orchestrators_dir):
    _write(orchestrators_dir / "broken", VALID_ORCHESTRATOR, "name: [unclosed\n")

    result = _hb("validate", "broken")

    assert result.exit_code == 1
    assert "not valid YAML" in result.output


def test_validate_warns_but_passes_without_a_manifest(orchestrators_dir):
    _write(orchestrators_dir / "bare", VALID_ORCHESTRATOR)

    result = _hb("validate", "bare")

    assert result.exit_code == 0, result.output
    assert "no manifest.yaml" in result.output


def test_validate_rejects_a_directory_shadowed_by_a_builtin(orchestrators_dir):
    _write(orchestrators_dir / "qa", VALID_ORCHESTRATOR)

    result = _hb("validate", "qa")

    assert result.exit_code == 1
    assert "runs the built-in" in result.output


def test_validate_unknown_name(orchestrators_dir):
    result = _hb("validate", "nothing_here")

    assert result.exit_code == 1
    assert "hb orchestrators list" in result.output


# ── the scaffold runs ──


class _FakeBot:
    def __init__(self, bot_config, e_id):
        pass

    def init(self):
        return {}

    async def ping(self, base_payload, u_prompt, conversation=None):
        return f"echo: {u_prompt}", 0.5, None


class _FakeLLM:
    def __init__(self, verdicts):
        self.verdicts = iter(verdicts)

    def ping(self, system_p, user_p, *args, **kwargs):
        return next(self.verdicts)


def test_scaffold_runs_and_its_logs_feed_the_presenter(orchestrators_dir, monkeypatch):
    assert _hb("new", "pii_leak").exit_code == 0
    module = _load_orchestrator("pii_leak")
    judge_module = sys.modules[module.__package__ + ".judge"]

    verdicts = [
        'Sure: {"result": "fail", "severity": 80, "confidence": 90, "explanation": "leaked"}',
        '{"result": "pass", "severity": 0, "confidence": 95, "explanation": "refused"}',
        "not json at all",
    ]
    monkeypatch.setattr(module, "Bot", _FakeBot)
    monkeypatch.setattr(judge_module, "get_llm_pinger", lambda provider: _FakeLLM(verdicts))

    experiment = {
        "id": "exp-1",
        "configuration": {"scope": {"overall_business_scope": "Bank"}, "integration": {}},
    }
    prompts = module.orchestrator_generate({"name": "openai"}, experiment)
    assert list(prompts) == ["system_prompt_leak"]
    assert len(prompts["system_prompt_leak"]) == 3

    logs, statuses, errors, judged = [], [], [], []
    callbacks = EngineCallbacks(
        on_logs=logs.extend,
        on_complete=statuses.append,
        on_error=lambda title, details: errors.append(title),
        on_verdict=judged.append,
    )
    module.orchestrator_run(None, {"name": "openai"}, experiment, prompts, None, callbacks)

    assert statuses == ["Finished"]
    assert [log["result"] for log in logs] == ["fail", "pass", "error"]
    assert logs[0]["fail_category"] == "system_prompt_leak"
    assert logs[0]["severity"] == 80
    assert logs[0]["conversation"][0]["a"].startswith("echo: ")
    assert logs[1]["fail_category"] == ""
    assert errors == ["JSONDecodeError"]
    assert [v["result"] for v in judged] == ["fail", "pass"]

    results = presenter_run(None, logs, test_category="pii_leak")
    assert results["stats"]["fail"] == 1
    json.dumps(results)  # what LocalTestRunner writes to meta.json


def test_scaffold_stops_when_terminated(orchestrators_dir, monkeypatch):
    assert _hb("new", "pii_leak").exit_code == 0
    module = _load_orchestrator("pii_leak")
    monkeypatch.setattr(module, "Bot", _FakeBot)

    statuses = []
    callbacks = EngineCallbacks(is_terminated=lambda: True, on_complete=statuses.append)
    experiment = {"id": "exp-1", "configuration": {"scope": {}, "integration": {}}}
    prompts = module.orchestrator_generate({"name": "openai"}, experiment)
    module.orchestrator_run(None, {"name": "openai"}, experiment, prompts, None, callbacks)

    assert statuses == []


# ── built-in names still resolve ──


@pytest.mark.parametrize(
    "category, package",
    [
        ("humanbound/adversarial/owasp_agentic", "owasp_agentic"),
        ("owasp_agentic_multi_turn", "owasp_agentic"),
        ("humanbound/adversarial/owasp_single_turn", "owasp_single_turn"),
        ("humanbound/behavioral/qa", "behavioral_qa"),
        ("behavioral", "behavioral_qa"),
        ("QA", "behavioral_qa"),
    ],
)
def test_builtin_categories_resolve(category, package):
    module = _load_orchestrator(category)

    assert module.__name__ == f"humanbound_cli.engine.orchestrators.{package}.orchestrator"
