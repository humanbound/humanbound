# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import pytest
import yaml
from click.testing import CliRunner
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import catalog, daemon, runtime
from humanbound_cli.arena.runtime import RunningAgent
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


def test_top_level_help_mentions_arena_run_and_test_target():
    out = cli_runner.invoke(cli, ["--help"], catch_exceptions=False).output
    assert "hb arena run <agent>" in out
    assert "hb test --target arena://<agent>" in out


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


def _write_unreadable_config(arena_env):
    from humanbound_cli.arena import keys

    keys.config_file().parent.mkdir(parents=True, exist_ok=True)
    keys.config_file().write_bytes(b"OPENAI_API_KEY=\xff\xfe\n")


def test_config_get_fails_cleanly_on_unreadable_env_file(arena_env):
    _write_unreadable_config(arena_env)
    result = invoke("config", "get")
    assert result.exit_code == 1
    assert "cannot read" in flat(result)


def test_config_set_fails_cleanly_on_unreadable_env_file(arena_env):
    _write_unreadable_config(arena_env)
    result = invoke("config", "set", "A=1")
    assert result.exit_code == 1
    assert "cannot read" in flat(result)


def test_config_unset_fails_cleanly_on_unreadable_env_file(arena_env):
    _write_unreadable_config(arena_env)
    result = invoke("config", "unset", "OPENAI_API_KEY")
    assert result.exit_code == 1
    assert "cannot read" in flat(result)


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


def test_info_does_not_install_the_agent(arena_env):
    """'installed' means pulled/run, not merely browsed with `info`."""
    result = invoke("info", "echo")
    assert result.exit_code == 0
    assert catalog.installed("echo") is None
    assert "No arena agents installed" in invoke("ls", "--installed").output


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


# ── lifecycle (run, ps, logs, stop, reset, rm, endpoint, serve) ──

RUNNING = RunningAgent("echo", "0.1.0", "image", 49153)


@pytest.fixture
def docker_ok(arena_env, monkeypatch):
    state = {"running": [], "started": [], "stopped": [], "gateway": []}
    monkeypatch.delenv("ECHO_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "image_present", lambda image: True)

    def start(m, d, env):
        state["started"].append((m.id, env))
        state["running"] = [RUNNING]
        return RUNNING

    monkeypatch.setattr(runtime, "start", start)
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    monkeypatch.setattr(runtime, "list_running", lambda: state["running"])
    monkeypatch.setattr(
        runtime, "find_running", lambda i: next((a for a in state["running"] if a.id == i), None)
    )

    def stop(agent_id, kind):
        state["stopped"].append(agent_id)
        state["running"] = [a for a in state["running"] if a.id != agent_id]

    monkeypatch.setattr(runtime, "stop", stop)
    monkeypatch.setattr(daemon, "ensure_running", lambda port=None: "http://127.0.0.1:11500")
    monkeypatch.setattr(
        daemon, "stop_gateway", lambda port=None: state["gateway"].append("stopped") or True
    )
    return state


def _with_required_key(monkeypatch, tmp_path, origin="first-party"):
    """Make `catalog.installed` return an echo manifest that requires OPENAI_API_KEY."""
    from humanbound_cli.arena.manifest import load_manifest

    data = yaml.safe_load(ECHO_YAML.read_text())
    data["runtime"]["env"] = {"required": ["OPENAI_API_KEY"]}
    data["origin"] = origin
    if origin == "community":
        data["source"]["upstream"] = {"repo": "https://github.com/x/y", "ref": "abc123"}
    manifest_path = tmp_path / "arena.yaml"
    manifest_path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(
        catalog, "installed", lambda i, v=None: (load_manifest(manifest_path), tmp_path)
    )


def test_run_starts_agent_and_gateway_and_prints_endpoints(docker_ok):
    result = invoke("run", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok["started"] == [("echo", {})]
    out = flat(result)
    assert "http://127.0.0.1:11500/a2a/echo" in out
    assert "hb test --target arena://echo" in out
    assert "intentionally vulnerable" in out.lower()
    assert "no keys" in out.lower()


def test_run_prints_key_names_never_values(docker_ok, monkeypatch, tmp_path):
    _with_required_key(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value-123")
    result = invoke("run", "echo")
    assert result.exit_code == 0, result.output
    assert "Passing keys: OPENAI_API_KEY" in flat(result)
    assert "sk-super-secret-value-123" not in result.output
    assert "secret" not in result.output
    assert docker_ok["started"] == [("echo", {"OPENAI_API_KEY": "sk-super-secret-value-123"})]


def test_run_fails_fast_on_missing_keys(docker_ok, monkeypatch, tmp_path):
    _with_required_key(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = invoke("run", "echo")
    assert result.exit_code == 1
    assert "hb arena config set OPENAI_API_KEY=" in flat(result)
    assert docker_ok["started"] == []


def test_run_community_agent_never_reads_keys_from_the_shell(docker_ok, monkeypatch, tmp_path):
    _with_required_key(monkeypatch, tmp_path, origin="community")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-value")
    result = invoke("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "hb arena config set OPENAI_API_KEY=" in out
    assert "shell environment is not used for community agents" in out
    assert "sk-shell-value" not in result.output
    assert docker_ok["started"] == []


def test_run_community_agent_uses_arena_config(docker_ok, monkeypatch, tmp_path):
    from humanbound_cli.arena import keys

    _with_required_key(monkeypatch, tmp_path, origin="community")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-value")
    keys.set_value("OPENAI_API_KEY", "sk-from-config")
    result = invoke("run", "echo")
    assert result.exit_code == 0, result.output
    assert "Passing keys: OPENAI_API_KEY" in flat(result)
    assert docker_ok["started"] == [("echo", {"OPENAI_API_KEY": "sk-from-config"})]


def test_run_first_party_missing_key_hint_does_not_mention_community(
    docker_ok, monkeypatch, tmp_path
):
    _with_required_key(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = invoke("run", "echo")
    assert result.exit_code == 1
    assert "community" not in flat(result)


def test_run_env_file_values_reach_runtime_start(docker_ok, monkeypatch, tmp_path):
    _with_required_key(monkeypatch, tmp_path)
    env_file = tmp_path / "extra.env"
    env_file.write_text("OPENAI_API_KEY=sk-from-file\n")
    result = invoke("run", "echo", "--env-file", str(env_file))
    assert result.exit_code == 0, result.output
    assert docker_ok["started"] == [("echo", {"OPENAI_API_KEY": "sk-from-file"})]


def test_run_fails_cleanly_on_unreadable_env_file(docker_ok, tmp_path):
    bad = tmp_path / "bad.env"
    bad.write_bytes(b"OPENAI_API_KEY=\xff\xfe\n")
    result = invoke("run", "echo", "--env-file", str(bad))
    assert result.exit_code == 1
    assert "cannot read" in flat(result)
    assert docker_ok["started"] == []


def test_run_validates_port_before_preflight_pull_or_start(docker_ok, monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "not-a-port")
    preflighted = []
    monkeypatch.setattr(runtime, "preflight", lambda m=None: preflighted.append(True))
    result = invoke("run", "echo")
    assert result.exit_code == 1
    assert "HB_ARENA_PORT" in flat(result)
    assert preflighted == []
    assert docker_ok["started"] == []


def test_run_reports_health_timeout_with_logs(docker_ok, monkeypatch):
    def unhealthy(agent, health):
        raise runtime.HealthTimeout("echo did not become healthy within 30s")

    monkeypatch.setattr(runtime, "wait_healthy", unhealthy)
    monkeypatch.setattr(runtime, "last_logs", lambda i, k, lines=50: "Traceback: [boom]")
    result = invoke("run", "echo")
    assert result.exit_code == 1
    assert "Traceback: [boom]" in flat(result)
    assert docker_ok["stopped"] == ["echo"]


def test_run_reports_docker_errors(docker_ok, monkeypatch):
    def broken(m, d, env):
        raise runtime.DockerError("echo started but port 8080 is not published")

    monkeypatch.setattr(runtime, "start", broken)
    result = invoke("run", "echo")
    assert result.exit_code == 1 and "not published" in flat(result)


def test_run_gateway_failure(docker_ok, monkeypatch):
    def no_gateway(port=None):
        raise daemon.GatewayError("port 11500 is used by another program")

    monkeypatch.setattr(daemon, "ensure_running", no_gateway)
    result = invoke("run", "echo")
    assert result.exit_code == 1 and "used by another program" in flat(result)
    # The container did start before the gateway failed: it must be stopped, and the
    # user told so, rather than left running with no gateway to reach it through.
    assert docker_ok["stopped"] == ["echo"]
    assert "stopped" in flat(result).lower()


def test_first_run_notice_shown_exactly_once_across_two_runs(docker_ok):
    first = invoke("run", "echo")
    assert "intentionally vulnerable" in flat(first).lower()
    assert invoke("stop", "--all").exit_code == 0
    second = invoke("run", "echo")
    assert second.exit_code == 0, second.output
    assert "intentionally vulnerable" not in flat(second).lower()


def test_run_and_pull_telemetry_payloads_contain_only_agent_and_version(
    docker_ok, monkeypatch, tmp_path
):
    events = []
    monkeypatch.setattr(
        "humanbound_cli.commands.arena.telemetry.capture",
        lambda event, properties=None: events.append((event, properties)),
    )
    assert invoke("run", "echo").exit_code == 0
    monkeypatch.setattr(runtime, "pull", lambda m, d: None)
    assert invoke("pull", "echo").exit_code == 0
    assert events == [
        ("arena_run", {"agent": "echo", "version": "0.1.0"}),
        ("arena_pull", {"agent": "echo", "version": "0.1.0"}),
    ]


def test_ps_endpoint_and_stop_all(docker_ok):
    assert "No arena agents running" in flat(invoke("ps"))
    invoke("run", "echo")
    assert "echo" in invoke("ps").output
    endpoint = flat(invoke("endpoint", "echo"))
    assert "/a2a/echo/.well-known/agent-card.json" in endpoint
    assert "arena/echo" in endpoint and '"SendMessage"' in endpoint
    result = invoke("stop", "--all")
    assert result.exit_code == 0
    assert docker_ok["stopped"] == ["echo"]
    assert docker_ok["gateway"] == ["stopped"]


def test_stop_one_keeps_gateway_while_others_run(docker_ok):
    other = RunningAgent("other", "1.0.0", "image", 49154)
    invoke("run", "echo")
    docker_ok["running"].append(other)
    assert invoke("stop", "echo").exit_code == 0
    assert docker_ok["stopped"] == ["echo"] and docker_ok["gateway"] == []


def test_stop_unknown_agent(docker_ok):
    result = invoke("stop", "ghost")
    assert result.exit_code == 1 and "not running" in flat(result)


def test_stop_needs_an_agent_or_all(docker_ok):
    result = invoke("stop")
    assert result.exit_code == 1 and "--all" in flat(result)


def test_stop_when_docker_is_down(docker_ok, monkeypatch):
    def down():
        raise runtime.DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "list_running", down)
    monkeypatch.setattr(runtime, "find_running", lambda i: down())
    for args in (("--all",), ("echo",)):
        result = invoke("stop", *args)
        assert result.exit_code == 1 and "not running" in flat(result)
        assert "Docker" in flat(result)


def test_stop_all_stops_gateway_even_when_docker_is_down(docker_ok, monkeypatch):
    def down():
        raise runtime.DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "list_running", down)
    result = invoke("stop", "--all")
    assert result.exit_code == 1
    assert "Docker" in flat(result)
    assert docker_ok["gateway"] == ["stopped"]


def test_logs_streams_from_runtime(docker_ok, monkeypatch):
    invoke("run", "echo")
    calls = []
    monkeypatch.setattr(
        runtime, "logs", lambda i, k, follow=False, tail=200: calls.append((i, k, follow, tail))
    )
    assert invoke("logs", "echo", "--tail", "5").exit_code == 0
    assert calls == [("echo", "image", False, 5)]


def test_reset_goes_through_the_gateway(docker_ok, monkeypatch):
    invoke("run", "echo")
    calls = []
    from humanbound_cli.arena import target

    monkeypatch.setattr(target, "reset_via_gateway", lambda i, g: calls.append((i, g)))
    assert invoke("reset", "echo").exit_code == 0
    assert calls == [("echo", "http://127.0.0.1:11500")]


def test_reset_reports_gateway_errors(docker_ok, monkeypatch):
    invoke("run", "echo")
    from humanbound_cli.arena import target

    def fail(i, g):
        raise target.TargetError("could not reset echo: [boom]")

    monkeypatch.setattr(target, "reset_via_gateway", fail)
    result = invoke("reset", "echo")
    assert result.exit_code == 1 and "could not reset echo: [boom]" in flat(result)


def test_rm_stops_and_removes(docker_ok, monkeypatch):
    invoke("run", "echo")
    removed = []
    monkeypatch.setattr(runtime, "remove_images", lambda m, d: removed.append(m.id))
    assert invoke("rm", "echo").exit_code == 0
    assert removed == ["echo"] and docker_ok["stopped"] == ["echo"]
    assert catalog.installed("echo") is None
    assert docker_ok["gateway"] == ["stopped"]


def test_rm_unknown_or_invalid_agent(docker_ok):
    for agent_id in ("ghost", "../etc"):
        result = invoke("rm", agent_id)
        assert result.exit_code == 1 and "not installed" in flat(result)


def test_serve_warns_on_non_loopback(arena_env, monkeypatch):
    served = []
    monkeypatch.setattr(daemon, "is_up", lambda port: False)
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    result = invoke("serve", "--host", "0.0.0.0", "--port", "12000")
    assert "reachable from your network" in flat(result)
    assert served == [("0.0.0.0", 12000)]


def test_serve_loopback_is_quiet(arena_env, monkeypatch):
    served = []
    monkeypatch.setattr(daemon, "is_up", lambda port: False)
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    result = invoke("serve")
    assert "reachable from your network" not in flat(result)
    assert served == [("127.0.0.1", 11500)]  # the resolved HB_ARENA_PORT default


def test_serve_help_documents_hb_arena_port(arena_env):
    out = invoke("serve", "--help").output
    assert "HB_ARENA_PORT" in out and "11500" in out


def test_serve_refuses_when_a_gateway_is_already_running(arena_env, monkeypatch):
    monkeypatch.setattr(daemon, "is_up", lambda port: True)
    served = []
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    result = invoke("serve", "--port", "11500")
    assert result.exit_code == 1
    out = flat(result)
    assert "already running on port 11500" in out
    assert "hb arena stop --all" in out
    assert served == []


def test_rm_removes_a_corrupt_cached_manifest(docker_ok, arena_env):
    bad = arena_env / "agents" / "echo" / "0.1.0"
    bad.mkdir(parents=True)
    (bad / "arena.yaml").write_text("not: [valid")
    result = invoke("rm", "echo")
    assert result.exit_code == 0, result.output
    assert not (arena_env / "agents" / "echo").exists()


def test_malformed_hb_arena_port_fails_cleanly_everywhere(docker_ok, monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "nope")
    served = []
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    for args in (("serve",), ("endpoint", "echo"), ("reset", "echo")):
        docker_ok["running"] = [RUNNING]
        result = invoke(*args)
        assert result.exit_code == 1, (args, result.output)
        assert "HB_ARENA_PORT" in flat(result)
    assert served == []
    # stop never fails on it: nothing could have been started on a malformed port
    result = invoke("stop", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok["gateway"] == []
