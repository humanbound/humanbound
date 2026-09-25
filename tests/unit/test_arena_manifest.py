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


def test_agent_yaml_omits_defaults_the_author_never_wrote():
    agent = {
        "scope": {"business": "Reprices a catalogue."},
        "intents": {"permitted": ["Read pages"], "restricted": ["Leak floor price"]},
    }
    doc = _with(agent=agent)
    m = parse_manifest(doc)
    assert m.agent_yaml() == agent


def test_agent_yaml_preserves_extra_null_valued_keys():
    agent = copy.deepcopy(VALID["agent"])
    agent["tools"] = None
    doc = _with(agent=agent)
    m = parse_manifest(doc)
    assert m.agent_yaml() == agent


def test_agent_block_rejects_duplicate_capability_keys():
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_with(agent__capabilities=["tools", "tools"]))
    assert "duplicate capability" in str(exc.value)


@pytest.mark.parametrize(
    "changes, fragment",
    [
        ({"id": "Bad Id"}, "\n  id:"),
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


def test_integration_path_must_start_with_slash():
    with pytest.raises(ManifestError, match="integration.path"):
        parse_manifest(_with(integration={"type": "a2a", "path": "a2a"}))


def test_http_call_endpoint_must_start_with_slash():
    with pytest.raises(ManifestError, match="endpoint"):
        parse_manifest(
            _with(
                integration__chat_completion={"endpoint": "run", "payload": {"prompt": "$PROMPT"}}
            )
        )


def test_chat_completion_payload_must_contain_prompt_placeholder():
    with pytest.raises(ManifestError, match=r"chat_completion\.payload must contain \$PROMPT"):
        parse_manifest(
            _with(integration__chat_completion={"endpoint": "/run", "payload": {"x": "y"}})
        )


def test_chat_completion_payload_prompt_placeholder_is_case_insensitive_and_nested():
    doc = _with(
        integration__chat_completion={
            "endpoint": "/run",
            "payload": {"nested": {"list": [1, "$prompt"]}},
        }
    )
    assert parse_manifest(doc).integration.chat_completion.payload["nested"]["list"][1] == "$prompt"


def test_future_schema_version_asks_for_upgrade():
    with pytest.raises(ManifestError, match="newer hb"):
        parse_manifest(_with(schema_version=SCHEMA_VERSION + 1))


def test_future_schema_version_as_string_asks_for_upgrade():
    with pytest.raises(ManifestError, match="newer hb"):
        parse_manifest(_with(schema_version=str(SCHEMA_VERSION + 1)))


def test_zero_schema_version_is_invalid():
    with pytest.raises(ManifestError, match="schema_version"):
        parse_manifest(_with(schema_version=0))


def test_load_manifest_reads_yaml(tmp_path):
    import yaml

    f = tmp_path / "arena.yaml"
    f.write_text(yaml.safe_dump(VALID))
    assert load_manifest(f).name == "PriceWatch"


def test_load_manifest_reports_unreadable_file(tmp_path):
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path / "missing.yaml")


def test_load_manifest_reports_undecodable_file(tmp_path):
    f = tmp_path / "arena.yaml"
    f.write_bytes(b"\xff\xfe\x00\x01invalid utf-8 \xff")
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(f)


def test_paths_follow_home_and_port_env(arena_home, monkeypatch):
    assert paths.arena_dir() == arena_home
    assert paths.gateway_url() == "http://127.0.0.1:11500"
    monkeypatch.setenv("HB_ARENA_PORT", "12001")
    assert paths.gateway_port() == 12001
    assert paths.gateway_url() == "http://127.0.0.1:12001"
    assert paths.gateway_url(port=9999) == "http://127.0.0.1:9999"


def test_gateway_port_rejects_non_numeric_env(monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "not-a-port")
    with pytest.raises(ValueError, match="HB_ARENA_PORT must be a port number, got 'not-a-port'"):
        paths.gateway_port()


@pytest.mark.parametrize(
    "env",
    [
        {"required": ["HB_API_KEY"]},
        {"optional": ["hb_token"]},
        {"required": ["HUMANBOUND_API_KEY"]},
        {"optional": ["Humanbound_Session"]},
    ],
)
def test_env_names_reserved_for_hb_credentials_are_rejected(env):
    with pytest.raises(ManifestError, match="reserved for hb's own credentials"):
        parse_manifest(_with(runtime__env=env))


@pytest.mark.parametrize("name", ["1BAD", "A-B", "A B", "", "A=B"])
def test_env_names_must_be_valid_identifiers(name):
    with pytest.raises(ManifestError, match="runtime.env"):
        parse_manifest(_with(runtime__env={"required": [name]}))


def test_env_names_that_merely_contain_hb_are_allowed():
    m = parse_manifest(_with(runtime__env={"required": ["OPENAI_API_KEY", "MY_HB_THING"]}))
    assert m.runtime.env.required == ["OPENAI_API_KEY", "MY_HB_THING"]


@pytest.mark.parametrize("path", ["health", "", "http://evil/health"])
def test_health_path_must_start_with_slash(path):
    with pytest.raises(ManifestError, match="runtime.health.path"):
        parse_manifest(_with(runtime__health={"path": path}))


def test_context_is_capped_at_1500_chars():
    assert parse_manifest(_with(context="x" * 1500)).context == "x" * 1500
    with pytest.raises(ManifestError, match="context"):
        parse_manifest(_with(context="x" * 1501))
