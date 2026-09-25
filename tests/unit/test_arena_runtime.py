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
        self.containers = []  # inspect dicts
        self.fail = {}  # argv prefix tuple -> returncode

    def __call__(self, argv, capture):
        args = argv[1:]
        self.calls.append(args)
        for prefix, code in self.fail.items():
            if tuple(args[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, "", "boom")
        if args[:1] == ["ps"]:
            out = "\n".join(f"c{i}" for i, _ in enumerate(self.containers))
            return subprocess.CompletedProcess(argv, 0, out, "")
        if args[:1] == ["inspect"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.containers), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

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


def test_start_compose_agent_writes_override_with_labels_and_loopback_port(docker, tmp_path):
    data = copy.deepcopy(ECHO.model_dump(mode="json"))
    data["source"] = {"compose": "docker-compose.yml", "service": "agent"}
    m = parse_manifest(data)
    docker.containers = [_inspect("echo", "0.1.0", "compose", 8080, 50000)]

    runtime.start(m, tmp_path, {})

    override = yaml.safe_load((tmp_path / runtime.OVERRIDE_FILE).read_text())
    svc = override["services"]["agent"]
    assert svc["ports"] == ["127.0.0.1::8080"]
    assert svc["labels"][runtime.LABEL_KIND] == "compose"
    up = docker.called("compose")[0]
    assert up[up.index("-p") + 1] == "arena-echo"
    assert up[-3:] == ["-d", "--force-recreate", "--renew-anon-volumes"]


def test_list_running_parses_labels_and_ports(docker):
    docker.containers = [
        _inspect("zeta", "1.0.0", "image", 8080, 40001),
        _inspect("alpha", "2.0.0", "compose", 9000, 40002),
    ]
    agents = runtime.list_running()
    assert [a.id for a in agents] == ["alpha", "zeta"]
    assert agents[0] == RunningAgent("alpha", "2.0.0", "compose", 40002)


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
