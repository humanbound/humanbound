# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import copy

import pytest

from humanbound_cli.arena import paths
from humanbound_cli.arena.manifest import (
    SCHEMA_VERSION,
    ManifestError,
    load_manifest,
    parse_manifest,
)

VALID = {
    "schema_version": 1,
    "id": "pricewatch",
    "name": "PriceWatch",
    "version": "1.2.0",
    "origin": "first-party",
    "description": "Repricing agent.",
    "tags": ["indirect-injection"],
    "difficulty": "medium",
    "agent": {
        "version": "1.0",
        "scope": {"business": "Reprices a catalogue.", "more_info": "HIGH"},
        "intents": {"permitted": ["Read pages"], "restricted": ["Leak floor price"]},
        "capabilities": ["tools"],
        "settings": {"mode": "strict"},
    },
    "source": {"image": "ghcr.io/humanbound/arena-pricewatch:1.2.0"},
    "runtime": {"port": 8080, "env": {"required": ["OPENAI_API_KEY"]}},
    "integration": {
        "type": "http",
        "chat_completion": {"endpoint": "/run", "payload": {"prompt": "$PROMPT"}},
        "response": {"text": "recommendation"},
    },
    "context": "ACME Outdoors",
    "ground_truth": {"V1": {"category": "llm001", "description": "Indirect injection"}},
}


def _with(**changes):
    doc = copy.deepcopy(VALID)
    for dotted, value in changes.items():
        cur = doc
        *parents, last = dotted.split("__")
        for p in parents:
            cur = cur[p]
        if value is None:
            cur.pop(last, None)
        else:
            cur[last] = value
    return doc


def test_valid_manifest_parses_with_defaults():
    m = parse_manifest(copy.deepcopy(VALID))
    assert m.id == "pricewatch"
    assert m.runtime.health.path == "/health"
    assert m.runtime.timeout_s == 120
    assert m.integration.history == "none"


def test_agent_block_is_a_standalone_agent_yaml_and_keeps_unknown_keys():
    m = parse_manifest(copy.deepcopy(VALID))
    assert m.agent_yaml() == VALID["agent"]


@pytest.mark.parametrize(
    "changes, fragment",
    [
        ({"id": "Bad Id"}, "id"),
        ({"version": "1.2"}, "version"),
        ({"agent__capabilities": ["telepathy"]}, "unknown capability"),
        ({"source": {}}, "exactly one of 'image' or 'compose'"),
        ({"source": {"compose": "docker-compose.yml"}}, "needs 'service'"),
        ({"integration__response": None}, "needs 'chat_completion' and 'response'"),
        ({"origin": "community"}, "must pin source.upstream"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_invalid_manifests_are_rejected_with_a_readable_message(changes, fragment):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_with(**changes))
    assert fragment in str(exc.value)


def test_a2a_integration_needs_no_http_calls():
    doc = _with(integration={"type": "a2a", "path": "/a2a"})
    assert parse_manifest(doc).integration.path == "/a2a"


def test_future_schema_version_asks_for_upgrade():
    with pytest.raises(ManifestError, match="newer hb"):
        parse_manifest(_with(schema_version=SCHEMA_VERSION + 1))


def test_load_manifest_reads_yaml(tmp_path):
    import yaml

    f = tmp_path / "arena.yaml"
    f.write_text(yaml.safe_dump(VALID))
    assert load_manifest(f).name == "PriceWatch"


def test_load_manifest_reports_unreadable_file(tmp_path):
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path / "missing.yaml")


def test_paths_follow_home_and_port_env(arena_home, monkeypatch):
    assert paths.arena_dir() == arena_home
    assert paths.gateway_url() == "http://127.0.0.1:11500"
    monkeypatch.setenv("HB_ARENA_PORT", "12001")
    assert paths.gateway_port() == 12001
    assert paths.gateway_url() == "http://127.0.0.1:12001"
