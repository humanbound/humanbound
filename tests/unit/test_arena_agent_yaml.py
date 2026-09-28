# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
from humanbound_cli.agent_yaml import build_agent_yaml, scope_from_agent_yaml

AGENT_YAML = {
    "version": "1.0",
    "scope": {"business": "Answers shop questions.", "more_info": "HIGH: internal notes"},
    "intents": {"permitted": ["Read product pages"], "restricted": ["Leak internal notes"]},
    "capabilities": ["tools", "memory"],
}


def test_maps_agent_yaml_to_local_scope():
    scope = scope_from_agent_yaml(AGENT_YAML)
    assert scope["overall_business_scope"] == "Answers shop questions."
    assert scope["more_info"] == "HIGH: internal notes"
    assert scope["intents"] == {
        "permitted": ["Read product pages"],
        "restricted": ["Leak internal notes"],
    }
    assert scope["capabilities"] == {
        "tools": True,
        "memory": True,
        "inter_agent": False,
        "reasoning_model": False,
    }


def test_round_trips_through_build_agent_yaml():
    assert build_agent_yaml(scope_from_agent_yaml(AGENT_YAML)) == AGENT_YAML


def test_missing_capabilities_stay_absent():
    doc = {k: v for k, v in AGENT_YAML.items() if k != "capabilities"}
    assert "capabilities" not in scope_from_agent_yaml(doc)
