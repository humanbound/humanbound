# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the `hb arena` command group. Docker, the gateway and processes are faked."""

from __future__ import annotations

import json
import re

import pytest
import yaml
from click.testing import CliRunner

from humanbound_cli.arena import catalog, keys, paths, runtime, target
from humanbound_cli.arena.runtime import DockerError
from humanbound_cli.main import cli

from .arena_testing import CATALOG, DIGEST, ECHO_YAML, SHA
from .test_arena_baseline import good

_REAL_START = runtime.start


def flat_text(text: str) -> str:
    """Text with all whitespace runs collapsed (Rich wraps long lines)."""
    return re.sub(r"\s+", " ", text)


def flat(result) -> str:
    """The output with all whitespace runs collapsed (Rich wraps long lines)."""
    return flat_text(result.output)


def _no_process(*args, **kwargs):
    raise AssertionError("unit tests must not run docker")


@pytest.fixture
def events(monkeypatch):
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, props=None: captured.append((event, props)),
    )
    return captured


@pytest.fixture
def arena_env(arena_home, monkeypatch, events):
    # The fixture catalog stands in for the default one: its agents are trusted.
    monkeypatch.setattr(paths, "DEFAULT_INDEX_URL", str(CATALOG / "index.json"))
    monkeypatch.setenv("HB_ARENA_INDEX", str(CATALOG))
    monkeypatch.setattr(runtime, "_run", _no_process)
    monkeypatch.setattr(runtime, "preflight", lambda m=None: None)
    monkeypatch.setattr(runtime, "docker_cli", lambda: "/usr/bin/docker")
    monkeypatch.delenv("HB_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(runtime, "list_running", lambda include_stopped=False: [])
    monkeypatch.setattr(runtime, "legacy_agents", lambda: [])
    monkeypatch.setattr(runtime, "pull_door_image", lambda: None)
    return arena_home


def run(*args, **kwargs):
    return CliRunner().invoke(cli, ["arena", *args], catch_exceptions=False, **kwargs)


# ── config ──


def test_config_round_trip_masks_values(arena_env):
    result = run("config", "set", "OPENAI_API_KEY=sk-1234567890abcdef", "ECHO_PREFIX=hi")
    assert result.exit_code == 0, result.output
    assert "✓ OPENAI_API_KEY saved" in result.output
    assert "sk-1234567890abcdef" not in result.output
    assert keys.read_config()["OPENAI_API_KEY"] == "sk-1234567890abcdef"

    result = run("config", "get")
    assert result.exit_code == 0
    assert "sk-…cdef" in result.output
    assert "ECHO_PREFIX" in result.output and "****" in result.output
    assert "sk-1234567890abcdef" not in result.output

    result = run("config", "get", "OPENAI_API_KEY")
    assert "sk-…cdef" in result.output

    assert run("config", "unset", "OPENAI_API_KEY").exit_code == 0
    assert "OPENAI_API_KEY" not in keys.read_config()
    run("config", "unset", "ECHO_PREFIX")
    assert "No arena keys stored." in run("config", "get").output


def test_config_malformed_pair_does_not_echo_value(arena_env):
    result = run("config", "set", "sk-supersecretvalue")
    assert result.exit_code == 1
    assert "expected KEY=VALUE" in result.output
    assert "supersecretvalue" not in result.output

    result = run("config", "set", "OPENAI_API_KEY")
    assert result.exit_code == 1
    assert "expected KEY=VALUE, got 'OPENAI_API_KEY=…'" in flat(result)


@pytest.mark.parametrize(
    "pair, message",
    [
        ("HB_TOKEN=x", "reserved"),
        ("humanbound_api=x", "reserved"),
        ("KEY='quoted'", "quotes"),
        ('KEY="quoted"', "quotes"),
        ("KEY= padded", "whitespace"),
        ("KEY=padded ", "whitespace"),
    ],
)
def test_config_rejects_bad_values(arena_env, pair, message):
    result = run("config", "set", pair)
    assert result.exit_code == 1
    assert message in result.output
    assert keys.read_config() == {}


def test_config_reserved_refused_before_anything_is_saved(arena_env):
    result = run("config", "set", "GOOD=1", "HB_API_KEY=x")
    assert result.exit_code == 1
    assert keys.read_config() == {}


def test_config_unreadable_env_file(arena_env):
    arena_env.mkdir(parents=True, exist_ok=True)
    (arena_env / "arena.env").write_bytes(b"\xff\xfe\x00bad")
    for args in (("get",), ("set", "A=b"), ("unset", "A")):
        result = run("config", *args)
        assert result.exit_code == 1
        assert "cannot read" in result.output


# ── validate ──


def test_validate_ok(arena_env):
    result = run("validate", str(ECHO_YAML))
    assert result.exit_code == 0
    assert "✓ echo 0.1.0 is a valid arena.yaml" in result.output
    assert "WARNING" not in result.output


def test_validate_bad(arena_env, tmp_path):
    data = yaml.safe_load(ECHO_YAML.read_text())
    del data["difficulty"]
    path = tmp_path / "arena.yaml"
    path.write_text(yaml.safe_dump(data))
    result = run("validate", str(path))
    assert result.exit_code == 1
    assert "invalid arena.yaml" in result.output
    assert "difficulty" in result.output


def _compose_manifest(tmp_path, compose_name="stack.yml"):
    """An echo compose manifest in `tmp_path/echo/` (the folder is named after the id)."""
    data = yaml.safe_load(ECHO_YAML.read_text())
    data["source"] = {"compose": compose_name, "service": "agent"}
    folder = tmp_path / "echo"
    folder.mkdir(exist_ok=True)
    path = folder / "arena.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_validate_folder_must_match_id(arena_env, tmp_path):
    folder = tmp_path / "not-echo"
    folder.mkdir()
    path = folder / "arena.yaml"
    path.write_text(ECHO_YAML.read_text())
    result = run("validate", str(path))
    assert result.exit_code == 1
    out = flat(result)
    assert "not-echo" in out and "'echo'" in out
    assert "folder" in out


def test_validate_relative_path_in_matching_folder(arena_env, monkeypatch):
    monkeypatch.chdir(ECHO_YAML.parent)
    result = run("validate", "arena.yaml")
    assert result.exit_code == 0, result.output


def test_validate_checks_the_named_compose_file(arena_env, tmp_path):
    path = _compose_manifest(tmp_path)
    (path.parent / "stack.yml").write_text(
        yaml.safe_dump({"services": {"agent": {"image": "x:1"}}})
    )
    result = run("validate", str(path))
    assert result.exit_code == 0, result.output

    (path.parent / "stack.yml").write_text(
        yaml.safe_dump({"services": {"agent": {"image": "x:1", "build": "."}}})
    )
    result = run("validate", str(path))
    assert result.exit_code == 1
    assert "build" in result.output


def test_validate_allows_dotenv_next_to_manifest(arena_env, tmp_path):
    path = _compose_manifest(tmp_path)
    (path.parent / "stack.yml").write_text(
        yaml.safe_dump({"services": {"agent": {"image": "x:1"}}})
    )
    (path.parent / ".env").write_text("OPENAI_API_KEY=sk-local\n")
    result = run("validate", str(path))
    assert result.exit_code == 0, result.output


def test_validate_uses_public_compose_path_check(arena_env, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(catalog, "check_compose_path", lambda v: seen.append(v))
    path = _compose_manifest(tmp_path)
    (path.parent / "stack.yml").write_text(
        yaml.safe_dump({"services": {"agent": {"image": "x:1"}}})
    )
    result = run("validate", str(path))
    assert result.exit_code == 0, result.output
    assert seen == ["stack.yml"]


def test_validate_compose_missing_file(arena_env, tmp_path):
    result = run("validate", str(_compose_manifest(tmp_path)))
    assert result.exit_code == 1
    assert "stack.yml" in flat(result)


def test_validate_compose_path_outside_folder(arena_env, tmp_path):
    result = run("validate", str(_compose_manifest(tmp_path, "../x.yml")))
    assert result.exit_code == 1
    assert "relative path" in flat(result)


UPSTREAM = {"repo": "https://github.com/x/y", "ref": SHA, "license": "Apache-2.0"}


def _manifest_file(tmp_path, **changes):
    data = yaml.safe_load(ECHO_YAML.read_text())
    data.update(changes)
    folder = tmp_path / "echo"
    folder.mkdir(exist_ok=True)
    path = folder / "arena.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_validate_tag_only_images_have_no_warning(arena_env, tmp_path):
    path = _manifest_file(tmp_path, source={"image": "x/echo:1", "upstream": UPSTREAM})
    result = run("validate", str(path))
    assert result.exit_code == 0, result.output
    assert "WARNING" not in result.output and "digest" not in result.output


def test_validate_compose_tag_images_have_no_warning(arena_env, tmp_path):
    path = _manifest_file(tmp_path, source={"compose": "stack.yml", "service": "agent"})
    compose = {"services": {"agent": {"image": "x/agent:1"}, "db": {"image": "postgres:16"}}}
    (path.parent / "stack.yml").write_text(yaml.safe_dump(compose))
    result = run("validate", str(path))
    assert result.exit_code == 0, result.output
    assert "WARNING" not in result.output


# ── ls ──


def test_ls_shows_latest_version(arena_env):
    result = run("ls")
    assert result.exit_code == 0
    out = flat(result)
    for column in ("ID", "VERSION", "DIFFICULTY", "TAGS", "STATE"):
        assert column in out
    assert "0.1.0" in out and "0.0.9" not in out
    assert "installed" not in out.split("STATE", 1)[1]


def _install_echo():
    loaded = catalog.load_index()
    return catalog.fetch_manifest(catalog.resolve(loaded.index, "echo"), loaded.location)


def test_ls_state_installed_and_running(arena_env, monkeypatch):
    _install_echo()
    assert "installed" in run("ls").output
    assert "echo" in run("ls", "--installed").output

    agent = runtime.RunningAgent("echo", "0.1.0", "image", 40000)
    monkeypatch.setattr(runtime, "list_running", lambda: [agent])
    assert "running" in run("ls").output


def test_ls_with_docker_down(arena_env, monkeypatch):
    def down():
        raise DockerError("Docker is installed but not running.")

    monkeypatch.setattr(runtime, "list_running", down)
    result = run("ls")
    assert result.exit_code == 0
    assert "echo" in result.output
    assert "not running" not in result.output


def test_ls_installed_empty(arena_env):
    result = run("ls", "--installed")
    assert result.exit_code == 0
    assert "No agents found." in result.output


def test_ls_unreachable_catalog(arena_env, monkeypatch, tmp_path):
    monkeypatch.setenv("HB_ARENA_INDEX", str(tmp_path / "nope" / "index.json"))
    result = run("ls")
    assert result.exit_code == 1
    assert "cannot load the arena catalog" in flat(result)


# ── info ──


def test_info(arena_env):
    result = run("info", "echo")
    assert result.exit_code == 0
    out = flat(result)
    assert "Echo" in out and "echo" in out and "0.1.0" in out
    assert "developer: Humanbound (https://humanbound.ai), contact: maintainers@example.org" in out
    assert "easy" in out and "origin" not in out
    assert "upstream" not in out and "images:" not in out  # none in the fixture
    assert "Echoes the prompt." in out
    assert "V1 [llm001]" in out  # printed literally, not as Rich markup
    assert "references: owasp-llm:LLM01, atlas:AML.T0051.000" in out
    assert "ECHO_PREFIX" in out
    assert "hb arena run echo" in out
    assert "hb test --target arena://echo" in out


def test_info_agent_yaml(arena_env):
    result = run("info", "echo", "--agent-yaml")
    assert result.exit_code == 0
    data = yaml.safe_load(result.output)
    assert data["scope"]["business"].startswith("Echo agent")
    assert data["capabilities"] == ["tools"]
    assert "Run it" not in result.output


def test_info_does_not_install(arena_env):
    assert run("info", "echo").exit_code == 0
    assert catalog.installed("echo") is None
    assert "No agents found." in run("ls", "--installed").output


def test_info_unknown_agent_suggests(arena_env):
    result = run("info", "ecko")
    assert result.exit_code == 1
    assert "Did you mean: echo" in flat(result)


def test_info_shows_upstream_and_the_index_digests(arena_env, monkeypatch, tmp_path):
    images = [{"ref": "humanbound-arena-echo:test", "digest": DIGEST}]
    root = _custom_catalog(
        tmp_path,
        images=images,
        manifest_changes={"source": {"image": "humanbound-arena-echo:test", "upstream": UPSTREAM}},
    )
    monkeypatch.setenv("HB_ARENA_INDEX", str(root))
    result = run("info", "echo")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert f"upstream: https://github.com/x/y @ {SHA} (Apache-2.0)" in out
    assert f"images: humanbound-arena-echo:test {DIGEST}" in out
    assert catalog.installed("echo") is None  # info still writes nothing


def test_info_tag_only_images_from_any_catalog(arena_env, monkeypatch, tmp_path):
    root = _custom_catalog(tmp_path, manifest_changes={"source": {"image": "x/echo:1"}})
    monkeypatch.setenv("HB_ARENA_INDEX", str(root))
    result = run("info", "echo")
    assert result.exit_code == 0, result.output
    assert "images:" not in result.output


def test_info_installed_agent_shows_the_recorded_digests(arena_env, monkeypatch, tmp_path):
    images = [{"ref": "humanbound-arena-echo:test", "digest": DIGEST}]
    monkeypatch.setenv("HB_ARENA_INDEX", str(_custom_catalog(tmp_path, images=images)))
    _install_echo()
    monkeypatch.setenv("HB_ARENA_INDEX", "/nonexistent/index.json")  # info uses the install
    result = run("info", "echo")
    assert result.exit_code == 0, result.output
    assert "0.1.0" in result.output
    assert f"humanbound-arena-echo:test {DIGEST}" in flat(result)


def test_pull_tag_only_image_from_a_custom_catalog(arena_env, monkeypatch, tmp_path, events):
    root = _custom_catalog(tmp_path, manifest_changes={"source": {"image": "x/echo:1"}})
    monkeypatch.setenv("HB_ARENA_INDEX", str(root))
    pulled = []
    monkeypatch.setattr(runtime, "pull", lambda m, d: pulled.append(m.source.image))
    result = run("pull", "echo")
    assert result.exit_code == 0, result.output
    assert pulled == ["x/echo:1"]
    assert events == [("arena_pull", {"agent": "custom"})]


# ── pull ──


def test_pull(arena_env, monkeypatch, events):
    pulled = []
    monkeypatch.setattr(runtime, "pull", lambda m, d: pulled.append((m.id, d)))
    result = run("pull", "echo")
    assert result.exit_code == 0, result.output
    assert "✓ echo 0.1.0 pulled" in result.output
    assert pulled and pulled[0][0] == "echo"
    assert catalog.installed("echo") is not None
    assert events == [("arena_pull", {"agent": "echo", "version": "0.1.0"})]


def test_pull_docker_error(arena_env, monkeypatch, events):
    def boom(m, d):
        raise DockerError("docker pull failed: [bold]nope[/bold]")

    monkeypatch.setattr(runtime, "pull", boom)
    result = run("pull", "echo")
    assert result.exit_code == 1
    assert "[bold]nope[/bold]" in result.output  # no markup interpretation
    assert events == []


def test_pull_preflight_failure(arena_env, monkeypatch):
    def down(m=None):
        raise DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "preflight", down)
    result = run("pull", "echo")
    assert result.exit_code == 1
    assert "not running" in result.output


DOCKER_COMMANDS = [
    ("pull", "echo"),
    ("run", "echo"),
    ("ps",),
    ("logs", "echo"),
    ("reset", "echo"),
    ("rm", "echo"),
    ("endpoint", "echo"),
    ("serve",),
    ("stop", "--all"),
]


@pytest.mark.parametrize("args", DOCKER_COMMANDS)
def test_inside_the_hb_docker_image_fails_fast(arena_env, monkeypatch, args):
    monkeypatch.setenv("HB_DOCKER_IMAGE", "1")
    monkeypatch.setattr(runtime, "list_running", _no_process)
    result = run(*args)
    assert result.exit_code == 1
    out = flat(result)
    assert "can't run inside the hb Docker image" in out
    assert "pip install humanbound" in out


@pytest.mark.parametrize("args", [("ls",), ("info", "echo"), ("config", "get")])
def test_inside_the_hb_docker_image_catalog_commands_work(arena_env, monkeypatch, args):
    monkeypatch.setenv("HB_DOCKER_IMAGE", "1")
    assert run(*args).exit_code == 0


@pytest.mark.parametrize("args", [a for a in DOCKER_COMMANDS if a[0] != "stop"])
def test_without_docker_on_path_fails_fast(arena_env, monkeypatch, args):
    monkeypatch.setattr(runtime, "docker_cli", lambda: None)
    monkeypatch.setattr(runtime, "list_running", _no_process)
    result = run(*args)
    assert result.exit_code == 1
    assert runtime.DOCKER_MISSING in flat(result)


def test_pull_unknown_agent(arena_env):
    result = run("pull", "ecko")
    assert result.exit_code == 1
    assert "Did you mean: echo" in flat(result)


def test_pull_refetches_corrupt_cache(arena_env, monkeypatch):
    monkeypatch.setattr(runtime, "pull", lambda m, d: None)
    _, path = _install_echo()
    (path / "arena.yaml").write_text("id: [broken")
    result = run("pull", "echo")
    assert result.exit_code == 0, result.output
    assert catalog.installed("echo")[0].id == "echo"


# ── run / ps / logs / stop / reset / rm / endpoint / serve ──

GATEWAY = "http://127.0.0.1:11500"


class FakeDocker:
    def __init__(self):
        self.running: list[runtime.RunningAgent] = []
        self.exited: list[runtime.RunningAgent] = []  # containers that stopped on their own
        self.started: list[tuple[str, dict]] = []
        self.door_pulls = 0
        self.door_sweeps: list[bool] = []  # any_owner of each remove_doors
        self.gateway_reachable = False
        self.refused: list[str] = []  # what the door's log says it refused
        self.door_logged: list[tuple[str, bool, int]] = []
        self.stopped: list[str] = []
        self.stop_dirs: list[tuple[str, object]] = []  # (id, agent_dir) of each stop
        self.pulled: list[str] = []
        self.removed_images: list[str] = []
        self.gateway_stops = 0
        self.gateway_up = True
        self.gateway_was_up = False  # what daemon.is_up reports before `run` ensures it
        self.forgotten: list[tuple[str, str]] = []
        self.image = True

    def start(self, m, agent_dir, env):
        self.started.append((m.id, dict(env)))
        agent = runtime.RunningAgent(
            m.id, m.version, runtime.kind_of(m), 40123, gateway_reachable=self.gateway_reachable
        )
        self.running.append(agent)
        return agent

    def pull_door_image(self):
        self.door_pulls += 1

    def door_logs(self, agent_id, *, follow=False, tail=200):
        self.door_logged.append((agent_id, follow, tail))

    def remove_doors(self, *, any_owner=False):
        self.door_sweeps.append(any_owner)

    def stop(self, agent_id, kind, owner=None, name=None, *, agent_dir=None):
        self.stopped.append(agent_id)
        self.stop_dirs.append((agent_id, agent_dir))
        self.running = [a for a in self.running if a.id != agent_id]
        self.exited = [a for a in self.exited if a.id != agent_id]

    def list_running(self, include_stopped=False, any_owner=False):
        return list(self.running) + (list(self.exited) if include_stopped else [])

    def find_running(self, agent_id, include_stopped=False):
        agents = self.list_running(include_stopped=include_stopped)
        return next((a for a in agents if a.id == agent_id), None)

    def stop_gateway(self, port=None, **kwargs):
        self.gateway_stops += 1
        was_up, self.gateway_up = self.gateway_up, False
        return was_up


@pytest.fixture
def docker_ok(arena_env, monkeypatch):
    from humanbound_cli.arena import daemon

    fake = FakeDocker()
    monkeypatch.setattr(runtime, "image_present", lambda image: fake.image)
    monkeypatch.setattr(runtime, "pull", lambda m, d: fake.pulled.append(m.id))
    monkeypatch.setattr(runtime, "start", fake.start)
    monkeypatch.setattr(runtime, "pull_door_image", fake.pull_door_image)
    monkeypatch.setattr(runtime, "refused_destinations", lambda agent_id: list(fake.refused))
    monkeypatch.setattr(runtime, "door_logs", fake.door_logs)
    monkeypatch.setattr(runtime, "remove_doors", fake.remove_doors)
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    monkeypatch.setattr(runtime, "list_running", fake.list_running)
    monkeypatch.setattr(runtime, "find_running", fake.find_running)
    monkeypatch.setattr(runtime, "stop", fake.stop)
    monkeypatch.setattr(runtime, "remove_images", lambda m, d: fake.removed_images.append(m.id))
    monkeypatch.setattr(daemon, "ensure_running", lambda port=None, **kw: GATEWAY)
    monkeypatch.setattr(daemon, "stop_gateway", fake.stop_gateway)
    monkeypatch.setattr(daemon, "is_up", lambda port=None, **kw: fake.gateway_was_up)
    monkeypatch.setattr(target, "forget_via_gateway", lambda i, g: fake.forgotten.append((i, g)))
    return fake


def _running(fake, agent_id="echo", version="0.1.0"):
    agent = runtime.RunningAgent(agent_id, version, "image", 40123)
    fake.running.append(agent)
    return agent


def test_run_happy_path(docker_ok, monkeypatch):
    keys.set_value("ECHO_PREFIX", "stored-secret-value")
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert "Passing keys: ECHO_PREFIX" in out
    assert "stored-secret-value" not in out
    assert "✓ echo 0.1.0 is running" in out
    assert f"{GATEWAY}/a2a/echo/.well-known/agent-card.json" in out
    assert f"{GATEWAY}/a2a/echo" in out
    assert f"{GATEWAY}/v1 (model: arena/echo)" in out
    assert "Test it: hb test --target arena://echo" in out
    assert "not from the default" not in out  # the default catalog needs no confirmation
    assert docker_ok.started == [("echo", {"ECHO_PREFIX": "stored-secret-value"})]
    assert docker_ok.pulled == []


def test_run_fresh_gateway_does_not_forget(docker_ok):
    assert run("run", "echo").exit_code == 0
    assert docker_ok.forgotten == []


def test_run_with_gateway_up_forgets_old_conversations(docker_ok):
    docker_ok.gateway_was_up = True
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok.forgotten == [("echo", GATEWAY)]


def test_run_forget_failure_is_ignored(docker_ok, monkeypatch):
    docker_ok.gateway_was_up = True

    def boom(agent_id, gateway):
        raise target.TargetError("gateway went away")

    monkeypatch.setattr(target, "forget_via_gateway", boom)
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert "is running" in result.output


def test_run_no_keys_and_pulls_missing_image(docker_ok):
    docker_ok.image = False
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert "Passing no keys" in result.output
    assert docker_ok.pulled == ["echo"]


def _install_variant(arena_home, *, index=None, images=(), **changes):
    """Install a modified echo manifest straight into the cache (as if pulled from `index`,
    default: the fixture catalog, which the tests treat as the default catalog)."""
    data = yaml.safe_load(ECHO_YAML.read_text())
    for key, value in changes.items():
        data[key] = value
    folder = arena_home / "agents" / "echo" / data["version"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "arena.yaml").write_text(yaml.safe_dump(data))
    provenance = {"index": index or str(CATALOG / "index.json"), "images": list(images)}
    (folder / catalog.PROVENANCE_FILE).write_text(json.dumps(provenance))
    return folder


def test_run_missing_keys(docker_ok, arena_env):
    _install_variant(arena_env, runtime={"port": 8080, "env": {"required": ["OPENAI_API_KEY"]}})
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "hb arena config set OPENAI_API_KEY=..." in out
    assert "not from the default" not in out
    assert docker_ok.started == []


def test_run_missing_keys_untrusted_hint(docker_ok, arena_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    _install_variant(
        arena_env,
        index=CUSTOM_INDEX,
        runtime={"port": 8080, "env": {"required": ["OPENAI_API_KEY"]}},
    )
    result = run("run", "echo", "--yes")
    assert result.exit_code == 1
    out = flat(result)
    assert "hb arena config set OPENAI_API_KEY=..." in out
    assert "not from the default Humanbound catalog, so its keys are not read from" in out
    assert docker_ok.started == []


def test_run_health_timeout(docker_ok, monkeypatch):
    def timeout(agent, health):
        raise runtime.HealthTimeout("echo did not become healthy within 30s")

    monkeypatch.setattr(runtime, "wait_healthy", timeout)
    tails = []

    def last_logs(i, k, n=50, *, agent_dir=None):
        tails.append(agent_dir)
        return "boom [red]trace[/red]\n"

    monkeypatch.setattr(runtime, "last_logs", last_logs)
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "boom [red]trace[/red]" in out
    assert "echo did not become healthy within 30s (see the agent's logs above)" in out
    assert "hb arena logs" not in out
    assert docker_ok.stopped == ["echo"]
    # the agent's own files: compose never looks in the current directory
    agent_dir = catalog.installed("echo")[1]
    assert tails == [agent_dir]
    assert docker_ok.stop_dirs == [("echo", agent_dir)]


def test_run_docker_error(docker_ok, monkeypatch):
    def boom(m, d, env):
        raise DockerError("docker run failed: port taken")

    monkeypatch.setattr(runtime, "start", boom)
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "docker run failed: port taken" in flat(result)


def test_run_gateway_failure_stops_agent(docker_ok, monkeypatch):
    from humanbound_cli.arena import daemon

    def fail(port=None, **kw):
        raise daemon.GatewayError("port 11500 is used by another program")

    monkeypatch.setattr(daemon, "ensure_running", fail)
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "port 11500 is used by another program (the agent was stopped)" in flat(result)
    assert docker_ok.stopped == ["echo"]


def test_run_bad_port_fails_before_start(docker_ok, monkeypatch):
    monkeypatch.setenv("HB_ARENA_PORT", "abc")
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "HB_ARENA_PORT" in result.output
    assert docker_ok.started == []
    assert catalog.installed("echo") is None


@pytest.mark.parametrize("raw", ["0", "70000"])
def test_run_out_of_range_port_fails_cleanly(docker_ok, monkeypatch, raw):
    monkeypatch.setenv("HB_ARENA_PORT", raw)
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "between 1 and 65535" in flat(result)
    assert docker_ok.started == []


def test_run_key_with_newline_fails_cleanly(docker_ok, monkeypatch, tmp_path):
    env_file = tmp_path / "keys.env"
    env_file.write_bytes(b"ECHO_PREFIX=line1\x00line2\n")
    result = run("run", "echo", "--env-file", str(env_file))
    assert result.exit_code == 1
    out = flat(result)
    assert "cannot use key ECHO_PREFIX" in out
    assert "line1" not in out
    assert docker_ok.started == []


@pytest.mark.parametrize(
    "exc", [OSError("[Errno 28] No space left on device"), ValueError("bad value for X")]
)
def test_run_start_os_or_value_error_fails_cleanly(docker_ok, monkeypatch, exc):
    def boom(m, d, env):
        raise exc

    monkeypatch.setattr(runtime, "start", boom)
    result = run("run", "echo")
    assert result.exit_code == 1
    assert str(exc) in flat(result)


def test_run_env_file_reaches_start(docker_ok, tmp_path):
    env_file = tmp_path / "keys.env"
    env_file.write_text("ECHO_PREFIX=from-file\nOTHER=ignored\n")
    result = run("run", "echo", "--env-file", str(env_file))
    assert result.exit_code == 0, result.output
    assert docker_ok.started == [("echo", {"ECHO_PREFIX": "from-file"})]
    assert "from-file" not in result.output


def test_run_binary_env_file(docker_ok, tmp_path):
    env_file = tmp_path / "keys.env"
    env_file.write_bytes(b"\xff\xfe\x00\x01")
    result = run("run", "echo", "--env-file", str(env_file))
    assert result.exit_code == 1
    out = flat(result)
    assert "cannot read" in out and "keys.env:" in out  # Rich may wrap the long temp path
    assert docker_ok.started == []


def test_run_refused_by_the_container_baseline(docker_ok, monkeypatch, events):
    from humanbound_cli.arena.baseline import BaselineError, Violation

    long_name = "arena-0123456789ab-echo-with-a-rather-long-service-name-1"
    violations = [
        Violation(long_name, "non-root", "runs as root (Config.User is empty, so root applies)"),
        Violation(long_name, "loopback-ports", "publishes 8080/tcp on 0.0.0.0, not only there"),
    ]

    def refuse(m, agent_dir, env):
        raise BaselineError(m.id, violations)

    monkeypatch.setattr(runtime, "start", refuse)
    result = run("run", "echo")
    assert result.exit_code == 1
    for v in violations:
        assert str(v) in result.output.splitlines()  # one per line, never wrapped
    assert "is running" not in result.output
    assert events == []  # no arena_run event for a refused agent


def test_run_shows_the_notice_every_time(docker_ok):
    from humanbound_cli.commands.arena import NOTICE

    assert 1 <= len(NOTICE.splitlines()) <= 3
    for _ in range(2):
        result = run("run", "echo")
        assert result.exit_code == 0, result.output
        out = flat(result)
        assert "intentionally vulnerable" in out
        assert "best effort" in out
        assert "at your own risk" in out
        assert "sensitive data" in out and "critical systems" in out
        assert "127.0.0.1" in out
    lowered = NOTICE.lower()
    assert "safe" not in lowered and "secure" not in lowered


# ── check ──


def _containers(monkeypatch, *containers):
    listed = []

    def agent_containers(agent_id):
        listed.append(agent_id)
        return [dict(c) for c in containers]

    monkeypatch.setattr(runtime, "agent_containers", agent_containers)
    monkeypatch.setattr(runtime, "agent_networks", _networks_without_a_route_out)
    return listed


def _networks_without_a_route_out(containers, internal=True):
    names = {n for c in containers for n in c["NetworkSettings"]["Networks"]}
    return [{"Name": n, "Internal": internal} for n in sorted(names)]


def test_check_passes(docker_ok, monkeypatch):
    _running(docker_ok)
    listed = _containers(monkeypatch, good("arena-x-echo"))
    result = run("check", "echo")
    assert result.exit_code == 0, result.output
    assert result.output == "✓ echo: 1 container meets the container baseline\n"
    assert listed == ["echo"]
    assert docker_ok.stopped == []


def test_check_passes_for_every_container_of_a_compose_agent(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(monkeypatch, good("arena-x-duo-agent-1"), good("arena-x-duo-backend-1"))
    result = run("check", "echo")
    assert result.exit_code == 0, result.output
    assert "✓ echo: 2 containers meet the container baseline" in result.output


def test_check_reports_one_problem_per_line_and_exits_1(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(
        monkeypatch,
        good("arena-x-duo-agent-1"),
        good(
            "arena-x-duo-backend-1",
            Config__User="root",
            HostConfig__Privileged=True,
            NetworkSettings__Ports={"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5000"}]},
        ),
    )
    result = run("check", "echo")
    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert lines == [
        "arena-x-duo-backend-1: non-root: runs as root (Config.User is 'root')",
        "arena-x-duo-backend-1: not-privileged: runs privileged (HostConfig.Privileged is true)",
        "arena-x-duo-backend-1: loopback-ports: publishes 8080/tcp on 0.0.0.0, not only on "
        "127.0.0.1",
    ]
    assert "3 problems" in result.stderr
    assert docker_ok.stopped == []  # check never stops anything


def test_check_json(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(monkeypatch, good("arena-x-echo"))
    result = run("check", "echo", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "agent": "echo",
        "containers": ["arena-x-echo"],
        "violations": [],
    }


def test_check_json_with_violations(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(monkeypatch, good("arena-x-echo", HostConfig__CapAdd=["NET_ADMIN"]))
    result = run("check", "echo", "--json")
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["agent"] == "echo"
    assert data["containers"] == ["arena-x-echo"]
    assert data["violations"] == [
        {
            "container": "arena-x-echo",
            "rule": "capabilities",
            "message": "adds capabilities (NET_ADMIN)",
        }
    ]
    assert docker_ok.stopped == []


@pytest.mark.parametrize("as_json", [False, True])
def test_check_not_running_exits_2(docker_ok, monkeypatch, as_json):
    monkeypatch.setattr(runtime, "agent_containers", _no_process)
    result = run("check", "echo", *(["--json"] if as_json else []))
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "echo is not running, and it is not installed" in flat_text(result.stderr)


def test_check_docker_down_exits_2(docker_ok, monkeypatch):
    def down(m=None):
        raise DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "preflight", down)
    result = run("check", "echo")
    assert result.exit_code == 2
    assert runtime.DOCKER_DOWN in result.stderr


def test_check_docker_failing_while_inspecting_exits_2(docker_ok, monkeypatch):
    _running(docker_ok)

    def broken(agent_id):
        raise DockerError("docker inspect failed: boom")

    monkeypatch.setattr(runtime, "agent_containers", broken)
    result = run("check", "echo")
    assert result.exit_code == 2
    assert "docker inspect failed: boom" in result.stderr
    assert docker_ok.stopped == []


def test_check_without_docker_exits_2(arena_env, monkeypatch):
    monkeypatch.setattr(runtime, "docker_cli", lambda: None)
    result = run("check", "echo")
    assert result.exit_code == 2
    assert runtime.DOCKER_MISSING in flat(result)


def test_check_inside_the_hb_docker_image_exits_2(arena_env, monkeypatch):
    monkeypatch.setenv("HB_DOCKER_IMAGE", "1")
    result = run("check", "echo")
    assert result.exit_code == 2
    assert "can't run inside the hb Docker image" in flat(result)


def test_check_invalid_id_exits_2(docker_ok):
    result = run("check", "Not An Id")
    assert result.exit_code == 2
    assert "is not a valid agent id" in flat_text(result.stderr)


@pytest.mark.parametrize("as_json", [False, True])
def test_check_with_no_containers_is_a_violation(docker_ok, monkeypatch, as_json):
    _running(docker_ok)
    _containers(monkeypatch)
    result = run("check", "echo", *(["--json"] if as_json else []))
    assert result.exit_code == 1
    if as_json:
        assert json.loads(result.stdout) == {
            "agent": "echo",
            "containers": [],
            "violations": [
                {
                    "container": "(agent)",
                    "rule": "inspect-data",
                    "message": "no containers to check",
                }
            ],
        }
    else:
        assert result.stdout.splitlines() == ["(agent): inspect-data: no containers to check"]
    assert docker_ok.stopped == []


def test_check_help_says_what_it_covers_and_the_notice(arena_env):
    result = run("check", "--help")
    assert result.exit_code == 0
    out = flat(result)
    assert "be only on networks that have no route out" in out
    assert "It checks configuration only" in out
    assert "not what it sends to the destinations it may reach" in out
    assert "intentionally vulnerable" in out
    assert "at your own risk" in out
    for code in ("0", "1", "2"):
        assert code in out
    lowered = out.lower()
    assert "safe" not in lowered and "secure" not in lowered


def test_run_telemetry(docker_ok, events):
    assert run("run", "echo").exit_code == 0
    assert events == [("arena_run", {"agent": "echo", "version": "0.1.0"})]


def test_ps(docker_ok):
    assert "No arena agents running." in run("ps").output
    _running(docker_ok)
    result = run("ps")
    out = flat(result)
    for column in ("ID", "VERSION", "A2A", "NATIVE"):
        assert column in out
    assert "echo" in out and "0.1.0" in out
    assert "http://127.0.0.1:40123" in out


def test_ps_docker_error(docker_ok, monkeypatch):
    def down():
        raise DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "list_running", down)
    result = run("ps")
    assert result.exit_code == 1
    assert "not running" in result.output


def test_endpoint(docker_ok):
    assert "echo is not running, and it is not installed" in flat(run("endpoint", "echo"))
    _running(docker_ok)
    result = run("endpoint", "echo")
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"{GATEWAY}/a2a/echo/.well-known/agent-card.json" in out
    assert "curl" in out and "A2A-Version: 1.0" in out
    assert "Content-Type: application/json" in out and "SendMessage" in out
    config = json.loads(out[out.index("{\n") :])
    assert config["chat_completion"]["endpoint"] == f"{GATEWAY}/a2a/echo"
    # the owner's token: printed, in the curl example and in the bot config
    token = paths.gateway_token(create=False)
    assert token
    assert f"Access token:     {token}" in out
    assert f"-H 'Authorization: Bearer {token}'" in out
    assert config["chat_completion"]["headers"]["Authorization"] == f"Bearer {token}"
    assert f"OPENAI_API_KEY={token}" in out


def test_stop_needs_id_or_all(docker_ok):
    result = run("stop")
    assert result.exit_code == 1
    assert "give an agent id or --all" in result.output


def test_stop_all(docker_ok):
    _running(docker_ok)
    _running(docker_ok, "other")
    result = run("stop", "--all")
    assert result.exit_code == 0
    assert "✓ echo stopped" in result.output and "✓ other stopped" in result.output
    assert "gateway stopped" in result.output
    assert docker_ok.running == []


def test_stop_all_nothing_running(docker_ok):
    docker_ok.gateway_up = False
    result = run("stop", "--all")
    assert result.exit_code == 0
    assert "No arena agents running." in result.output
    assert docker_ok.gateway_stops == 1


def test_stop_one_keeps_gateway_while_another_runs(docker_ok):
    _running(docker_ok)
    _running(docker_ok, "other")
    result = run("stop", "echo")
    assert result.exit_code == 0
    assert "✓ echo stopped" in result.output
    assert docker_ok.gateway_stops == 0
    assert "gateway stopped" not in result.output

    result = run("stop", "other")
    assert "gateway stopped" in result.output


def test_stop_cleans_up_an_exited_agent(docker_ok):
    # A crashed or `docker stop`ped container still has a network and a keys file to remove.
    docker_ok.exited.append(runtime.RunningAgent("echo", "0.1.0", "image", None))
    assert "No arena agents running." in run("ps").output
    result = run("stop", "echo")
    assert result.exit_code == 0, result.output
    assert "✓ echo stopped" in result.output
    assert docker_ok.stopped == ["echo"]


def test_stop_all_cleans_up_exited_agents(docker_ok):
    _running(docker_ok)
    docker_ok.exited.append(runtime.RunningAgent("other", "0.1.0", "compose", None))
    result = run("stop", "--all")
    assert result.exit_code == 0, result.output
    assert sorted(docker_ok.stopped) == ["echo", "other"]
    assert "gateway stopped" in result.output


def test_stop_not_running(docker_ok):
    result = run("stop", "echo")
    assert result.exit_code == 1
    assert "echo is not running" in result.output


def test_stop_all_docker_down_still_stops_gateway(docker_ok, monkeypatch):
    def down(include_stopped=False, any_owner=False):
        raise DockerError(runtime.DOCKER_DOWN)

    monkeypatch.setattr(runtime, "list_running", down)
    result = run("stop", "--all")
    assert result.exit_code == 1
    assert "not running" in result.output
    assert docker_ok.gateway_stops == 1


def test_logs(docker_ok, monkeypatch):
    calls = []
    monkeypatch.setattr(
        runtime,
        "logs",
        lambda i, k, *, follow, tail, agent_dir=None: calls.append((i, k, follow, tail, agent_dir)),
    )
    assert run("logs", "echo").exit_code == 1
    _running(docker_ok)
    result = run("logs", "echo", "-f", "--tail", "5")
    assert result.exit_code == 0
    assert calls == [("echo", "image", True, 5, None)]


def _compose_running(docker_ok, monkeypatch, tmp_path, found=True):
    """A running compose agent `stack` whose install (if `found`) is in tmp_path."""
    from humanbound_cli.arena.manifest import ManifestError

    agent = runtime.RunningAgent("stack", "1.0.0", "compose", 40123)
    docker_ok.running.append(agent)
    lookups = []

    def installed(agent_id, version=None):
        lookups.append((agent_id, version))
        if found is None:
            raise ManifestError("corrupt")
        return (object(), tmp_path) if found else None

    monkeypatch.setattr(catalog, "installed", installed)
    return lookups


@pytest.mark.parametrize("found, expected", [(True, "dir"), (False, None), (None, None)])
def test_stop_compose_agent_uses_its_installed_files(
    docker_ok, monkeypatch, tmp_path, found, expected
):
    lookups = _compose_running(docker_ok, monkeypatch, tmp_path, found)
    result = run("stop", "stack")
    assert result.exit_code == 0, result.output
    assert lookups == [("stack", "1.0.0")]
    assert docker_ok.stop_dirs == [("stack", tmp_path if expected else None)]


def test_stop_all_passes_each_compose_agents_files(docker_ok, monkeypatch, tmp_path):
    _compose_running(docker_ok, monkeypatch, tmp_path)
    _running(docker_ok)
    assert run("stop", "--all").exit_code == 0
    assert sorted(docker_ok.stop_dirs, key=lambda x: x[0]) == [
        ("echo", None),
        ("stack", tmp_path),
    ]


def test_stop_all_any_owner_never_uses_our_files_for_others(docker_ok, monkeypatch, tmp_path):
    _compose_running(docker_ok, monkeypatch, tmp_path)
    docker_ok.running[0] = runtime.RunningAgent(
        "stack", "1.0.0", "compose", 40123, owner="ffffffffffff", name="arena-ffffffffffff-stack"
    )
    assert run("stop", "--all", "--any-owner").exit_code == 0
    assert docker_ok.stop_dirs == [("stack", None)]


def test_logs_compose_agent_uses_its_installed_files(docker_ok, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        runtime,
        "logs",
        lambda i, k, *, follow, tail, agent_dir=None: calls.append((i, agent_dir)),
    )
    _compose_running(docker_ok, monkeypatch, tmp_path)
    assert run("logs", "stack").exit_code == 0
    assert calls == [("stack", tmp_path)]


def test_logs_docker_error(docker_ok, monkeypatch):
    def boom(*a, **kw):
        raise DockerError("docker logs failed: gone")

    monkeypatch.setattr(runtime, "logs", boom)
    _running(docker_ok)
    result = run("logs", "echo")
    assert result.exit_code == 1
    assert "docker logs failed: gone" in result.output


def test_reset(docker_ok, monkeypatch):
    from humanbound_cli.arena import target

    calls = []
    monkeypatch.setattr(target, "reset_via_gateway", lambda i, g: calls.append((i, g)))
    assert run("reset", "echo").exit_code == 1
    _running(docker_ok)
    result = run("reset", "echo")
    assert result.exit_code == 0
    assert "✓ echo reset" in result.output
    assert calls == [("echo", GATEWAY)]


def test_reset_failure(docker_ok, monkeypatch):
    from humanbound_cli.arena import target

    def fail(i, g):
        raise target.TargetError("could not reset echo: [boom]")

    monkeypatch.setattr(target, "reset_via_gateway", fail)
    _running(docker_ok)
    result = run("reset", "echo")
    assert result.exit_code == 1
    assert "could not reset echo: [boom]" in result.output


def test_rm(docker_ok):
    _install_echo()
    _running(docker_ok)
    result = run("rm", "echo")
    assert result.exit_code == 0, result.output
    assert "✓ echo removed" in result.output
    assert docker_ok.stopped == ["echo"]
    assert docker_ok.removed_images == ["echo"]
    assert catalog.installed("echo") is None
    assert "gateway stopped" in result.output


def test_rm_stops_an_exited_agent_before_removing_images(docker_ok):
    _install_echo()
    docker_ok.exited.append(runtime.RunningAgent("echo", "0.1.0", "image", None))
    result = run("rm", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok.stopped == ["echo"]
    assert docker_ok.removed_images == ["echo"]


def test_rm_unknown(docker_ok):
    result = run("rm", "echo")
    assert result.exit_code == 1
    assert "echo is not installed" in result.output


def test_rm_invalid_id(docker_ok, arena_env):
    (arena_env / "agents").mkdir(parents=True)
    result = run("rm", "../agents")
    assert result.exit_code == 1
    assert "is not installed" in result.output
    assert (arena_env / "agents").is_dir()


def test_rm_corrupt_cache(docker_ok):
    _, path = _install_echo()
    (path / "arena.yaml").write_text("id: [broken")
    _running(docker_ok)
    result = run("rm", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok.stopped == ["echo"]
    assert docker_ok.removed_images == []
    assert not path.exists()


def test_serve_warns_on_non_loopback(docker_ok, monkeypatch):
    from humanbound_cli.arena import daemon

    served = []
    monkeypatch.setattr(daemon, "is_up", lambda port=None, **kw: False)
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    result = run("serve", "--host", "0.0.0.0", "--port", "12000")
    assert result.exit_code == 0
    assert "intentionally vulnerable" in flat(result)
    assert "reachable from your network" in flat(result)
    assert "gateway.token" in flat(result)  # the token is still required
    assert served == [("0.0.0.0", 12000)]


@pytest.mark.parametrize("port", ["0", "65536", "-5"])
def test_serve_port_out_of_range_is_usage_error(docker_ok, monkeypatch, port):
    from humanbound_cli.arena import daemon

    monkeypatch.setattr(daemon, "serve", _no_process)
    result = run("serve", "--port", port)
    assert result.exit_code == 2
    assert "--port" in result.output


def test_serve_quiet_on_loopback(docker_ok, monkeypatch):
    from humanbound_cli.arena import daemon

    served = []
    monkeypatch.setattr(daemon, "is_up", lambda port=None, **kw: False)
    monkeypatch.setattr(daemon, "serve", lambda host, port: served.append((host, port)))
    result = run("serve")
    assert result.exit_code == 0
    assert "reachable from your network" not in flat(result)
    assert served == [("127.0.0.1", 11500)]


def test_serve_refuses_when_gateway_up(docker_ok, monkeypatch):
    from humanbound_cli.arena import daemon

    monkeypatch.setattr(daemon, "is_up", lambda port=None, **kw: True)
    monkeypatch.setattr(daemon, "serve", _no_process)
    result = run("serve")
    assert result.exit_code == 1
    assert "a gateway is already running on port 11500" in flat(result)


def test_serve_refuses_another_owners_gateway(docker_ok, monkeypatch):
    from humanbound_cli.arena import daemon

    monkeypatch.setattr(daemon, "is_up", lambda port=None, any_owner=False: any_owner)
    monkeypatch.setattr(daemon, "serve", _no_process)
    result = run("serve")
    assert result.exit_code == 1
    out = flat(result)
    assert "port 11500 is used by another user's or HOME's arena gateway" in out
    assert "HB_ARENA_PORT" in out


# ── trust: shell keys, confirmation, telemetry for custom catalogs ──


CUSTOM_INDEX = "/somewhere/else/index.json"


def _custom_catalog(tmp_path, *, images=None, manifest_changes=None):
    """A copy of the fixture catalog at another location (so: a custom catalog). `images`
    goes into every index entry; manifest_changes into echo's arena.yaml."""
    import shutil

    root = tmp_path / "custom"
    shutil.copytree(CATALOG, root)
    if images is not None:
        index = json.loads((root / "index.json").read_text())
        for entry in index["agents"]:
            entry["images"] = images
        (root / "index.json").write_text(json.dumps(index))
    if manifest_changes:
        path = root / "agents" / "echo" / "arena.yaml"
        data = yaml.safe_load(path.read_text())
        data.update(manifest_changes)
        path.write_text(yaml.safe_dump(data))
    return root


def _needs_openai(**extra):
    return {
        "runtime": {
            "port": 8080,
            "env": {"required": ["OPENAI_API_KEY"], "optional": ["ECHO_PREFIX"]},
        },
        **extra,
    }


def test_default_catalog_reads_only_llm_keys_from_the_shell(docker_ok, arena_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    monkeypatch.setenv("ECHO_PREFIX", "not-an-llm-key")
    _install_variant(arena_env, **_needs_openai())
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok.started == [("echo", {"OPENAI_API_KEY": "sk-from-the-shell"})]


def test_default_catalog_hint_for_non_llm_keys(docker_ok, arena_env, monkeypatch):
    monkeypatch.setenv("ECHO_PREFIX", "from-the-shell")
    _install_variant(arena_env, runtime={"port": 8080, "env": {"required": ["ECHO_PREFIX"]}})
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "hb arena config set ECHO_PREFIX=..." in out
    assert "only LLM keys" in out


def test_default_catalog_agent_with_upstream_is_trusted(docker_ok, arena_env, monkeypatch):
    # There is one kind of agent: packaging an upstream project changes nothing.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    _install_variant(
        arena_env, source={"image": "x/echo:1", "upstream": UPSTREAM}, **_needs_openai()
    )
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert docker_ok.started == [("echo", {"OPENAI_API_KEY": "sk-from-the-shell"})]


@pytest.mark.parametrize(
    "location",
    # a local index path: test_run_missing_keys_untrusted_hint
    ["custom-dir", "https://raw.githubusercontent.com/someone/fork/main/index.json"],
)
def test_other_catalogs_get_no_shell_keys(docker_ok, arena_env, monkeypatch, tmp_path, location):
    if location == "custom-dir":
        root = _custom_catalog(tmp_path, manifest_changes=_needs_openai())
        monkeypatch.setenv("HB_ARENA_INDEX", str(root))
    else:
        _install_variant(arena_env, index=location, **_needs_openai())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    result = run("run", "echo", "--yes")
    assert result.exit_code == 1
    assert "keys are not read from your shell" in flat(result)
    assert docker_ok.started == []


def test_other_catalogs_run_with_keys_from_arena_env(docker_ok, arena_env, monkeypatch):
    _install_variant(arena_env, index=CUSTOM_INDEX, **_needs_openai())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    keys.set_value("OPENAI_API_KEY", "sk-stored")
    result = run("run", "echo", "--yes")
    assert result.exit_code == 0, result.output
    assert docker_ok.started == [("echo", {"OPENAI_API_KEY": "sk-stored"})]


def test_install_without_provenance_is_fetched_again(docker_ok, arena_env, monkeypatch):
    folder = _install_variant(arena_env, name="Stale")
    (folder / catalog.PROVENANCE_FILE).unlink()
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert (folder / catalog.PROVENANCE_FILE).exists()
    assert catalog.installed("echo")[0].name == "Echo"


def test_install_without_provenance_offline_is_untrusted(docker_ok, arena_env, monkeypatch):
    folder = _install_variant(arena_env, **_needs_openai())
    (folder / catalog.PROVENANCE_FILE).unlink()
    monkeypatch.setenv("HB_ARENA_INDEX", "/nonexistent/index.json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    result = run("run", "echo", "--yes")
    assert result.exit_code == 1
    assert "keys are not read from your shell" in flat(result)


# confirmation


def _untrusted_install(arena_env, **extra):
    return _install_variant(
        arena_env,
        index=CUSTOM_INDEX,
        images=[{"ref": "humanbound-arena-echo:test", "digest": DIGEST}],
        developer={
            "name": "Someone Else",
            "url": "https://example.org/agents",
            "contact": "security@example.org",
        },
        source={"image": "humanbound-arena-echo:test", "upstream": UPSTREAM},
        **extra,
    )


@pytest.fixture
def interactive(monkeypatch):
    from humanbound_cli.commands import arena as arena_cmd

    monkeypatch.setattr(arena_cmd, "_interactive", lambda: True)


def test_untrusted_agent_needs_confirmation_non_interactive(docker_ok, arena_env):
    _untrusted_install(arena_env)
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "--yes" in out
    assert docker_ok.started == []


def test_untrusted_agent_confirmation_shows_details(docker_ok, arena_env, interactive):
    _untrusted_install(arena_env)
    keys.set_value("ECHO_PREFIX", "stored-value")
    result = run("run", "echo", input="y\n")
    assert result.exit_code == 0, result.output
    out = flat(result)
    for text in (
        f"is not from the default Humanbound catalog (it comes from {CUSTOM_INDEX})",
        "developer: Someone Else (https://example.org/agents)",
        "contact: security@example.org",
        f"upstream: https://github.com/x/y @ {SHA}",
        "license: Apache-2.0",
        f"images: humanbound-arena-echo:test {DIGEST}",
        "keys: ECHO_PREFIX",
    ):
        assert text in out
    assert "stored-value" not in out
    assert docker_ok.started == [("echo", {"ECHO_PREFIX": "stored-value"})]
    # remembered: no second prompt, even non-interactive
    docker_ok.running.clear()
    from humanbound_cli.commands import arena as arena_cmd

    arena_cmd._interactive = lambda: False  # restored by monkeypatch
    result = run("run", "echo")
    assert result.exit_code == 0, result.output


def test_confirmation_without_upstream_or_digests(docker_ok, arena_env, interactive):
    _install_variant(arena_env, index=CUSTOM_INDEX)
    result = run("run", "echo", input="y\n")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert "developer: Humanbound (https://humanbound.ai)" in out
    assert "contact: maintainers@example.org" in out
    assert "upstream" not in out and "license" not in out
    assert "images: humanbound-arena-echo:test keys:" in out  # the tag, no digest


def test_untrusted_agent_declined(docker_ok, arena_env, interactive):
    _untrusted_install(arena_env)
    result = run("run", "echo", input="n\n")
    assert result.exit_code == 1
    assert docker_ok.started == []
    from humanbound_cli.arena import consent

    m, folder = catalog.installed("echo")
    assert not consent.is_accepted(m, folder)


def test_untrusted_agent_yes_skips_and_remembers(docker_ok, arena_env):
    _untrusted_install(arena_env)
    result = run("run", "echo", "--yes")
    assert result.exit_code == 0, result.output
    from humanbound_cli.arena import consent

    m, folder = catalog.installed("echo")
    assert consent.is_accepted(m, folder)
    assert (arena_env / consent.ACCEPTED_FILE).exists()


def test_changed_manifest_asks_again(docker_ok, arena_env):
    folder = _untrusted_install(arena_env)
    assert run("run", "echo", "--yes").exit_code == 0
    docker_ok.running.clear()
    data = yaml.safe_load((folder / "arena.yaml").read_text())
    data["source"]["image"] = "x/echo:2"
    (folder / "arena.yaml").write_text(yaml.safe_dump(data))
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "--yes" in flat(result)


def test_changed_digests_ask_again(docker_ok, arena_env):
    folder = _untrusted_install(arena_env)
    assert run("run", "echo", "--yes").exit_code == 0
    docker_ok.running.clear()
    record = json.loads((folder / catalog.PROVENANCE_FILE).read_text())
    record["images"][0]["digest"] = "sha256:" + "b" * 64
    (folder / catalog.PROVENANCE_FILE).write_text(json.dumps(record))
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "--yes" in flat(result)


def test_custom_catalog_needs_confirmation(docker_ok, arena_env, monkeypatch, tmp_path):
    monkeypatch.setenv("HB_ARENA_INDEX", str(_custom_catalog(tmp_path)))
    result = run("run", "echo")
    assert result.exit_code == 1
    assert "--yes" in flat(result)
    assert run("run", "echo", "--yes").exit_code == 0


# telemetry


def test_telemetry_custom_catalog_hides_agent(docker_ok, arena_env, events, monkeypatch, tmp_path):
    monkeypatch.setenv("HB_ARENA_INDEX", str(_custom_catalog(tmp_path)))
    monkeypatch.setattr(runtime, "pull", lambda m, d: None)
    assert run("pull", "echo").exit_code == 0
    assert run("run", "echo", "--yes").exit_code == 0
    assert events == [("arena_pull", {"agent": "custom"}), ("arena_run", {"agent": "custom"})]


# ── digests from the index, through the real runtime.pull (docker faked) ──


def _docker_store(monkeypatch, images: dict):
    """runtime._run backed by a dict of local tags -> RepoDigests; returns the argv log."""
    import subprocess

    calls = []

    def fake_run(argv, capture, env=None, timeout=None):
        calls.append(list(argv))
        args = argv[1:]
        rc, out = 0, ""
        if args[:2] == ["image", "inspect"]:
            if args[-1] in images:
                out = json.dumps(images[args[-1]])
            else:
                rc = 1
        elif args[:1] == ["pull"]:
            images[args[1]] = [args[1]]
        elif args[:1] == ["tag"]:
            images[args[2]] = images[args[1]]
        return subprocess.CompletedProcess(argv, rc, out, "")

    monkeypatch.setattr(runtime, "_run", fake_run)
    return calls


def _pinned_catalog(monkeypatch, tmp_path):
    images = [{"ref": "humanbound-arena-echo:test", "digest": DIGEST}]
    monkeypatch.setenv("HB_ARENA_INDEX", str(_custom_catalog(tmp_path, images=images)))


def test_pull_fetches_a_missing_published_image_by_digest(arena_env, monkeypatch, tmp_path):
    _pinned_catalog(monkeypatch, tmp_path)
    calls = _docker_store(monkeypatch, {})
    result = run("pull", "echo")
    assert result.exit_code == 0, result.output
    by_digest = "humanbound-arena-echo@" + DIGEST
    assert ["docker", "pull", by_digest] in calls
    assert ["docker", "tag", by_digest, "humanbound-arena-echo:test"] in calls


def test_pull_refuses_a_local_build_under_the_published_tag(
    arena_env, monkeypatch, tmp_path, events
):
    _pinned_catalog(monkeypatch, tmp_path)
    calls = _docker_store(monkeypatch, {"humanbound-arena-echo:test": []})
    result = run("pull", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "the local image humanbound-arena-echo:test is not the one the catalog published" in out
    assert f"expected {DIGEST}, found locally built, no registry digest" in out
    assert "docker rmi humanbound-arena-echo:test" in out
    assert "HB_ARENA_INDEX=<checkout>" in out
    assert not any(argv[1] in ("pull", "tag") for argv in calls)
    assert events == []


def test_run_refuses_a_stale_published_tag(docker_ok, arena_env, monkeypatch, tmp_path):
    _pinned_catalog(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "start", _REAL_START)
    stale = "sha256:" + "9" * 64
    _docker_store(monkeypatch, {"humanbound-arena-echo:test": ["humanbound-arena-echo@" + stale]})
    result = run("run", "echo", "--yes")
    assert result.exit_code == 1
    out = flat(result)
    compact = re.sub(r"\s+", "", result.output)  # Rich may break the long digest anywhere
    assert f"expected{DIGEST},foundhumanbound-arena-echo@{stale}" in compact
    assert "docker rmi humanbound-arena-echo:test" in out
    assert docker_ok.started == []


def test_local_catalog_without_digests_runs_a_local_build(arena_env, monkeypatch, tmp_path):
    # A checkout or PR has no images in its index: tags as usual, no warning.
    monkeypatch.setenv("HB_ARENA_INDEX", str(_custom_catalog(tmp_path)))
    calls = _docker_store(monkeypatch, {"humanbound-arena-echo:test": []})
    result = run("pull", "echo")
    assert result.exit_code == 0, result.output
    assert "WARNING" not in result.output and "digest" not in result.output
    assert ["docker", "pull", "humanbound-arena-echo:test"] in calls


# ── old Docker Engine on Linux ──


@pytest.mark.parametrize(
    "info, warned",
    [
        (runtime.DockerInfo("27.5.1", "Ubuntu 24.04 LTS"), True),
        (runtime.DockerInfo("28.1.0", "Ubuntu 24.04 LTS"), False),
        (None, False),
    ],
)
def test_run_warns_about_old_linux_engines(docker_ok, monkeypatch, info, warned):
    monkeypatch.setattr(runtime, "preflight", lambda m=None: info)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert ("Docker Engine 27.5.1" in out) is warned
    assert ("reachable from your local network" in out) is warned
    assert out.count("upgrade to Docker Engine 28") == (1 if warned else 0)


def test_run_does_not_warn_on_macos(docker_ok, monkeypatch):
    monkeypatch.setattr(
        runtime, "preflight", lambda m=None: runtime.DockerInfo("27.5.1", "Docker Desktop")
    )
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    assert "Docker Engine 28" not in flat(run("run", "echo"))


# ── token ──


def test_token_creates_and_prints_only_the_token(arena_env):
    assert paths.gateway_token(create=False) is None
    result = run("token")
    assert result.exit_code == 0, result.output
    token = paths.gateway_token(create=False)
    assert token
    assert result.stdout == token + "\n"
    assert result.stderr == ""
    # the same token every time
    again = run("token")
    assert again.exit_code == 0
    assert again.stdout == result.stdout


def test_token_needs_no_docker(arena_env, monkeypatch):
    monkeypatch.setattr(runtime, "docker_cli", lambda: None)
    result = run("token")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == paths.gateway_token(create=False)


def test_token_unreadable_fails_on_stderr(arena_env, monkeypatch):
    def broken(**kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(paths, "gateway_token", broken)
    result = run("token")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "permission denied" in result.stderr


def test_token_help_says_to_treat_it_like_a_password(arena_env):
    result = run("token", "--help")
    assert result.exit_code == 0
    assert "like a password" in flat(result)


# ── what an agent may reach on the network ──

MODEL_RUNTIME = {
    "port": 8080,
    "env": {"required": ["OPENAI_API_KEY"], "optional": ["OPENAI_BASE_URL"]},
}


def _model_install(arena_env, egress=None, **extra):
    spec = dict(MODEL_RUNTIME, **({"egress": egress} if egress else {}))
    keys.set_value("OPENAI_API_KEY", "sk-1234567890abcdef")
    return _install_variant(arena_env, runtime=spec, **extra)


def test_info_says_what_the_agent_may_reach(arena_env):
    assert "Network: blocked (it may reach nothing)" in flat(run("info", "echo"))
    _model_install(arena_env, egress=["files.example.com", "api.example.com:8443"])
    out = flat(run("info", "echo"))
    assert (
        "Network: blocked, except its model (api.openai.com:443, or the host and port of "
        "OPENAI_BASE_URL), files.example.com:443, api.example.com:8443"
    ) in out


def test_run_blocks_the_network_and_says_what_is_let_through(docker_ok, arena_env):
    _model_install(arena_env, egress=["files.example.com"])
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert "Network: blocked, except api.openai.com:443 (the model), files.example.com:443" in out
    assert docker_ok.door_pulls == 1


def test_run_lets_the_users_model_through(docker_ok, arena_env):
    _model_install(arena_env)
    keys.set_value("OPENAI_BASE_URL", "http://host.docker.internal:11434/v1")
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert "Network: blocked, except host.docker.internal:11434 (the model)" in flat(result)


def test_run_with_nothing_to_reach(docker_ok, arena_env):
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert "Network: blocked, except nothing" in flat(result)


def test_run_refuses_a_model_url_it_cannot_read(docker_ok, arena_env):
    _model_install(arena_env)
    keys.set_value("OPENAI_BASE_URL", "user:s3cret@llm.example.com")
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "cannot start echo: OPENAI_BASE_URL must be an http(s) URL" in out
    assert "s3cret" not in out
    assert docker_ok.started == []


def test_run_warns_when_the_model_is_on_localhost(docker_ok, arena_env):
    _model_install(arena_env)
    keys.set_value("OPENAI_BASE_URL", "http://localhost:11434/v1")
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    out = flat(result)
    assert "OPENAI_BASE_URL points at localhost" in out and "host.docker.internal" in out
    assert "Network: blocked, except nothing" in out


def test_run_says_when_docker_cannot_hide_the_gateway(docker_ok, arena_env):
    docker_ok.gateway_reachable = True
    result = run("run", "echo")
    assert result.exit_code == 0, result.output
    assert "can't take the gateway address off the agent's network" in flat(result)
    docker_ok.running.clear()
    docker_ok.gateway_reachable = False
    assert "gateway address" not in flat(run("run", "echo"))


def _never_healthy(monkeypatch):
    def timeout(agent, health):
        raise runtime.HealthTimeout("echo did not become healthy within 30s")

    monkeypatch.setattr(runtime, "wait_healthy", timeout)
    monkeypatch.setattr(runtime, "last_logs", lambda *a, **kw: "")


def test_a_failed_start_shows_what_the_door_refused(docker_ok, arena_env, monkeypatch):
    _never_healthy(monkeypatch)
    docker_ok.refused = ["telemetry.example.com:443", "pypi.org:443"]
    result = run("run", "echo")
    assert result.exit_code == 1
    out = flat(result)
    assert "It tried to reach, and hb refused: telemetry.example.com:443, pypi.org:443" in out
    assert "only way out is hb's proxy" in out
    assert docker_ok.stopped == ["echo"]


def test_the_confirmation_shows_what_the_agent_may_reach(docker_ok, arena_env, interactive):
    _untrusted_install(arena_env, runtime=dict(MODEL_RUNTIME, egress=["files.example.com"]))
    keys.set_value("OPENAI_API_KEY", "sk-1234567890abcdef")
    result = run("run", "echo", input="y\n")
    assert result.exit_code == 0, result.output
    assert (
        "network: blocked, except api.openai.com:443 (the model), files.example.com:443"
    ) in flat(result)


def test_a_manifest_that_may_reach_more_is_confirmed_again(docker_ok, arena_env, interactive):
    _untrusted_install(arena_env)
    assert run("run", "echo", "--yes").exit_code == 0
    docker_ok.running.clear()
    _untrusted_install(arena_env, runtime={"port": 8080, "egress": ["files.example.com"]})
    result = run("run", "echo", input="n\n")
    assert result.exit_code == 1
    assert "network: blocked, except files.example.com:443" in flat(result)


def test_check_reports_a_network_with_a_route_out(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(monkeypatch, good("arena-x-echo"))
    monkeypatch.setattr(
        runtime, "agent_networks", lambda c: _networks_without_a_route_out(c, internal=False)
    )
    result = run("check", "echo")
    assert result.exit_code == 1
    assert result.stdout.splitlines() == [
        "arena-x-echo: internal-networks: is on the network arena-x-echo, which has a route "
        "out (Internal is false)"
    ]


def test_check_cannot_run_when_the_networks_cannot_be_listed(docker_ok, monkeypatch):
    _running(docker_ok)
    _containers(monkeypatch, good("arena-x-echo"))

    def broken(containers):
        raise DockerError("docker did not respond within 15s")

    monkeypatch.setattr(runtime, "agent_networks", broken)
    result = run("check", "echo")
    assert result.exit_code == 2
    assert "docker did not respond" in result.stderr


def test_logs_of_the_door(docker_ok, monkeypatch):
    monkeypatch.setattr(runtime, "logs", _no_process)
    docker_ok.running.append(runtime.RunningAgent("echo", "0.1.0", "image", 40123))
    result = run("logs", "echo", "--door", "--tail", "7", "-f")
    assert result.exit_code == 0, result.output
    assert docker_ok.door_logged == [("echo", True, 7)]


def test_logs_of_the_door_docker_error(docker_ok, monkeypatch):
    docker_ok.running.append(runtime.RunningAgent("echo", "0.1.0", "image", 40123))

    def boom(agent_id, **kw):
        raise DockerError("docker logs failed: No such container")

    monkeypatch.setattr(runtime, "door_logs", boom)
    result = run("logs", "echo", "--door")
    assert result.exit_code == 1
    assert "No such container" in flat(result)


@pytest.mark.parametrize("any_owner", [False, True])
def test_stop_all_removes_doors_left_behind(docker_ok, any_owner):
    _running(docker_ok)
    args = ["stop", "--all", *(["--any-owner"] if any_owner else [])]
    assert run(*args).exit_code == 0
    assert docker_ok.door_sweeps == [any_owner]
    docker_ok.door_sweeps.clear()
    assert run("stop", "--all").exit_code == 0  # nothing running: doors are still swept
    assert docker_ok.door_sweeps == [False]


def test_stop_one_agent_leaves_other_doors_alone(docker_ok):
    _running(docker_ok)
    assert run("stop", "echo").exit_code == 0
    assert docker_ok.door_sweeps == []


def test_pull_also_fetches_the_door_image(arena_env, monkeypatch):
    order = []
    monkeypatch.setattr(runtime, "pull", lambda m, d: order.append("agent"))
    monkeypatch.setattr(runtime, "pull_door_image", lambda: order.append("door"))
    assert run("pull", "echo").exit_code == 0
    assert order == ["agent", "door"]


def test_run_help_says_what_blocking_is_and_is_not(arena_env):
    out = flat(run("run", "--help"))
    assert "--open-network" not in out  # there is no way to run an agent without the block
    assert "An allowed destination is still a way out" in out
    assert "a container is not a virtual machine" in out
    lowered = out.lower()
    assert "safe" not in lowered and "secure" not in lowered and "sandbox" not in lowered
