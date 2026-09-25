# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import copy
import json
import subprocess

import pytest
import yaml
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import runtime
from humanbound_cli.arena.manifest import load_manifest, parse_manifest
from humanbound_cli.arena.runtime import DockerError, HealthTimeout, RunningAgent

ECHO = load_manifest(ARENA_FIXTURES / "catalog" / "agents" / "echo" / "arena.yaml")


def _inspect(agent_id, version, kind, port, host_port):
    return {
        "Config": {
            "Labels": {
                runtime.LABEL_ID: agent_id,
                runtime.LABEL_VERSION: version,
                runtime.LABEL_KIND: kind,
                runtime.LABEL_PORT: str(port),
            }
        },
        "NetworkSettings": {
            "Ports": {f"{port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(host_port)}]}
        },
    }


class FakeDocker:
    """Records docker argv; answers `ps`/`inspect` with the configured containers."""

    def __init__(self):
        self.calls = []
        self.envs = []  # subprocess env per call (None = inherited)
        self.timeouts = []  # subprocess timeout per call
        self.containers = []  # inspect dicts
        self.fail = {}  # argv prefix tuple -> returncode
        self.inspect_code = 0
        self.inspect_out = None  # override inspect stdout

    def __call__(self, argv, capture, env=None, timeout=None):
        args = argv[1:]
        self.calls.append(args)
        self.envs.append(env)
        self.timeouts.append(timeout)
        for prefix, code in self.fail.items():
            if tuple(args[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, "", "boom")
        if args[:1] == ["ps"]:
            out = "\n".join(f"c{i}" for i, _ in enumerate(self.containers))
            return subprocess.CompletedProcess(argv, 0, out, "")
        if args[:1] == ["inspect"]:
            out = self.inspect_out if self.inspect_out is not None else json.dumps(self.containers)
            return subprocess.CompletedProcess(argv, self.inspect_code, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def env_of(self, *prefix):
        return [
            e
            for c, e in zip(self.calls, self.envs, strict=True)
            if tuple(c[: len(prefix)]) == prefix
        ]

    def called(self, *prefix):
        return [c for c in self.calls if tuple(c[: len(prefix)]) == prefix]


@pytest.fixture
def docker(monkeypatch, arena_home):
    fake = FakeDocker()
    monkeypatch.setattr(runtime, "_run", fake)
    return fake


def test_preflight_reports_missing_docker(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    with pytest.raises(DockerError, match="Install Docker"):
        runtime.preflight()


def test_preflight_reports_stopped_daemon(monkeypatch, docker):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "/usr/bin/docker")
    docker.fail[("info",)] = 1
    with pytest.raises(DockerError, match="not running"):
        runtime.preflight()


def test_start_image_agent_is_isolated_and_loopback_only(docker, tmp_path):
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 49153)]
    agent = runtime.start(ECHO, tmp_path, {"ECHO_PREFIX": "s3cret-value"})

    run = docker.called("run")[0]
    assert run[run.index("-p") + 1] == "127.0.0.1::8080"
    assert run[run.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in run
    assert run[run.index("--network") + 1] == "arena-echo"
    assert f"{runtime.LABEL_ID}=echo" in run
    assert run[-1] == "humanbound-arena-echo:test"
    assert not any("s3cret-value" in part for call in docker.calls for part in call)
    env_file = runtime.run_env_file("echo")
    assert run[run.index("--env-file") + 1] == str(env_file)
    assert env_file.read_text() == "ECHO_PREFIX=s3cret-value\n"
    assert agent == RunningAgent("echo", "0.1.0", "image", 49153)
    assert agent.base_url == "http://127.0.0.1:49153"


def test_start_fails_when_port_is_not_published(docker, tmp_path):
    docker.containers = []
    with pytest.raises(DockerError, match="not published"):
        runtime.start(ECHO, tmp_path, {})


def test_start_cleans_up_when_port_is_not_published(docker, tmp_path):
    docker.containers = []
    with pytest.raises(DockerError, match="not published"):
        runtime.start(ECHO, tmp_path, {"ECHO_PREFIX": "x"})
    run_at = docker.calls.index(docker.called("run")[0])
    removed_after = [c for c in docker.calls[run_at:] if c[:4] == ["rm", "-f", "-v", "arena-echo"]]
    assert removed_after
    assert docker.called("network", "rm", "arena-echo")
    assert not runtime.run_env_file("echo").exists()


def test_start_keeps_the_port_error_when_cleanup_fails(docker, tmp_path, monkeypatch):
    docker.containers = []

    def broken_stop(agent_id, kind):
        raise DockerError("cleanup exploded")

    monkeypatch.setattr(runtime, "stop", broken_stop)
    with pytest.raises(DockerError, match="not published"):
        runtime.start(ECHO, tmp_path, {})


def test_start_passes_only_declared_keys(docker, tmp_path):
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 49153)]
    runtime.start(ECHO, tmp_path, {"ECHO_PREFIX": "p", "UNDECLARED": "nope"})
    assert runtime.run_env_file("echo").read_text() == "ECHO_PREFIX=p\n"


def _compose_manifest(env=None):
    data = copy.deepcopy(ECHO.model_dump(mode="json"))
    data["source"] = {"compose": "docker-compose.yml", "service": "agent"}
    if env is not None:
        data["runtime"]["env"] = env
    return parse_manifest(data)


def _write_compose(agent_dir, services, **top):
    doc = {"services": services, **top}
    (agent_dir / runtime.COMPOSE_FILE).write_text(yaml.safe_dump(doc))


SAFE_SERVICES = {
    "agent": {"build": ".", "depends_on": ["db"], "volumes": ["data:/data"]},
    "db": {"image": "postgres:16", "volumes": [{"type": "volume", "source": "pg", "target": "/x"}]},
}


def test_start_compose_agent_writes_override_with_labels_and_loopback_port(docker, tmp_path):
    m = _compose_manifest()
    _write_compose(tmp_path, SAFE_SERVICES, volumes={"data": {}, "pg": {}})
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]

    runtime.start(m, tmp_path, {})

    override = yaml.safe_load((tmp_path / runtime.OVERRIDE_FILE).read_text())
    svc = override["services"]["agent"]
    assert svc["ports"] == ["127.0.0.1::8080"]
    assert svc["labels"][runtime.LABEL_KIND] == "compose"
    assert svc["cap_drop"] == ["ALL"]
    up = docker.called("compose")[0]
    assert up[up.index("-p") + 1] == "arena-echo"
    assert up[-3:] == ["-d", "--force-recreate", "--renew-anon-volumes"]


def test_compose_secrets_travel_by_process_env_not_argv(docker, tmp_path, monkeypatch):
    m = _compose_manifest({"required": ["OPENAI_API_KEY"], "optional": ["ECHO_PREFIX"]})
    _write_compose(tmp_path, SAFE_SERVICES)
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]
    monkeypatch.setenv("HB_API_KEY", "hb-own-secret")
    monkeypatch.setenv("HUMANBOUND_TOKEN", "hb-own-token")
    monkeypatch.setenv("PATH", "/usr/bin")

    runtime.start(m, tmp_path, {"OPENAI_API_KEY": "sk-$ecret$$", "ECHO_PREFIX": "pre"})

    override = yaml.safe_load((tmp_path / runtime.OVERRIDE_FILE).read_text())
    svc = override["services"]["agent"]
    assert svc["environment"] == ["OPENAI_API_KEY", "ECHO_PREFIX"]
    assert "sk-$ecret$$" not in (tmp_path / runtime.OVERRIDE_FILE).read_text()
    compose_calls = docker.called("compose")
    assert compose_calls
    for call in compose_calls:
        assert "--env-file" not in call
        assert not any("sk-$ecret$$" in part or "pre" == part for part in call)
    (env,) = docker.env_of("compose", "-p", "arena-echo", "-f")
    assert env["OPENAI_API_KEY"] == "sk-$ecret$$"
    assert env["ECHO_PREFIX"] == "pre"
    assert env["PATH"] == "/usr/bin"
    assert "HB_API_KEY" not in env and "HUMANBOUND_TOKEN" not in env
    # the run file is still written (reset needs it)
    assert "OPENAI_API_KEY=sk-$ecret$$" in runtime.run_env_file("echo").read_text()


def test_compose_pull_does_not_inherit_hb_credentials(docker, tmp_path, monkeypatch):
    m = _compose_manifest()
    _write_compose(tmp_path, SAFE_SERVICES)
    monkeypatch.setenv("HB_API_KEY", "hb-own-secret")
    runtime.pull(m, tmp_path)
    (env,) = docker.env_of("compose")
    assert env is not None and "HB_API_KEY" not in env


def test_compose_env_only_carries_allowlisted_host_vars(docker, tmp_path, monkeypatch):
    """A compose file's ${VAR} interpolation must not be able to read arbitrary host
    secrets: only an explicit allowlist of harmless base vars, plus the agent's own
    declared keys, may reach the compose subprocess environment."""
    m = _compose_manifest({"required": ["OPENAI_API_KEY"]})
    _write_compose(tmp_path, SAFE_SERVICES)
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-super-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-super-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    runtime.start(m, tmp_path, {"OPENAI_API_KEY": "sk-agent-key"})

    (env,) = docker.env_of("compose", "-p", "arena-echo", "-f")
    assert env["PATH"] == "/usr/bin"
    assert env["OPENAI_API_KEY"] == "sk-agent-key"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_reset_compose_passes_the_saved_env(docker, tmp_path, monkeypatch):
    m = _compose_manifest({"required": ["OPENAI_API_KEY"]})
    _write_compose(tmp_path, SAFE_SERVICES)
    runtime.write_env_file(runtime.run_env_file("echo"), {"OPENAI_API_KEY": "sk-keep"})
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)

    runtime.reset(m, tmp_path)

    up_env = [e for c, e in zip(docker.calls, docker.envs, strict=True) if "up" in c]
    assert up_env and up_env[0]["OPENAI_API_KEY"] == "sk-keep"


# The rules themselves are tested in test_arena_compose_safety.py; here: runtime applies them.
@pytest.mark.parametrize("action", ["start", "pull"])
def test_unsafe_compose_is_refused_before_any_compose_call(docker, tmp_path, action):
    m = _compose_manifest()
    _write_compose(tmp_path, {"agent": {"image": "a"}, "sidecar": {"image": "x", "ports": ["1:1"]}})
    with pytest.raises(DockerError, match="sidecar"):
        if action == "start":
            runtime.start(m, tmp_path, {})
        else:
            runtime.pull(m, tmp_path)
    assert docker.called("compose") == []


def test_override_hardens_every_service_but_exposes_only_the_talked_to_one(docker, tmp_path):
    m = _compose_manifest({"required": ["OPENAI_API_KEY"]})
    _write_compose(tmp_path, SAFE_SERVICES, volumes={"data": {}, "pg": {}})
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]

    runtime.start(m, tmp_path, {"OPENAI_API_KEY": "sk"})

    services = yaml.safe_load((tmp_path / runtime.OVERRIDE_FILE).read_text())["services"]
    assert set(services) == {"agent", "db"}
    for svc in services.values():
        assert svc["cap_drop"] == ["ALL"]
        assert svc["security_opt"] == ["no-new-privileges:true"]
    assert services["db"] == {"cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]}
    assert services["agent"]["ports"] == ["127.0.0.1::8080"]
    assert services["agent"]["environment"] == ["OPENAI_API_KEY"]
    assert runtime.LABEL_ID in services["agent"]["labels"]


def test_list_running_parses_labels_and_ports(docker):
    docker.containers = [
        _inspect("zeta", "1.0.0", "image", 8080, 40001),
        _inspect("alpha", "2.0.0", "compose", 9000, 40002),
    ]
    agents = runtime.list_running()
    assert [a.id for a in agents] == ["alpha", "zeta"]
    assert agents[0] == RunningAgent("alpha", "2.0.0", "compose", 40002)


def test_list_running_tolerates_inspect_exit_code(docker):
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 40001)]
    docker.inspect_code = 1  # e.g. a second container vanished between ps and inspect
    assert runtime.list_running() == [RunningAgent("echo", "0.1.0", "image", 40001)]


@pytest.mark.parametrize("out", ["", "not json", "{}", "[1, null]"])
def test_list_running_treats_bad_inspect_output_as_empty(docker, out):
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 40001)]
    docker.inspect_code = 1
    docker.inspect_out = out
    assert runtime.list_running() == []


def test_list_running_skips_containers_without_id_label(docker):
    unlabeled = _inspect("x", "1.0.0", "image", 8080, 40009)
    del unlabeled["Config"]["Labels"][runtime.LABEL_ID]
    docker.containers = [unlabeled, _inspect("echo", "0.1.0", "image", 8080, 40001)]
    assert [a.id for a in runtime.list_running()] == ["echo"]


def test_list_running_empty_skips_inspect(docker):
    assert runtime.list_running() == []
    assert docker.called("inspect") == []


def test_wait_healthy_retries_until_ok():
    agent = RunningAgent("echo", "0.1.0", "image", 49153)
    answers = iter([Exception("refused"), 503, 200])
    urls = []

    def get(url, timeout):
        urls.append(url)
        a = next(answers)
        if isinstance(a, Exception):
            raise runtime.httpx.ConnectError("refused")
        return runtime.httpx.Response(a)

    runtime.wait_healthy(agent, ECHO.runtime.health, get=get, sleep=lambda _: None)
    assert urls[-1] == "http://127.0.0.1:49153/health"
    assert len(urls) == 3


def test_wait_healthy_times_out():
    agent = RunningAgent("echo", "0.1.0", "image", 49153)
    ticks = iter(range(100))

    def get(url, timeout):
        raise runtime.httpx.ConnectError("refused")

    with pytest.raises(HealthTimeout, match="within 30s"):
        runtime.wait_healthy(
            agent,
            ECHO.runtime.health,
            get=get,
            sleep=lambda _: None,
            clock=lambda: next(ticks),
        )


def test_stop_image_removes_container_network_and_env_file(docker):
    runtime.write_env_file(runtime.run_env_file("echo"), {"A": "1"})
    runtime.stop("echo", "image")
    assert docker.called("rm", "-f", "-v", "arena-echo")
    assert docker.called("network", "rm", "arena-echo")
    assert not runtime.run_env_file("echo").exists()


def test_stop_compose_runs_down(docker):
    runtime.stop("echo", "compose")
    down = docker.called("compose")[0]
    assert down[-3:] == ["down", "-v", "--remove-orphans"]


def test_reset_recreates_with_the_same_env(docker, tmp_path, monkeypatch):
    runtime.write_env_file(runtime.run_env_file("echo"), {"ECHO_PREFIX": "keep-me"})
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 49153)]
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)

    agent = runtime.reset(ECHO, tmp_path)

    assert agent.host_port == 49153
    assert runtime.run_env_file("echo").read_text() == "ECHO_PREFIX=keep-me\n"
    assert docker.called("rm", "-f", "-v", "arena-echo")
    assert docker.called("run")


def test_list_running_bounds_docker_calls_with_a_timeout(docker):
    docker.containers = [_inspect("echo", "0.1.0", "image", 8080, 40001)]
    runtime.list_running()
    assert [c[0] for c in docker.calls] == ["ps", "inspect"]
    assert all(t is not None and t > 0 for t in docker.timeouts)


def test_docker_timeout_becomes_docker_error(monkeypatch):
    def hang(argv, capture, env=None, timeout=None):
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(runtime, "_run", hang)
    with pytest.raises(DockerError, match="did not respond within 15"):
        runtime.list_running()


def test_docker_error_with_no_captured_output_has_no_dangling_colon(monkeypatch):
    def uncaptured(argv, capture, env=None, timeout=None):
        assert capture is False
        return subprocess.CompletedProcess(argv, 1, None, None)

    monkeypatch.setattr(runtime, "_run", uncaptured)
    with pytest.raises(DockerError, match=r"failed \(see the output above\)$"):
        runtime._docker("pull", "some/image", capture=False)
