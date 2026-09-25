# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Local runs save the scope they tested against in meta.json, so `hb guardrails
--format yaml` can build the humanbound-firewall agent.yaml without a scope file."""

from __future__ import annotations

import json

from humanbound_cli.engine.local_runner import _LocalRun, _scope_to_save
from humanbound_cli.engine.runner import TestConfig as _TestConfig
from humanbound_cli.engine.scope import from_scope_file

SCOPE_FILE = """\
business_scope: Quotes
permitted: [Quote]
restricted: [Discount]
capabilities: {tools: true}
"""


def test_meta_json_keeps_the_scope_and_its_capabilities(tmp_path, monkeypatch):
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(SCOPE_FILE)
    run = _LocalRun("exp-scope", _TestConfig(scope_path=str(scope_file)))
    run.scope = _scope_to_save(from_scope_file(str(scope_file)), str(scope_file))

    monkeypatch.chdir(tmp_path)
    run._save_results()

    meta = json.loads((tmp_path / ".humanbound/results/exp-scope/meta.json").read_text())
    assert meta["scope"]["overall_business_scope"] == "Quotes"
    assert meta["scope"]["intents"] == {"permitted": ["Quote"], "restricted": ["Discount"]}
    assert meta["scope"]["capabilities"] == {"tools": True}


def test_invalid_scope_file_capabilities_do_not_break_a_run(tmp_path):
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text("business_scope: Quotes\ncapabilities: {vision: true}\n")

    saved = _scope_to_save(from_scope_file(str(scope_file)), str(scope_file))

    assert saved["overall_business_scope"] == "Quotes"
    assert "capabilities" not in saved


def test_scope_without_a_file_is_saved_as_resolved():
    scope = {"overall_business_scope": "AI assistant", "intents": {}, "more_info": ""}

    assert _scope_to_save(scope, None) == scope
    assert _scope_to_save(None, None) is None
