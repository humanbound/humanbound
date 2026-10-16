# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Custom orchestrators loaded from ~/.humanbound/orchestrators/<name>/."""

import sys

import pytest

from humanbound_cli.engine.local_runner import _load_orchestrator

ORCHESTRATOR_PY = """\
from .config import CATEGORY
from .generator import opening_prompts


def orchestrator_generate(model_provider, experiment):
    return {CATEGORY: opening_prompts()}


def orchestrator_run(organisation_id, model_provider, experiment, prompts,
                     few_shots_model, callbacks=None):
    return None


def compute_quota(testing_level, dataset_len):
    return dataset_len
"""


@pytest.fixture
def orchestrators_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".humanbound" / "orchestrators"
    root.mkdir(parents=True)
    yield root
    for name in [n for n in sys.modules if n.startswith("humanbound_custom_orchestrator_")]:
        del sys.modules[name]


def _write_documented_layout(path, category="custom001"):
    """The package layout docs/local-engine/orchestrators.md tells users to create."""
    path.mkdir()
    (path / "manifest.yaml").write_text("name: my-orchestrator\nversion: 1.0.0\n")
    (path / "config.py").write_text(f"CATEGORY = {category!r}\n")
    (path / "generator.py").write_text("def opening_prompts():\n    return ['Hi there']\n")
    (path / "judge.py").write_text("")
    (path / "orchestrator.py").write_text(ORCHESTRATOR_PY)


def test_orchestrator_can_import_its_sibling_modules(orchestrators_dir):
    _write_documented_layout(orchestrators_dir / "my_orch")

    module = _load_orchestrator("my_orch")

    assert module.orchestrator_generate({}, {}) == {"custom001": ["Hi there"]}
    assert module.compute_quota("unit", 3) == 3


def test_package_with_init_file_loads(orchestrators_dir):
    path = orchestrators_dir / "my_orch"
    _write_documented_layout(path)
    (path / "__init__.py").write_text("LOADED_AS_PACKAGE = True\n")

    module = _load_orchestrator("my_orch")

    assert module.orchestrator_generate({}, {}) == {"custom001": ["Hi there"]}
    assert sys.modules[module.__package__].LOADED_AS_PACKAGE is True


def test_namespaced_category_resolves_to_custom_dir(orchestrators_dir):
    _write_documented_layout(orchestrators_dir / "my_orch")

    module = _load_orchestrator("acme/adversarial/my_orch")

    assert module.orchestrator_generate({}, {}) == {"custom001": ["Hi there"]}


def test_two_custom_orchestrators_do_not_share_sibling_modules(orchestrators_dir):
    _write_documented_layout(orchestrators_dir / "first", category="first001")
    _write_documented_layout(orchestrators_dir / "second", category="second001")

    first = _load_orchestrator("first")
    second = _load_orchestrator("second")

    assert first.orchestrator_generate({}, {}) == {"first001": ["Hi there"]}
    assert second.orchestrator_generate({}, {}) == {"second001": ["Hi there"]}


def test_reload_picks_up_edits(orchestrators_dir):
    path = orchestrators_dir / "my_orch"
    _write_documented_layout(path)
    _load_orchestrator("my_orch")

    (path / "config.py").write_text("CATEGORY = 'edited001'\n")
    module = _load_orchestrator("my_orch")

    assert module.orchestrator_generate({}, {}) == {"edited001": ["Hi there"]}


def test_missing_interface_function_is_reported(orchestrators_dir):
    path = orchestrators_dir / "my_orch"
    path.mkdir()
    (path / "orchestrator.py").write_text("def orchestrator_generate(p, e):\n    return {}\n")

    with pytest.raises(ValueError, match="does not define: orchestrator_run, compute_quota"):
        _load_orchestrator("my_orch")


def test_unknown_orchestrator_points_at_the_custom_directory(orchestrators_dir):
    with pytest.raises(ValueError) as excinfo:
        _load_orchestrator("does_not_exist")

    message = str(excinfo.value)
    assert "~/.humanbound/orchestrators/<name>/orchestrator.py" in message
    assert "hb orchestrators install" not in message
