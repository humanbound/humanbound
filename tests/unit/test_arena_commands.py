# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import pytest
import yaml
from click.testing import CliRunner
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import catalog, runtime
from humanbound_cli.main import cli

CATALOG = ARENA_FIXTURES / "catalog"
ECHO_YAML = CATALOG / "agents" / "echo" / "arena.yaml"
cli_runner = CliRunner()


@pytest.fixture
def arena_env(arena_home, monkeypatch):
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    monkeypatch.setattr(runtime, "preflight", lambda m=None: None)
    return arena_home


def invoke(*args):
    return cli_runner.invoke(cli, ["arena", *args], catch_exceptions=False)


def flat(result):
    """Output with whitespace collapsed, so Rich line-wrapping can't break assertions."""
    return " ".join(result.output.split())


def test_config_set_get_unset_masks_values(arena_env):
    assert invoke("config", "set", "OPENAI_API_KEY=sk-abcdefghijklmnop").exit_code == 0
    out = invoke("config", "get").output
    assert "OPENAI_API_KEY" in out and "sk-…mnop" in out and "abcdefgh" not in out
    assert invoke("config", "unset", "OPENAI_API_KEY").exit_code == 0
    assert "OPENAI_API_KEY" not in invoke("config", "get").output


def test_config_set_rejects_malformed_pairs(arena_env):
    result = invoke("config", "set", "NOEQUALS")
    assert result.exit_code == 1 and "KEY=VALUE" in flat(result)


def test_config_set_rejects_bad_values_and_reserved_names(arena_env):
    quoted = invoke("config", "set", "OPENAI_API_KEY='sk-secret-value'")
    assert quoted.exit_code == 1 and "quotes" in flat(quoted)
    assert "sk-secret-value" not in quoted.output
    reserved = invoke("config", "set", "HB_API_KEY=abc")
    assert reserved.exit_code == 1 and "reserved" in flat(reserved)
    assert "HB_API_KEY" not in invoke("config", "get").output


def test_validate_ok_and_failure(arena_env, tmp_path):
    ok = invoke("validate", str(ECHO_YAML))
    assert ok.exit_code == 0 and "echo 0.1.0" in flat(ok)
    bad = tmp_path / "arena.yaml"
    bad.write_text(yaml.safe_dump({"schema_version": 1, "id": "x"}))
    result = invoke("validate", str(bad))
    assert result.exit_code == 1 and "invalid arena.yaml" in flat(result)


def test_ls_shows_catalog_with_install_state(arena_env, monkeypatch):
    monkeypatch.setattr(runtime, "list_running", lambda: [])
    out = invoke("ls").output
    assert "echo" in out and "0.1.0" in out


def test_ls_works_when_docker_is_down(arena_env, monkeypatch):
    def down():
        raise runtime.DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "list_running", down)
    result = invoke("ls")
    assert result.exit_code == 0 and "echo" in result.output


def test_info_and_agent_yaml(arena_env):
    out = flat(invoke("info", "echo"))
    assert "Echo" in out and "V1" in out
    # Manifest text is printed literally, never as Rich markup: "[llm001]" survives.
    assert "[llm001]" in out
    raw = invoke("info", "echo", "--agent-yaml").output
    assert yaml.safe_load(raw)["scope"]["business"].startswith("Echo agent")


def test_pull_caches_manifest_and_pulls_image(arena_env, monkeypatch):
    pulled = []
    monkeypatch.setattr(runtime, "pull", lambda m, d: pulled.append(m.id))
    result = invoke("pull", "echo")
    assert result.exit_code == 0
    assert pulled == ["echo"]
    assert catalog.installed("echo") is not None


def test_pull_reports_docker_errors(arena_env, monkeypatch):
    def fail(m, d):
        raise runtime.DockerError("'docker pull' failed: [denied] no access")

    monkeypatch.setattr(runtime, "pull", fail)
    result = invoke("pull", "echo")
    assert result.exit_code == 1 and "[denied] no access" in flat(result)


def test_unknown_agent_suggests(arena_env):
    result = invoke("pull", "ecko")
    assert result.exit_code == 1 and "Did you mean: echo" in flat(result)


def test_unreachable_catalog_fails_cleanly(arena_home, monkeypatch, tmp_path):
    monkeypatch.setenv("HB_ARENA_INDEX", str(tmp_path / "missing"))
    result = invoke("info", "echo")
    assert result.exit_code == 1 and "cannot load the arena catalog" in flat(result)
