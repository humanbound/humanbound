# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the arena Docker runtime. Docker is never called: runtime._run is faked."""

import copy
import json
import re
import subprocess
import sys

import httpx
import pytest
import yaml

from humanbound_cli.arena import compose_safety, paths, runtime
from humanbound_cli.arena.manifest import Health, load_manifest, parse_manifest
from humanbound_cli.arena.runtime import (
    COMPOSE_MISSING,
    DOCKER_DOWN,
    DOCKER_MISSING,
    LABEL_DOOR,
    LABEL_ID,
    LABEL_KIND,
    LABEL_OWNER,
    LABEL_PORT,
    LABEL_SERVICE,
    LABEL_VERSION,
    LIST_TIMEOUT_S,
    OVERRIDE_FILE,
    DockerError,
    HealthTimeout,
    RunningAgent,
    list_running,
    preflight,
    reset,
    resource_name,
    run_env_file,
    start,
    stop,
    wait_healthy,
)

from .arena_testing import ECHO_YAML, mode_of
from .arena_testing import completed as _cp

SECRET = "sk-super-secret-value-1234"

COMPOSE = {
    "services": {
        "agent": {
            "image": "ghcr.io/example/arena-stack:0.1.0",
            "depends_on": ["db"],
            "environment": {"OPENAI_API_KEY": "${OPENAI_API_KEY}"},
        },
        "db": {"image": "postgres:16", "volumes": ["pgdata:/var/lib/postgresql/data"]},
    },
    "volumes": {"pgdata": None},
}


DOOR_PORT = "49153"


def container(agent_id="echo", *, port=8080, kind="image", labels=None, published=None):
    """What `docker inspect` reports for an agent's container. It publishes nothing (its
    network can't): the way in is its door (see door()). `published` is a host port the
    container publishes all the same, as one from an hb before network blocking did."""
    lab = {
        LABEL_ID: agent_id,
        LABEL_VERSION: "0.1.0",
        LABEL_KIND: kind,
        LABEL_PORT: str(port),
        LABEL_OWNER: paths.arena_owner(),
        LABEL_DOOR: "",
    }
    if labels is not None:
        lab = labels
    ports, bindings = {}, {}
    if published is not None:
        ports = {f"{port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": published}]}
        bindings = {f"{port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]}
    if kind == "compose" and labels is None:
        lab[LABEL_SERVICE] = "agent"
        lab["com.docker.compose.service"] = "agent"
        lab["com.docker.compose.project"] = resource_name(agent_id)
    name = resource_name(agent_id)
    net = f"{name}_default" if kind == "compose" else name
    return {
        "Id": f"c-{agent_id}",
        "Name": f"/{name}",
        "Config": {"User": "65534", "Labels": lab},
        "Mounts": [],
        "HostConfig": {
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges"],
            "PidMode": "",
            "IpcMode": "private",
            "NetworkMode": net,
            "UTSMode": "",
            "UsernsMode": "",
            "PortBindings": bindings,
        },
        "NetworkSettings": {"Ports": ports, "Networks": {net: {}}},
    }


def door(agent_id="echo", *, host_port=DOOR_PORT, owner=None, name=None):
    """What `docker inspect` reports for the door of an agent."""
    owner = paths.arena_owner() if owner is None else owner
    name = name or runtime.door_name(resource_name(agent_id, owner))
    ports = (
        {} if host_port is None else {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": host_port}]}
    )
    return {
        "Id": f"door-{owner}-{agent_id}",
        "Name": f"/{name}",
        "Config": {"User": "65534:65534", "Labels": {LABEL_DOOR: agent_id, LABEL_OWNER: owner}},
        "NetworkSettings": {"Ports": ports},
    }


def _labels(c) -> dict:
    return (c.get("Config") or {}).get("Labels") or {}


def _matches(c, filters) -> bool:
    """`docker ps --filter label=K[=V]`: every filter must match."""
    for f in filters:
        if not f.startswith("label="):
            continue
        key, sep, value = f[len("label=") :].partition("=")
        if key not in _labels(c) or (sep and _labels(c)[key] != value):
            return False
    return True


class FakeDocker:
    """Stands in for runtime._run; records (argv, env, timeout, capture).

    It lists and inspects `containers` the way Docker does (label filters, ids), runs a door
    when hb starts one (`door_port` is the port it gets; None: it gets none), and reports
    every network as one with no route out, except those in `open_networks` and the ones
    hb created without --internal."""

    def __init__(self):
        self.calls = []
        self.containers = []
        self.open_networks = set()
        self.door_port = DOOR_PORT
        self.rules = []  # (predicate(args) -> bool, result(args) -> CompletedProcess | Exception)

    def on(self, predicate, result):
        self.rules.insert(0, (predicate, result))

    def __call__(self, argv, capture, env=None, timeout=None):
        self.calls.append((list(argv), env, timeout, capture))
        args = list(argv[1:])
        for predicate, result in self.rules:
            if predicate(args):
                out = result(args) if callable(result) else result
                if isinstance(out, BaseException):
                    raise out
                return out
        if args[:1] == ["ps"]:
            filters = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--filter"]
            found = [c for c in self.containers if _matches(c, filters)]
            return _cp(argv, 0, "\n".join(c["Id"] for c in found))
        if args[:1] == ["inspect"]:
            found = [c for c in self.containers if c["Id"] in args[1:]]
            return _cp(argv, 0 if len(found) == len(args[1:]) else 1, json.dumps(found))
        if args[:2] == ["network", "create"]:
            if "--internal" in args:
                self.open_networks.discard(args[-1])
            else:
                self.open_networks.add(args[-1])
        if args[:2] == ["network", "inspect"]:
            names = [a for a in args[2:] if not a.startswith("-")]
            data = [{"Name": n, "Internal": n not in self.open_networks} for n in names]
            return _cp(argv, 0, json.dumps(data))
        if args[:2] == ["network", "ls"]:
            project = next(a for a in args if a.startswith("label=")).rsplit("=", 1)[1]
            return _cp(argv, 0, f"{project}_default\n")
        if args[:1] == ["run"] and any(
            a.startswith(f"{LABEL_DOOR}=") and a[-1] != "=" for a in args
        ):
            agent_id = next(a for a in args if a.startswith(f"{LABEL_DOOR}=")).split("=", 1)[1]
            name = args[args.index("--name") + 1]
            self.containers.append(door(agent_id, host_port=self.door_port, name=name))
        if args[:1] == ["rm"] and args[-1].endswith("_door"):
            self.containers = [c for c in self.containers if c["Name"] != f"/{args[-1]}"]
        return _cp(argv, 0)

    def argvs(self):
        return [c[0] for c in self.calls]

    def find(self, *prefix):
        return [c for c in self.calls if c[0][1 : 1 + len(prefix)] == list(prefix)]


@pytest.fixture
def fake(arena_home, monkeypatch):
    f = FakeDocker()
    monkeypatch.setattr(runtime, "_run", f)
    return f


@pytest.fixture
def echo():
    return load_manifest(ECHO_YAML)


@pytest.fixture
def compose_agent(tmp_path):
    data = yaml.safe_load(ECHO_YAML.read_text())
    data = copy.deepcopy(data)
    data["id"] = "stack"
    data["source"] = {"compose": "docker-compose.yml", "service": "agent"}
    data["runtime"]["env"] = {"required": ["OPENAI_API_KEY"], "optional": ["ECHO_PREFIX"]}
    agent_dir = tmp_path / "stack"
    agent_dir.mkdir()
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(COMPOSE))
    return parse_manifest(data), agent_dir


def agent_run(fake):
    """The `docker run` of the agent itself (hb also runs its door)."""
    (run,) = [c for c in fake.find("run") if f"{LABEL_DOOR}=" in c[0]]
    return run


def door_run(fake):
    (run,) = [c for c in fake.find("run") if f"{LABEL_DOOR}=" not in c[0]]
    return run


def pair(argv, flag, value):
    return any(argv[i] == flag and argv[i + 1] == value for i in range(len(argv) - 1))


def door_stop(name):
    """What stop() runs first: the door holds on to the agent's networks."""
    return ["docker", "rm", "-f", "-v", f"{name}_door"]


def outside_rm(name):
    return ["docker", "network", "rm", f"{name}_out"]


def _no_secret_in_argv(fake):
    for argv in fake.argvs():
        assert not any(SECRET in a for a in argv), argv


# ── re-exports ──


def test_runtime_reexports_compose_safety():
    assert runtime.DockerError is compose_safety.DockerError
    assert runtime.check_compose is compose_safety.check_compose


# ── _docker error mapping ──


def test_docker_missing_binary(fake):
    fake.on(lambda a: True, FileNotFoundError("docker"))
    with pytest.raises(DockerError) as e:
        runtime._docker("ps")
    assert str(e.value) == DOCKER_MISSING


def test_docker_timeout(fake):
    fake.on(lambda a: True, subprocess.TimeoutExpired(["docker"], 15))
    with pytest.raises(DockerError, match="did not respond within 15s"):
        runtime._docker("ps", timeout=15.0)


def test_docker_failure_without_captured_stderr(fake):
    fake.on(lambda a: a[:1] == ["pull"], lambda a: _cp(a, 1))
    with pytest.raises(DockerError) as e:
        runtime._docker("pull", "x", capture=False)
    assert str(e.value).endswith("failed (see the output above)")
    assert not str(e.value).endswith(":")


def test_docker_failure_with_stderr(fake):
    fake.on(lambda a: a[:1] == ["pull"], lambda a: _cp(a, 1, stderr="manifest unknown\n"))
    with pytest.raises(DockerError, match="manifest unknown"):
        runtime._docker("pull", "x")


# ── preflight ──


def test_preflight_docker_missing(fake, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    with pytest.raises(DockerError) as e:
        preflight()
    assert str(e.value) == DOCKER_MISSING


def test_preflight_docker_down(fake, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 1))
    with pytest.raises(DockerError) as e:
        preflight()
    assert str(e.value) == DOCKER_DOWN


@pytest.mark.parametrize(
    "stderr, fragment",
    [
        (
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?",
            "not running",
        ),
        (
            "permission denied while trying to connect to the Docker daemon socket",
            "permission denied on the Docker socket",
        ),
    ],
)
def test_preflight_exit_zero_without_a_server_version_is_not_usable(
    fake, monkeypatch, stderr, fragment
):
    """Some docker CLIs exit 0 from `docker info --format` when the daemon is unreachable:
    the error goes to stderr and the server fields come back empty."""
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 0, "|\n", stderr))
    with pytest.raises(DockerError) as e:
        preflight()
    assert fragment in str(e.value)


def test_preflight_compose_missing(fake, monkeypatch, echo, compose_agent):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 0, "27.5.1|Docker Desktop\n"))
    fake.on(lambda a: a[:2] == ["compose", "version"], lambda a: _cp(a, 1))
    preflight(echo)  # image agents don't need compose
    with pytest.raises(DockerError) as e:
        preflight(compose_agent[0])
    assert str(e.value) == COMPOSE_MISSING


def test_preflight_ok(fake, monkeypatch, compose_agent):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 0, "27.5.1|Ubuntu 24.04 LTS\n"))
    info = preflight(compose_agent[0])
    assert info == runtime.DockerInfo("27.5.1", "Ubuntu 24.04 LTS")
    (argv, _, timeout, _) = fake.find("info")[0]
    assert argv == ["docker", "info", "--format", "{{.ServerVersion}}|{{.OperatingSystem}}"]
    assert timeout == LIST_TIMEOUT_S


PERMISSION_DENIED = (
    "permission denied while trying to connect to the Docker daemon socket at "
    'unix:///var/run/docker.sock: Get "http://%2Fvar%2Frun%2Fdocker.sock/v1.47/info": '
    "dial unix /var/run/docker.sock: connect: permission denied"
)
NOT_RUNNING = (
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
    "Is the docker daemon running?"
)


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_preflight_permission_denied(fake, monkeypatch, platform):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(runtime.sys, "platform", platform)
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 1, "", PERMISSION_DENIED))
    with pytest.raises(DockerError) as e:
        preflight()
    message = str(e.value)
    assert "permission denied on the Docker socket" in message
    if platform == "linux":
        assert "docker group" in message and "usermod -aG docker" in message
        assert "DOCKER_HOST" in message and "rootless" in message
    else:
        assert "Docker Desktop" in message


@pytest.mark.parametrize(
    "platform, hint",
    [
        ("linux", "sudo systemctl start docker"),
        ("darwin", "Start Docker Desktop"),
        ("win32", "Start Docker Desktop"),
    ],
)
def test_preflight_daemon_not_running_hint_per_os(fake, monkeypatch, platform, hint):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(runtime.sys, "platform", platform)
    fake.on(lambda a: a[:1] == ["info"], lambda a: _cp(a, 1, "", NOT_RUNNING))
    with pytest.raises(DockerError) as e:
        preflight()
    assert "not running" in str(e.value) and hint in str(e.value)
    assert "permission" not in str(e.value)


def test_compose_missing_mentions_the_linux_plugin():
    assert "Docker Desktop" in COMPOSE_MISSING
    assert "compose plugin" in COMPOSE_MISSING and "Linux" in COMPOSE_MISSING


@pytest.mark.parametrize(
    "platform, info, exposed",
    [
        ("linux", runtime.DockerInfo("27.5.1", "Ubuntu 24.04 LTS"), True),
        ("linux", runtime.DockerInfo("20.10.24", "Debian GNU/Linux 12"), True),
        ("linux", runtime.DockerInfo("28.0.0", "Ubuntu 24.04 LTS"), False),
        ("linux", runtime.DockerInfo("29.1.2", "Fedora"), False),
        ("linux", runtime.DockerInfo("27.5.1", "Docker Desktop"), False),  # in a VM
        ("linux", runtime.DockerInfo("", ""), False),  # unknown: don't guess
        ("linux", runtime.DockerInfo("dev", "Ubuntu"), False),
        ("darwin", runtime.DockerInfo("27.5.1", "Docker Desktop"), False),
        ("win32", runtime.DockerInfo("27.5.1", "Docker Desktop"), False),
    ],
)
def test_loopback_exposed_on_old_linux_engines(monkeypatch, platform, info, exposed):
    monkeypatch.setattr(runtime.sys, "platform", platform)
    assert runtime.loopback_ports_exposed(info) is exposed


# ── image agents ──


def test_start_image_agent(fake, echo, tmp_path, arena_home):
    fake.containers = [container()]
    agent = start(echo, tmp_path, {"ECHO_PREFIX": SECRET, "UNDECLARED": "nope"})
    assert agent == RunningAgent("echo", "0.1.0", "image", 49153)
    assert agent.base_url == "http://127.0.0.1:49153"  # the door's port
    assert not agent.gateway_reachable

    argv = agent_run(fake)[0]
    name = resource_name("echo")
    env_file = run_env_file("echo")
    assert env_file == arena_home / "run" / "echo.env"

    assert "-p" not in argv  # its network can't publish a port: the door is the way in
    assert pair(argv, "--cap-drop", "ALL")
    assert pair(argv, "--security-opt", "no-new-privileges")
    assert pair(argv, "--network", name)
    assert pair(argv, "--name", name)
    assert pair(argv, "--env-file", str(env_file))
    for label in (
        f"{LABEL_ID}=echo",
        f"{LABEL_VERSION}=0.1.0",
        f"{LABEL_KIND}=image",
        f"{LABEL_PORT}=8080",
        f"{LABEL_OWNER}={paths.arena_owner()}",
        f"{LABEL_DOOR}=",
    ):
        assert pair(argv, "--label", label)
    for key, value in runtime.egress.proxy_env([name]).items():
        assert pair(argv, "-e", f"{key}={value}")
    assert argv[-1] == "humanbound-arena-echo:test"
    _no_secret_in_argv(fake)
    assert env_file.read_text() == f"ECHO_PREFIX={SECRET}\n"
    assert mode_of(env_file) == 0o600


def test_an_agents_network_has_no_route_out_and_no_gateway_address(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {})
    name = resource_name("echo")
    hidden = f"{runtime.NO_BRIDGE_ADDRESS}=true"
    created = [c[0][3:] for c in fake.find("network", "create")]
    assert created == [
        ["--internal", "-o", hidden, f"{name}_probe"],  # can this Docker do it?
        ["--internal", "-o", hidden, name],
        ["--label", f"{LABEL_OWNER}={paths.arena_owner()}", f"{name}_out"],
    ]
    assert ["docker", "network", "rm", f"{name}_probe"] in fake.argvs()


def test_a_docker_that_cannot_hide_the_gateway_is_used_as_it_is(fake, echo, tmp_path):
    fake.containers = [container()]
    fake.on(
        lambda a: a[:2] == ["network", "create"] and "-o" in a,
        lambda a: _cp(a, 1, "", "unknown option"),
    )
    agent = start(echo, tmp_path, {})
    assert agent.gateway_reachable
    name = resource_name("echo")
    assert ["docker", "network", "create", "--internal", name] in fake.argvs()


def test_the_door_runs_before_the_agent_without_privileges(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {})
    name = resource_name("echo")
    argv = door_run(fake)[0]
    runs = [c[0] for c in fake.find("run")]
    assert runs.index(argv) < runs.index(agent_run(fake)[0])
    assert pair(argv, "--name", f"{name}_door")
    assert pair(argv, "--network", f"{name}_out")
    assert pair(argv, "-p", "127.0.0.1::8080")
    assert pair(argv, "--user", "65534:65534") and "--read-only" in argv
    assert pair(argv, "--cap-drop", "ALL")
    assert pair(argv, "--security-opt", "no-new-privileges")
    assert pair(argv, "--pids-limit", str(runtime.DOOR_PIDS_LIMIT))
    assert pair(argv, "--memory", runtime.DOOR_MEMORY_LIMIT)
    assert pair(argv, "--restart", "no")
    assert pair(argv, "--label", f"{LABEL_DOOR}=echo")
    assert pair(argv, "--label", f"{LABEL_OWNER}={paths.arena_owner()}")
    assert not any(a.startswith(f"{LABEL_ID}=") for a in argv)  # never listed as an agent
    assert pair(argv, "-e", f"DOOR_TARGET={name}:8080")
    assert pair(argv, "-e", "DOOR_ALLOW=[]")  # echo declares no OPENAI_* key
    assert "--add-host" not in argv
    i = argv.index("--entrypoint")
    assert argv[i : i + 5] == ["--entrypoint", "python3", runtime.DOOR_IMAGE, "-I", "-c"]
    assert "@sha256:" in runtime.DOOR_IMAGE
    assert argv[-1] == open(runtime.door_program.__file__, encoding="utf-8").read()
    connect = ["docker", "network", "connect", "--alias", "hb-door", name, f"{name}_door"]
    assert fake.argvs().index(connect) < fake.argvs().index(agent_run(fake)[0])


def _allow(fake):
    argv = door_run(fake)[0]
    (value,) = [a for a in argv if a.startswith("DOOR_ALLOW=")]
    return json.loads(value.split("=", 1)[1]), argv


def _model_agent(egress=None):
    data = yaml.safe_load(ECHO_YAML.read_text())
    data["runtime"]["env"] = {"required": ["OPENAI_API_KEY"], "optional": ["OPENAI_BASE_URL"]}
    if egress:
        data["runtime"]["egress"] = egress
    return parse_manifest(data)


def test_the_door_lets_the_model_and_the_declared_hosts_through(fake, tmp_path):
    fake.containers = [container()]
    start(_model_agent(["files.example.com:8443"]), tmp_path, {"OPENAI_API_KEY": SECRET})
    allow, argv = _allow(fake)
    assert allow == [
        {"host": "api.openai.com", "port": 443, "private": True},
        {"host": "files.example.com", "port": 8443, "private": False},
    ]
    assert "--add-host" not in argv
    _no_secret_in_argv(fake)


def test_a_model_on_this_machine_is_let_through_at_its_port_only(fake, tmp_path):
    fake.containers = [container()]
    env = {"OPENAI_API_KEY": SECRET, "OPENAI_BASE_URL": "http://host.docker.internal:11434/v1"}
    start(_model_agent(), tmp_path, env)
    allow, argv = _allow(fake)
    assert allow == [{"host": "host.docker.internal", "port": 11434, "private": True}]
    assert pair(argv, "--add-host", "host.docker.internal:host-gateway")  # for Linux


def test_an_unreadable_model_url_stops_the_start_before_docker(fake, tmp_path):
    env = {"OPENAI_API_KEY": SECRET, "OPENAI_BASE_URL": "ftp://user:pw@llm.example.com"}
    with pytest.raises(DockerError) as e:
        start(_model_agent(), tmp_path, env)
    assert "cannot start echo: OPENAI_BASE_URL must be an http(s) URL" in str(e.value)
    assert "pw" not in str(e.value).replace("http(s)", "")
    assert fake.calls == []
    assert not run_env_file("echo").exists()


def test_pull_door_image_only_when_missing(fake):
    runtime.pull_door_image()
    assert fake.argvs() == [["docker", "image", "inspect", runtime.DOOR_IMAGE]]
    fake.calls.clear()
    fake.on(lambda a: a[:2] == ["image", "inspect"], lambda a: _cp(a, 1))
    runtime.pull_door_image()
    assert fake.argvs()[-1] == ["docker", "pull", runtime.DOOR_IMAGE]
    assert fake.calls[-1][3] is False  # streamed to the terminal


def test_a_failed_start_leaves_nothing_behind(fake, echo, tmp_path):
    fake.on(
        lambda a: a[:1] == ["run"] and f"{LABEL_DOOR}=" in a,
        lambda a: _cp(a, 1, "", "port taken"),
    )
    with pytest.raises(DockerError, match="port taken"):
        start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    name = resource_name("echo")
    tail = fake.argvs()[-4:]
    assert tail == [
        ["docker", "rm", "-f", "-v", name],
        door_stop(name),
        ["docker", "network", "rm", name],
        outside_rm(name),
    ]
    assert not run_env_file("echo").exists()


def test_start_not_published_cleans_up(fake, echo, tmp_path):
    fake.containers = [container()]
    fake.door_port = None  # the door got no port
    fake.on(lambda a: a[:1] == ["logs"], lambda a: _cp(a, 0, "boot failed: bad key\n", ""))
    with pytest.raises(DockerError) as e:
        start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    assert "can't be reached from this machine" in str(e.value)
    assert "boot failed: bad key" in str(e.value)
    name = resource_name("echo")
    rm_calls = [c for c in fake.find("rm", "-f", "-v", name)]
    assert len(rm_calls) == 2  # pre-start cleanup + stop
    assert fake.find("network", "rm", name) and fake.find("network", "rm", f"{name}_out")
    assert fake.argvs()[-4:-3] == [door_stop(name)]
    assert not run_env_file("echo").exists()


def test_start_not_running_at_all_cleans_up(fake, echo, tmp_path):
    fake.containers = []
    with pytest.raises(DockerError, match="can't be reached"):
        start(echo, tmp_path, {})
    assert fake.find("network", "rm", resource_name("echo"))


def test_stop_image(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {"ECHO_PREFIX": "x"})
    assert run_env_file("echo").exists()
    fake.calls.clear()
    stop("echo", "image")
    name = resource_name("echo")
    assert fake.argvs() == [
        door_stop(name),
        ["docker", "rm", "-f", "-v", name],
        ["docker", "network", "rm", name],
        outside_rm(name),
    ]
    assert not run_env_file("echo").exists()


# ── compose agents ──


@pytest.fixture
def host_env(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-host-secret")
    monkeypatch.setenv("HB_API_KEY", "hb-host-secret")
    monkeypatch.setenv("HUMANBOUND_TOKEN", "hb-host-token")
    monkeypatch.setenv("COMPOSE_BAKE", "true")
    monkeypatch.setenv("BUILDKIT_PROGRESS", "plain")
    monkeypatch.setenv("https_proxy", "http://proxy:3128")
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-should-not-leak")


def test_start_compose_agent(fake, compose_agent, host_env, arena_home):
    m, agent_dir = compose_agent
    fake.containers = [container("stack", kind="compose")]
    agent = start(m, agent_dir, {"OPENAI_API_KEY": SECRET, "UNDECLARED": "nope"})
    assert agent.kind == "compose" and agent.host_port == 49153

    override = yaml.safe_load((agent_dir / OVERRIDE_FILE).read_text())
    services = override["services"]
    assert set(services) == {"agent", "db"}
    for spec in services.values():
        assert spec["cap_drop"] == ["ALL"]
        assert spec["security_opt"] == ["no-new-privileges:true"]
    target = services["agent"]
    assert target["labels"] == {
        LABEL_ID: "stack",
        LABEL_VERSION: "0.1.0",
        LABEL_KIND: "compose",
        LABEL_PORT: "8080",
        LABEL_SERVICE: "agent",
        LABEL_OWNER: paths.arena_owner(),
        LABEL_DOOR: "",
    }
    # every service carries the owner (so `down` scoping and cleanup can find it), but only
    # the talked-to one has arena id labels: sidecars get them explicitly empty, so labels
    # baked into their images can't make them look like agents
    assert services["db"]["labels"] == {
        LABEL_ID: "",
        LABEL_VERSION: "",
        LABEL_KIND: "",
        LABEL_PORT: "",
        LABEL_SERVICE: "",
        LABEL_OWNER: paths.arena_owner(),
        LABEL_DOOR: "",
    }
    # names only; the unset optional ECHO_PREFIX is not listed (it would null a base default)
    proxy = [f"{k}={v}" for k, v in runtime.egress.proxy_env(["agent", "db"]).items()]
    assert target["environment"] == ["OPENAI_API_KEY", *proxy]
    assert services["db"]["environment"] == proxy  # every service is pointed at the door
    # no service publishes a port (their networks can't): the door is the way in
    assert "ports" not in target and "ports" not in services["db"]
    hidden = {runtime.NO_BRIDGE_ADDRESS: "true"}
    assert override["networks"] == {"default": {"internal": True, "driver_opts": hidden}}

    ups = [c for c in fake.calls if "up" in c[0]]
    assert [c[0][c[0].index("up") :] for c in ups] == [
        ["up", "--no-start", "--force-recreate", "--renew-anon-volumes"],
        ["up", "-d"],
    ]
    # down (from scratch, keeping named volumes), containers and networks, the door, start
    name = resource_name("stack")
    order = [a for a in fake.argvs() if "down" in a or "up" in a or a[1:2] == ["run"]]
    assert ["down" in order[0], "--no-start" in order[1], order[2][1], order[3][-2:]] == [
        True,
        True,
        "run",
        ["up", "-d"],
    ]
    assert "-v" not in order[0]
    door_argv = door_run(fake)[0]
    assert pair(door_argv, "-e", "DOOR_TARGET=agent:8080")
    assert pair(door_argv, "-e", 'DOOR_ALLOW=[{"host":"api.openai.com","port":443,"private":true}]')
    connect = ["docker", "network", "connect", "--alias", "hb-door", f"{name}_default"]
    assert [*connect, f"{name}_door"] in fake.argvs()
    up = ups[-1]
    argv, env, _, _ = up
    assert argv[:4] == ["docker", "compose", "-p", resource_name("stack")]
    assert str(agent_dir / "docker-compose.yml") in argv
    assert str(agent_dir / OVERRIDE_FILE) in argv
    assert "--env-file" not in argv
    for c in fake.calls:
        if c[0][1] == "compose":
            assert "--env-file" not in c[0]
    _no_secret_in_argv(fake)

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["OPENAI_API_KEY"] == SECRET
    assert "COMPOSE_BAKE" not in env
    assert env["BUILDKIT_PROGRESS"] == "plain"
    assert env["https_proxy"] == "http://proxy:3128"
    for leaked in ("AWS_SECRET_ACCESS_KEY", "HB_API_KEY", "HUMANBOUND_TOKEN", "UNDECLARED"):
        assert leaked not in env
    assert run_env_file("stack").read_text() == f"OPENAI_API_KEY={SECRET}\n"


def test_every_declared_compose_network_gets_no_route_out(fake, compose_agent):
    m, agent_dir = compose_agent
    doc = copy.deepcopy(COMPOSE)
    doc["networks"] = {"front": None, "back": {"internal": False, "driver": "bridge"}}
    doc["services"]["agent"]["networks"] = ["front", "back"]
    doc["services"]["db"]["networks"] = ["back"]
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(doc))
    fake.containers = [container("stack", kind="compose")]
    fake.on(
        lambda a: a[:2] == ["network", "create"] and "-o" in a,
        lambda a: _cp(a, 1, "", "unknown option"),
    )
    agent = start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert agent.gateway_reachable
    override = yaml.safe_load((agent_dir / OVERRIDE_FILE).read_text())
    assert override["networks"] == {
        "default": {"internal": True},
        "front": {"internal": True},
        "back": {"internal": True},
    }


def test_the_door_joins_every_network_of_the_project(fake, compose_agent):
    m, agent_dir = compose_agent
    fake.containers = [container("stack", kind="compose")]
    fake.on(lambda a: a[:2] == ["network", "ls"], lambda a: _cp(a, 0, "p_front\np_back\n"))
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    joined = [c[0][-2] for c in fake.find("network", "connect")]
    assert joined == ["p_front", "p_back"]


def test_a_compose_service_may_not_take_the_doors_name(fake, compose_agent):
    m, agent_dir = compose_agent
    doc = copy.deepcopy(COMPOSE)
    doc["services"]["hb-door"] = {"image": "ghcr.io/example/x:1"}
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(doc))
    with pytest.raises(DockerError, match="may not be called hb-door"):
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert not fake.find("compose")


def test_subprocess_env_allowlist(monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("DOCKER_HOST", "unix:///x.sock")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    for name in ("COMPOSE_PROFILES", "COMPOSE_FILE", "COMPOSE_ENV_FILES", "COMPOSE_PROJECT_NAME"):
        monkeypatch.setenv(name, "attacker-chosen")
    monkeypatch.setenv("COMPOSE_HTTP_TIMEOUT", "120")
    monkeypatch.setenv("COMPOSE_PARALLEL_LIMIT", "4")
    monkeypatch.setenv("BUILDKIT_PROGRESS", "plain")
    monkeypatch.setenv("BUILDKIT_HOST", "tcp://elsewhere:1234")
    env = runtime._subprocess_env({"K": "v"})
    assert env["PATH"] == "/bin" and env["DOCKER_HOST"] == "unix:///x.sock"
    assert env["K"] == "v"
    assert env["COMPOSE_HTTP_TIMEOUT"] == "120" and env["COMPOSE_PARALLEL_LIMIT"] == "4"
    assert env["BUILDKIT_PROGRESS"] == "plain"
    for name in (
        "GITHUB_TOKEN",
        "COMPOSE_PROFILES",
        "COMPOSE_FILE",
        "COMPOSE_ENV_FILES",
        "COMPOSE_PROJECT_NAME",
        "BUILDKIT_HOST",
    ):
        assert name not in env


def test_unsafe_compose_refused_before_any_docker_call(fake, compose_agent):
    m, agent_dir = compose_agent
    bad = copy.deepcopy(COMPOSE)
    bad["services"]["agent"]["privileged"] = True
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(bad))
    with pytest.raises(DockerError, match="privileged"):
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    with pytest.raises(DockerError, match="privileged"):
        runtime.pull(m, agent_dir)
    assert fake.calls == []
    assert not run_env_file("stack").exists()
    assert not (agent_dir / OVERRIDE_FILE).exists()


def test_pull_compose_only_pulls(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    runtime.pull(m, agent_dir)
    compose_calls = [c for c in fake.calls if c[0][1] == "compose"]
    assert [argv[-1] for argv, _, _, _ in compose_calls] == ["pull"]
    for argv, env, _, _ in compose_calls:
        assert "--env-file" not in argv
        assert "build" not in argv and "--ignore-buildable" not in argv
        assert "AWS_SECRET_ACCESS_KEY" not in env


def test_declared_but_unset_names_never_come_from_the_host(fake, compose_agent, monkeypatch):
    # A manifest declaring e.g. SSL_CERT_FILE must not get the host's value via
    # ${SSL_CERT_FILE}.
    m, agent_dir = compose_agent
    m.runtime.env.optional.append("SSL_CERT_FILE")
    monkeypatch.setenv("SSL_CERT_FILE", "/host/secret/path")
    fake.containers = [container("stack", kind="compose")]
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    composed = [c for c in fake.calls if c[0][1] == "compose"]
    assert composed
    for _, env, _, _ in composed:
        assert "SSL_CERT_FILE" not in env
    fake.calls.clear()
    runtime.pull(m, agent_dir)
    for _, env, _, _ in fake.calls:
        assert "SSL_CERT_FILE" not in env


def test_pull_image(fake, echo, tmp_path):
    runtime.pull(echo, tmp_path)
    assert fake.argvs() == [["docker", "pull", "humanbound-arena-echo:test"]]


# ── images the catalog index publishes with a digest ──

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
ECHO_REF = "humanbound-arena-echo:test"
AGENT_REF = "ghcr.io/example/arena-stack:0.1.0"


def _record(agent_dir, images, index="/x/index.json"):
    """What catalog.fetch_manifest writes: the index location and the entry's images."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    pins = [{"ref": ref, "digest": digest} for ref, digest in images]
    (agent_dir / "installed.json").write_text(json.dumps({"index": index, "images": pins}))


class LocalImages:
    """A fake local image store behind FakeDocker: tag -> RepoDigests."""

    def __init__(self, fake, images=None):
        self.images = dict(images or {})
        fake.on(lambda a: a[:2] == ["image", "inspect"], self._inspect)
        fake.on(lambda a: a[:1] == ["pull"] and "@" in a[1], self._pull)
        fake.on(lambda a: a[:1] == ["tag"], self._tag)

    def _inspect(self, args):
        ref = args[-1]
        if ref not in self.images:
            return _cp(["docker", *args], 1, "", f"Error: No such image: {ref}")
        return _cp(["docker", *args], 0, json.dumps(self.images[ref]) + "\n")

    def _pull(self, args):
        self.images[args[1]] = [args[1]]
        return _cp(["docker", *args], 0)

    def _tag(self, args):
        self.images[args[2]] = self.images[args[1]]
        return _cp(["docker", *args], 0)


def test_pull_image_by_digest_when_the_tag_is_missing(fake, echo, tmp_path):
    _record(tmp_path, [(ECHO_REF, D1)])
    local = LocalImages(fake)
    runtime.pull(echo, tmp_path)
    by_digest = "humanbound-arena-echo@" + D1
    assert ["docker", "pull", by_digest] in fake.argvs()
    assert ["docker", "tag", by_digest, ECHO_REF] in fake.argvs()
    assert ["docker", "pull", ECHO_REF] not in fake.argvs()  # never by tag
    assert local.images[ECHO_REF] == [by_digest]
    (pull,) = fake.find("pull")
    assert pull[3] is False  # streamed to the terminal


def test_pull_image_with_a_matching_local_tag_pulls_nothing(fake, echo, tmp_path):
    _record(tmp_path, [(ECHO_REF, D1)])
    LocalImages(fake, {ECHO_REF: ["humanbound-arena-echo@" + D1]})
    runtime.pull(echo, tmp_path)
    assert not fake.find("pull") and not fake.find("tag")


@pytest.mark.parametrize(
    "found, shown",
    [
        (["humanbound-arena-echo@" + D2], "humanbound-arena-echo@" + D2),
        ([], "locally built, no registry digest"),
        (None, "locally built, no registry digest"),  # "RepoDigests": null
        (["localhost:5000/elsewhere@" + D1], "localhost:5000/elsewhere@" + D1),
    ],
)
def test_a_stale_or_local_tag_is_refused_with_the_fix(fake, echo, tmp_path, found, shown):
    _record(tmp_path, [(ECHO_REF, D1)])
    LocalImages(fake, {ECHO_REF: found})
    for action in (lambda: runtime.pull(echo, tmp_path), lambda: start(echo, tmp_path, {})):
        with pytest.raises(DockerError) as exc:
            action()
        message = str(exc.value)
        assert ECHO_REF in message
        assert f"expected {D1}" in message
        assert shown in message
        assert f"docker rmi {ECHO_REF}" in message
        assert "HB_ARENA_INDEX=<checkout>" in message
    assert not fake.find("pull") and not fake.find("run") and not fake.find("tag")
    assert not run_env_file("echo").exists()


def test_docker_hub_short_names_match(fake, tmp_path):
    data = yaml.safe_load(ECHO_YAML.read_text())
    data["source"] = {"image": "docker.io/library/postgres:16"}
    m = parse_manifest(data)
    _record(tmp_path, [("docker.io/library/postgres:16", D1)])
    LocalImages(fake, {"docker.io/library/postgres:16": ["postgres@" + D1]})
    runtime.pull(m, tmp_path)
    assert not fake.find("pull")


def test_no_digests_in_the_index_keeps_tag_behaviour(fake, echo, tmp_path):
    _record(tmp_path, [])
    LocalImages(fake, {ECHO_REF: []})  # a local build: fine without index digests
    runtime.pull(echo, tmp_path)
    assert fake.argvs() == [["docker", "pull", ECHO_REF]]
    fake.calls.clear()
    fake.containers = [container()]
    start(echo, tmp_path, {})
    assert not fake.find("image", "inspect")
    assert fake.find("run")


def test_pins_for_images_the_agent_does_not_use_are_ignored(fake, echo, tmp_path):
    _record(tmp_path, [("ghcr.io/x/unrelated:1", D1)])
    LocalImages(fake)
    runtime.pull(echo, tmp_path)
    assert fake.argvs() == [["docker", "pull", ECHO_REF]]


def test_pull_by_digest_failure_is_a_docker_error(fake, echo, tmp_path):
    _record(tmp_path, [(ECHO_REF, D1)])
    LocalImages(fake)
    fake.on(lambda a: a[:1] == ["pull"], lambda a: _cp(["docker", *a], 1))
    with pytest.raises(DockerError, match="docker pull .* failed"):
        runtime.pull(echo, tmp_path)
    assert not fake.find("tag")


def test_start_image_agent_pulls_a_missing_pinned_image_by_digest(fake, echo, tmp_path):
    _record(tmp_path, [(ECHO_REF, D1)])
    LocalImages(fake)
    fake.containers = [container()]
    start(echo, tmp_path, {})
    argvs = fake.argvs()
    by_digest = "humanbound-arena-echo@" + D1
    assert argvs.index(["docker", "pull", by_digest]) < argvs.index(
        ["docker", "tag", by_digest, ECHO_REF]
    )
    assert agent_run(fake)[0][-1] == ECHO_REF


def test_pull_compose_pins_some_services(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    _record(agent_dir, [(AGENT_REF, D1)])
    LocalImages(fake)
    runtime.pull(m, agent_dir)
    by_digest = "ghcr.io/example/arena-stack@" + D1
    assert ["docker", "pull", by_digest] in fake.argvs()
    assert ["docker", "tag", by_digest, AGENT_REF] in fake.argvs()
    (compose_pull,) = [c[0] for c in fake.calls if c[0][1] == "compose"]
    assert compose_pull[-2:] == ["pull", "db"]  # only the service the index doesn't pin


def test_pull_compose_every_service_pinned_skips_compose_pull(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    _record(agent_dir, [(AGENT_REF, D1), ("postgres:16", D2)])
    LocalImages(fake, {"postgres:16": ["postgres@" + D2]})
    runtime.pull(m, agent_dir)
    assert not [c for c in fake.calls if c[0][1] == "compose"]
    assert ["docker", "pull", "ghcr.io/example/arena-stack@" + D1] in fake.argvs()
    assert ["docker", "pull", "postgres@" + D2] not in fake.argvs()


def test_compose_mismatch_is_refused_before_anything_runs(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    _record(agent_dir, [(AGENT_REF, D1), ("postgres:16", D2)])
    LocalImages(fake, {AGENT_REF: ["ghcr.io/example/arena-stack@" + D1], "postgres:16": []})
    with pytest.raises(DockerError, match="postgres:16.*locally built, no registry digest"):
        runtime.pull(m, agent_dir)
    with pytest.raises(DockerError, match="docker rmi postgres:16"):
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert not [c for c in fake.calls if c[0][1] == "compose"]
    assert not run_env_file("stack").exists()
    assert not (agent_dir / OVERRIDE_FILE).exists()


def test_start_compose_checks_pinned_images_first(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    _record(agent_dir, [(AGENT_REF, D1)])
    LocalImages(fake)
    fake.containers = [container("stack", kind="compose")]
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    argvs = fake.argvs()
    tag = argvs.index(["docker", "tag", "ghcr.io/example/arena-stack@" + D1, AGENT_REF])
    up = next(i for i, argv in enumerate(argvs) if "up" in argv)
    assert tag < up


def test_unsafe_compose_is_refused_before_the_digest_check(fake, compose_agent):
    m, agent_dir = compose_agent
    _record(agent_dir, [(AGENT_REF, D1)])
    bad = copy.deepcopy(COMPOSE)
    bad["services"]["agent"]["privileged"] = True
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(bad))
    with pytest.raises(DockerError, match="unsafe"):
        runtime.pull(m, agent_dir)
    assert fake.calls == []


def _files(agent_dir, override=True):
    files = ["-f", str(agent_dir / "docker-compose.yml")]
    if override:
        files += ["-f", str(agent_dir / OVERRIDE_FILE)]
    return [*files, "--project-directory", str(agent_dir)]


def test_stop_compose(fake, host_env, compose_agent):
    _, agent_dir = compose_agent
    (agent_dir / OVERRIDE_FILE).write_text("services: {}\n")
    stop("stack", "compose", agent_dir=agent_dir)
    name = resource_name("stack")
    assert [fake.argvs()[0], fake.argvs()[2]] == [door_stop(name), outside_rm(name)]
    (_, (argv, env, _, _), _) = fake.calls
    assert argv == [
        "docker",
        "compose",
        "-p",
        resource_name("stack"),
        *_files(agent_dir),
        "down",
        "-v",
        "--remove-orphans",
    ]
    assert "PATH" in env and "AWS_SECRET_ACCESS_KEY" not in env


def test_stop_compose_without_an_override(fake, compose_agent):
    _, agent_dir = compose_agent
    stop("stack", "compose", agent_dir=agent_dir)
    assert fake.argvs()[1][4:8] == _files(agent_dir, override=False)


def _project_rules(fake, name, *, containers=("c1", "c2"), networks=("n1",), volumes=("v1",)):
    label = f"label=com.docker.compose.project={name}"
    fake.on(lambda a: a[:1] == ["ps"] and label in a, lambda a: _cp(a, 0, "\n".join(containers)))
    fake.on(
        lambda a: a[:2] == ["network", "ls"] and label in a,
        lambda a: _cp(a, 0, "\n".join(networks)),
    )
    fake.on(
        lambda a: a[:2] == ["volume", "ls"] and label in a,
        lambda a: _cp(a, 0, "\n".join(volumes)),
    )


@pytest.mark.parametrize("have_dir", [False, True])
def test_stop_compose_without_its_compose_file_uses_labels(fake, tmp_path, have_dir):
    """The manifest (and compose file) is gone: never run compose, which could load a
    docker-compose.yml from the current directory; remove the project by its label."""
    name = resource_name("stack")
    _project_rules(fake, name)
    stop("stack", "compose", agent_dir=tmp_path if have_dir else None)
    label = f"label=com.docker.compose.project={name}"
    assert not fake.find("compose")
    assert fake.argvs() == [
        door_stop(name),
        ["docker", "ps", "-a", "-q", "--filter", label],
        ["docker", "rm", "-f", "-v", "c1", "c2"],
        ["docker", "network", "ls", "-q", "--filter", label],
        ["docker", "network", "rm", "n1"],
        ["docker", "volume", "ls", "-q", "--filter", label],
        ["docker", "volume", "rm", "-f", "v1"],
        outside_rm(name),
    ]


def test_stop_compose_by_labels_skips_empty_lists(fake):
    _project_rules(fake, resource_name("stack"), containers=(), networks=(), volumes=())
    stop("stack", "compose")
    assert [a[1:3] for a in fake.argvs()[1:-1]] == [
        ["ps", "-a"],
        ["network", "ls"],
        ["volume", "ls"],
    ]


def test_stop_compose_by_labels_reports_a_failed_listing(fake):
    fake.on(lambda a: a[:1] == ["ps"], lambda a: _cp(a, 1, stderr="daemon down"))
    with pytest.raises(DockerError, match="daemon down"):
        stop("stack", "compose")


def test_no_compose_call_can_read_the_current_directory(fake, compose_agent, host_env, tmp_path):
    """Every `docker compose` hb runs names its files and project directory explicitly."""
    m, agent_dir = compose_agent
    fake.containers = [container("stack", kind="compose")]
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    runtime.pull(m, agent_dir)
    runtime.logs("stack", "compose", agent_dir=agent_dir)
    runtime.last_logs("stack", "compose", agent_dir=agent_dir)
    runtime.remove_images(m, agent_dir)
    stop("stack", "compose", agent_dir=agent_dir)
    _project_rules(fake, resource_name("stack"))
    stop("stack", "compose")
    stop("stack", "compose", owner="ffffffffffff", name="arena-ffffffffffff-stack")
    runtime.logs("stack", "compose")
    runtime.last_logs("stack", "compose")
    compose_calls = fake.find("compose")
    assert compose_calls
    for argv, _, _, _ in compose_calls:
        assert "-f" in argv and "--project-directory" in argv, argv
        assert argv[argv.index("--project-directory") + 1] == str(agent_dir)


def test_start_compose_not_published_cleans_up(fake, compose_agent):
    m, agent_dir = compose_agent
    fake.containers = [container("stack", kind="compose")]
    fake.door_port = None
    with pytest.raises(DockerError, match="can't be reached"):
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert [c for c in fake.calls if c[0][1] == "compose" and "down" in c[0]]
    assert not run_env_file("stack").exists()


def test_start_compose_up_failure_cleans_up(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    fake.on(
        lambda a: a[:1] == ["compose"] and "up" in a,
        lambda a: _cp(a, 1, stderr="pull access denied"),
    )
    with pytest.raises(DockerError, match="pull access denied"):
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert [c for c in fake.calls if c[0][1] == "compose" and "down" in c[0]]
    assert not run_env_file("stack").exists()


# ── reset ──


def test_reset_keeps_env_image(fake, echo, tmp_path, monkeypatch):
    healthy = []
    monkeypatch.setattr(
        runtime, "wait_healthy", lambda agent, health: healthy.append((agent, health))
    )
    fake.containers = [container()]
    start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    fake.calls.clear()
    agent = reset(echo, tmp_path)
    assert agent.host_port == 49153
    assert run_env_file("echo").read_text() == f"ECHO_PREFIX={SECRET}\n"
    assert healthy == [(agent, echo.runtime.health)]
    assert fake.find("run")
    _no_secret_in_argv(fake)


def test_reset_keeps_env_compose(fake, compose_agent, host_env, monkeypatch):
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    m, agent_dir = compose_agent
    fake.containers = [container("stack", kind="compose")]
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    fake.calls.clear()
    reset(m, agent_dir)
    ups = [c for c in fake.calls if "up" in c[0]]
    assert len(ups) == 2 and all(up[1]["OPENAI_API_KEY"] == SECRET for up in ups)
    stopping = [c for c in fake.calls if c[0][1:2] != ["ps"] and c[0][1:2] != ["inspect"]]
    assert stopping[0][0] == door_stop(resource_name("stack"))
    assert stopping[1][0][1:] == [
        "compose",
        "-p",
        resource_name("stack"),
        *_files(agent_dir),
        "down",
        "-v",
        "--remove-orphans",
    ]


def test_reset_refuses_when_saved_keys_unreadable(fake, echo, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    env_file = run_env_file("echo")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_bytes(b"ECHO_PREFIX=\xff\xfe\n")
    with pytest.raises(
        DockerError, match=r"cannot read the saved keys for echo.*hb arena run echo"
    ):
        reset(echo, tmp_path)
    assert fake.calls == []  # nothing stopped, nothing restarted with missing keys
    assert env_file.exists()


def test_reset_without_saved_keys_refuses_when_keys_are_required(fake, compose_agent, monkeypatch):
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    m, agent_dir = compose_agent  # requires OPENAI_API_KEY
    assert not run_env_file("stack").exists()
    with pytest.raises(DockerError, match="no saved keys for stack → hb arena run stack again"):
        reset(m, agent_dir)
    assert fake.calls == []  # nothing stopped, nothing restarted without keys


def test_reset_without_saved_keys_starts_with_none(fake, echo, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    fake.containers = [container()]
    assert not run_env_file("echo").exists()
    reset(echo, tmp_path)
    assert fake.find("run")
    assert run_env_file("echo").read_text() == ""


def test_start_image_run_failure_cleans_up(fake, echo, tmp_path):
    fake.on(lambda a: a[:1] == ["run"], lambda a: _cp(a, 125, stderr="port is already allocated"))
    with pytest.raises(DockerError, match="port is already allocated"):
        start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    assert not run_env_file("echo").exists()
    assert fake.find("network", "rm", resource_name("echo"))


# ── list_running ──


def test_list_running_parses_and_skips(fake):
    no_label = container("x")
    no_label["Id"] = "c-no-label"
    no_label["Config"]["Labels"] = {"other": "1"}
    fake.containers = [
        container("echo"),
        door("echo"),
        container("stack", port=9000, kind="compose"),
        door("stack", host_port="50000"),
        no_label,
        container("unreachable"),
    ]
    agents = list_running()
    assert agents == [
        RunningAgent("echo", "0.1.0", "image", 49153),
        RunningAgent("stack", "0.1.0", "compose", 50000),
        RunningAgent("unreachable", "0.1.0", "image", None),
    ]
    assert all(c[2] == LIST_TIMEOUT_S for c in fake.calls)
    assert [c[0][1] for c in fake.calls] == ["ps", "inspect", "ps", "inspect"]


def test_list_running_without_agents_never_looks_for_doors(fake):
    fake.containers = [door("echo")]
    assert list_running() == []
    assert [c[0][1] for c in fake.calls] == ["ps"]


def test_list_running_finds_each_agent_behind_its_own_door(fake):
    other = "ffffffffffff"
    theirs = container("echo")
    theirs["Id"] = "c-theirs"
    theirs["Config"]["Labels"][LABEL_OWNER] = other
    fake.containers = [
        container("echo"),
        door("echo", host_port="50001"),
        container("stack", kind="compose"),
        door("stack", host_port="50002"),
        container("doorless"),
        container("stuck"),
        door("stuck", host_port=None),
        container("odd"),
        door("odd", host_port="not-a-port"),
        theirs,
        door("echo", host_port="50009", owner=other),
    ]
    agents = {a.id: a for a in list_running()}
    assert {k: a.host_port for k, a in agents.items()} == {
        "echo": 50001,  # never the other owner's door
        "stack": 50002,
        "doorless": None,
        "stuck": None,
        "odd": None,
    }
    everyone = list_running(any_owner=True)
    assert sorted((a.owner, a.host_port) for a in everyone if a.id == "echo") == [
        (paths.arena_owner(), 50001),
        (other, 50009),
    ]
    # doors are looked up once, with a time limit
    doors = [c for c in fake.calls if f"label={LABEL_DOOR}" in c[0]]
    assert len(doors) == 2 and all(c[2] == LIST_TIMEOUT_S for c in doors)


def test_a_port_the_agent_publishes_itself_is_not_its_way_in(fake):
    """Only a door counts (a container from an hb before network blocking has none)."""
    fake.containers = [container("echo", published="50001")]
    (agent,) = list_running()
    assert agent.host_port is None


def test_a_door_is_never_listed_as_an_agent(fake):
    fake.containers = [door("echo")]
    assert list_running(include_stopped=True, any_owner=True) == []


def test_list_running_include_stopped(fake):
    fake.containers = [container("echo")]
    assert list_running(include_stopped=True) == [RunningAgent("echo", "0.1.0", "image", None)]
    assert fake.calls[0][0][:4] == ["docker", "ps", "-a", "-q"]
    fake.calls.clear()
    list_running()
    assert "-a" not in fake.calls[0][0]


def test_list_running_empty_skips_inspect(fake):
    assert list_running() == []
    assert len(fake.calls) == 1


def test_list_running_partial_inspect_failure(fake):
    fake.containers = [container("echo")]
    fake.on(
        lambda a: a[:1] == ["inspect"],
        lambda a: _cp(a, 1, json.dumps([container("echo")]), "Error: No such object: gone"),
    )
    fake.on(lambda a: a[:1] == ["ps"], lambda a: _cp(a, 0, "c-echo-49153\ngone\n"))
    assert [a.id for a in list_running()] == ["echo"]


@pytest.mark.parametrize("stdout", ["", "not json", '{"a": 1}', "[1, 2]"])
def test_list_running_bad_inspect_output(fake, stdout):
    fake.containers = [container("echo")]
    fake.on(lambda a: a[:1] == ["inspect"], lambda a: _cp(a, 1, stdout))
    assert list_running() == []


def test_list_running_timeout(fake):
    fake.on(lambda a: a[:1] == ["ps"], subprocess.TimeoutExpired(["docker", "ps"], LIST_TIMEOUT_S))
    with pytest.raises(DockerError, match="did not respond within 15s"):
        list_running()


# ── wait_healthy ──


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


AGENT = RunningAgent("echo", "0.1.0", "image", 49153)


def test_wait_healthy_retries_until_ok():
    clock = Clock()
    urls = []
    responses = [
        httpx.ConnectError("refused"),
        httpx.Response(503),
        httpx.Response(200),
    ]

    def get(url, timeout):
        urls.append(url)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    wait_healthy(
        AGENT, Health(path="/health", timeout_s=30), get=get, sleep=clock.sleep, clock=clock
    )
    assert urls == ["http://127.0.0.1:49153/health"] * 3
    assert clock.now == 2


def test_wait_healthy_timeout():
    clock = Clock()

    def get(url, timeout):
        raise httpx.ConnectError("refused")

    with pytest.raises(HealthTimeout, match="within 5s"):
        wait_healthy(AGENT, Health(timeout_s=5), get=get, sleep=clock.sleep, clock=clock)
    assert clock.now == 5


# ── logs ──


def test_last_logs_combines_streams(fake):
    fake.on(lambda a: a[:1] == ["logs"], lambda a: _cp(a, 0, "out\n", "err\n"))
    text = runtime.last_logs("echo", "image", 20)
    assert "out" in text and "err" in text
    (argv, _, _, capture) = fake.calls[0]
    assert argv == ["docker", "logs", "--tail", "20", resource_name("echo")] and capture


def test_last_logs_never_raises(fake):
    fake.on(lambda a: True, FileNotFoundError("docker"))
    assert runtime.last_logs("echo", "image") == ""


def test_logs_compose_uses_allowlisted_env(fake, host_env, compose_agent):
    _, agent_dir = compose_agent
    runtime.logs("stack", "compose", follow=True, tail=10, agent_dir=agent_dir)
    ((argv, env, _, capture),) = fake.calls
    assert argv == [
        "docker",
        "compose",
        "-p",
        resource_name("stack"),
        *_files(agent_dir, override=False),
        "logs",
        "--tail",
        "10",
        "-f",
    ]
    assert capture is False and "AWS_SECRET_ACCESS_KEY" not in env


def _agent_container_rule(fake, ids="c-agent"):
    fake.on(
        lambda a: a[:1] == ["ps"] and f"label={LABEL_ID}=stack" in a,
        lambda a: _cp(a, 0, ids),
    )


def test_logs_compose_without_its_compose_file_follows_the_agent_container(fake):
    _agent_container_rule(fake)
    runtime.logs("stack", "compose", follow=True, tail=10)
    assert not fake.find("compose")
    ps, logs = fake.argvs()
    project = f"label=com.docker.compose.project={resource_name('stack')}"
    assert ps == [
        "docker",
        "ps",
        "-a",
        "-q",
        "--filter",
        project,
        "--filter",
        f"label={LABEL_ID}=stack",
    ]
    assert logs == ["docker", "logs", "--tail", "10", "-f", "c-agent"]


def test_logs_compose_without_a_container(fake):
    _agent_container_rule(fake, ids="")
    with pytest.raises(DockerError, match="no container"):
        runtime.logs("stack", "compose")


def test_last_logs_compose(fake, compose_agent):
    _, agent_dir = compose_agent
    fake.on(lambda a: a[:1] == ["compose"], lambda a: _cp(a, 0, "svc | boom\n", ""))
    assert runtime.last_logs("stack", "compose", 5, agent_dir=agent_dir) == "svc | boom\n"
    ((argv, _, timeout, _),) = fake.calls
    assert argv[4:8] == _files(agent_dir, override=False)
    assert argv[8:] == ["logs", "--no-color", "--tail", "5"]
    assert timeout == LIST_TIMEOUT_S


def test_last_logs_compose_without_its_compose_file(fake):
    _agent_container_rule(fake)
    fake.on(lambda a: a[:1] == ["logs"], lambda a: _cp(a, 0, "out\n", "err\n"))
    text = runtime.last_logs("stack", "compose", 5)
    assert not fake.find("compose")
    assert "out" in text and "err" in text
    assert fake.argvs()[-1] == ["docker", "logs", "--tail", "5", "c-agent"]


def test_remove_images(fake, echo, compose_agent, host_env):
    runtime.remove_images(echo, compose_agent[1])
    assert fake.find("rmi") and fake.find("rmi")[0][0] == [
        "docker",
        "rmi",
        "humanbound-arena-echo:test",
    ]
    fake.calls.clear()
    m, agent_dir = compose_agent
    runtime.remove_images(m, agent_dir)
    compose_calls = [c for c in fake.calls if c[0][1] == "compose"]
    ((argv, env, _, _),) = compose_calls
    assert argv == [
        "docker",
        "compose",
        "-p",
        resource_name("stack"),
        *_files(agent_dir, override=False),
        "down",
        "-v",
    ]
    assert "--rmi" not in argv
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # only the images of the agent's own compose services, one by one
    assert sorted(c[0][2] for c in fake.find("rmi")) == [
        "ghcr.io/example/arena-stack:0.1.0",
        "postgres:16",
    ]


def _ancestor_rules(fake, image, *, everyone, arena):
    """`docker ps -a -q --filter ancestor=image [--filter label=owner]` results."""

    def ps(args):
        if f"ancestor={image}" not in args:
            return _cp(args, 0, "")
        ids = arena if f"label={LABEL_OWNER}" in args else everyone
        return _cp(args, 0, "\n".join(ids))

    fake.on(lambda a: a[:1] == ["ps"] and any(x.startswith("ancestor=") for x in a), ps)


def test_remove_images_skips_an_image_used_by_other_containers(fake, echo, tmp_path):
    _ancestor_rules(fake, echo.source.image, everyone=["c1", "mine"], arena=["mine"])
    runtime.remove_images(echo, tmp_path)
    assert fake.find("rmi") == []


def test_remove_images_removes_an_image_only_arena_uses(fake, echo, tmp_path):
    _ancestor_rules(fake, echo.source.image, everyone=["mine"], arena=["mine"])
    runtime.remove_images(echo, tmp_path)
    assert [c[0] for c in fake.find("rmi")] == [["docker", "rmi", echo.source.image]]


def test_remove_images_compose_skips_shared_images(fake, compose_agent):
    m, agent_dir = compose_agent
    _ancestor_rules(fake, "postgres:16", everyone=["users-db"], arena=[])
    runtime.remove_images(m, agent_dir)
    assert [c[0][2] for c in fake.find("rmi")] == ["ghcr.io/example/arena-stack:0.1.0"]


def test_remove_images_when_the_check_fails_keeps_the_image(fake, echo, tmp_path):
    fake.on(lambda a: a[:1] == ["ps"], lambda a: _cp(a, 1, stderr="boom"))
    runtime.remove_images(echo, tmp_path)
    assert fake.find("rmi") == []


def test_remove_images_unsafe_compose_removes_nothing(fake, compose_agent):
    m, agent_dir = compose_agent
    bad = copy.deepcopy(COMPOSE)
    bad["services"]["agent"]["privileged"] = True
    (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(bad))
    runtime.remove_images(m, agent_dir)
    assert fake.find("rmi") == []


# ── owner scoping ──


def test_resource_name_includes_the_owner(arena_home):
    owner = paths.arena_owner()
    assert resource_name("echo") == f"arena-{owner}-echo"
    assert resource_name("echo", owner="0123456789ab") == "arena-0123456789ab-echo"
    assert resource_name("echo", owner="") == "arena-echo"  # pre-owner (legacy) resources


def test_resource_name_stays_within_63_chars(arena_home):
    long_a = "a" * 40 + "-one-" + "x" * 18
    long_b = "a" * 40 + "-two-" + "x" * 18
    assert len(long_a) == 63
    name_a, name_b = resource_name(long_a), resource_name(long_b)
    assert len(name_a) <= 63 and len(name_b) <= 63
    assert name_a != name_b  # a shared prefix does not collide
    assert name_a.startswith(f"arena-{paths.arena_owner()}-aaaa")
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*_[0-9a-f]{8}", name_a)  # ids never contain "_"
    assert resource_name(long_a) == name_a  # stable
    assert len(resource_name("b" * 44)) <= 63


def test_list_running_filters_by_owner(fake):
    other = container("theirs")
    other["Config"]["Labels"][LABEL_OWNER] = "ffffffffffff"
    legacy = container("legacy")
    del legacy["Config"]["Labels"][LABEL_OWNER]
    fake.containers = [container("echo"), other, legacy]
    agents = list_running()
    assert [a.id for a in agents] == ["echo"]
    assert agents[0].owner == paths.arena_owner()
    ps = fake.calls[0][0]
    assert f"label={LABEL_ID}" in ps
    assert f"label={LABEL_OWNER}={paths.arena_owner()}" in ps


def test_list_running_any_owner(fake):
    other = container("theirs")
    other["Config"]["Labels"][LABEL_OWNER] = "ffffffffffff"
    legacy = container("legacy")
    del legacy["Config"]["Labels"][LABEL_OWNER]
    fake.containers = [container("echo"), other, legacy]
    agents = list_running(include_stopped=True, any_owner=True)
    assert [(a.id, a.owner) for a in agents] == [
        ("echo", paths.arena_owner()),
        ("theirs", "ffffffffffff"),
        ("legacy", ""),
    ]
    ps = fake.calls[0][0]
    assert not any(a.startswith(f"label={LABEL_OWNER}") for a in ps)


def test_stop_another_owners_agent(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {"ECHO_PREFIX": "x"})
    fake.calls.clear()
    stop("echo", "image", owner="ffffffffffff")
    assert fake.argvs() == [
        door_stop("arena-ffffffffffff-echo"),
        ["docker", "rm", "-f", "-v", "arena-ffffffffffff-echo"],
        ["docker", "network", "rm", "arena-ffffffffffff-echo"],
        outside_rm("arena-ffffffffffff-echo"),
    ]
    assert run_env_file("echo").exists()  # ours: not touched
    fake.calls.clear()
    stop("legacy", "compose", owner="")
    assert not fake.find("compose")  # another owner's (or no) compose file: by label only
    assert "label=com.docker.compose.project=arena-legacy" in fake.argvs()[1]


# ── label-derived ids and names ──


@pytest.mark.parametrize("bad", ["../x", "Echo", "a b", "", "x" * 64, "echo\n", "-x"])
def test_list_running_skips_invalid_id_labels(fake, bad):
    fake.containers = [container("echo"), container(bad)]
    assert [a.id for a in list_running()] == ["echo"]


@pytest.mark.parametrize(
    "change",
    [
        {LABEL_KIND: ""},
        {LABEL_KIND: "vm"},
        {LABEL_PORT: ""},
        {LABEL_PORT: "http"},
        {LABEL_PORT: "0"},
        {LABEL_PORT: "70000"},
    ],
)
def test_list_running_needs_kind_and_port_labels(fake, change):
    bad = container("bad")
    bad["Config"]["Labels"].update(change)
    fake.containers = [container("echo"), bad]
    assert [a.id for a in list_running()] == ["echo"]


def test_list_running_compose_needs_the_labelled_service(fake):
    sidecar = container("stack", kind="compose")
    sidecar["Config"]["Labels"]["com.docker.compose.service"] = "db"
    unlabelled = container("other", kind="compose")
    del unlabelled["Config"]["Labels"]["com.docker.compose.service"]
    fake.containers = [container("echo"), sidecar, unlabelled]
    assert [a.id for a in list_running()] == ["echo"]


def test_list_running_keeps_actual_names(fake):
    stack = container("stack", kind="compose")
    stack["Config"]["Labels"]["com.docker.compose.project"] = "arena-abc-stack"
    echo_c = container("echo")
    echo_c["Name"] = "/some-other-name"
    fake.containers = [echo_c, stack]
    agents = {a.id: a for a in list_running()}
    assert agents["echo"].name == "some-other-name"
    assert agents["stack"].name == "arena-abc-stack"


@pytest.mark.parametrize("bad", ["../../etc/passwd", "Echo", "", "a/b"])
def test_run_env_file_validates_the_id(arena_home, bad):
    with pytest.raises(ValueError):
        run_env_file(bad)


def test_stop_uses_a_given_name(fake):
    stop("echo", "image", owner="ffffffffffff", name="arena-renamed")
    assert fake.argvs() == [
        door_stop("arena-renamed"),
        ["docker", "rm", "-f", "-v", "arena-renamed"],
        ["docker", "network", "rm", "arena-renamed"],
        outside_rm("arena-renamed"),
    ]
    fake.calls.clear()
    stop("stack", "compose", owner="ffffffffffff", name="proj-x")
    assert fake.argvs()[0] == door_stop("proj-x")
    assert "label=com.docker.compose.project=proj-x" in fake.argvs()[1]
    assert fake.argvs()[-1] == outside_rm("proj-x")


def test_stop_legacy_removes_our_keys_file_when_we_have_no_such_agent(fake, echo, tmp_path):
    path = run_env_file("echo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ECHO_PREFIX=x\n")
    fake.containers = []
    stop("echo", "image", owner="")
    assert not path.exists()


def test_stop_legacy_keeps_our_keys_file_while_our_agent_exists(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {"ECHO_PREFIX": "x"})
    stop("echo", "image", owner="")
    assert run_env_file("echo").exists()


# ── containment ──


def test_start_image_agent_has_resource_limits(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {})
    argv = agent_run(fake)[0]
    assert pair(argv, "--pids-limit", str(runtime.PIDS_LIMIT))
    assert pair(argv, "--memory", runtime.MEMORY_LIMIT)
    assert pair(argv, "--cpus", str(runtime.CPU_LIMIT))
    assert pair(argv, "--restart", "no")
    assert argv[-1] == echo.source.image


def _override_for(fake, compose_agent, services_update=None):
    m, agent_dir = compose_agent
    if services_update:
        data = copy.deepcopy(COMPOSE)
        for svc, spec in services_update.items():
            data["services"][svc].update(spec)
        (agent_dir / "docker-compose.yml").write_text(yaml.safe_dump(data))
    fake.containers = [container("stack", kind="compose")]
    start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    return yaml.safe_load((agent_dir / OVERRIDE_FILE).read_text())["services"]


def test_compose_override_limits_every_service(fake, compose_agent):
    services = _override_for(fake, compose_agent)
    for spec in services.values():
        assert spec["restart"] == "no"
        assert spec["pids_limit"] == runtime.PIDS_LIMIT
        assert spec["mem_limit"] == runtime.MEMORY_LIMIT
        assert spec["cpus"] == runtime.CPU_LIMIT


def test_compose_override_keeps_lower_limits(fake, compose_agent):
    services = _override_for(
        fake,
        compose_agent,
        {
            "agent": {"mem_limit": "512m", "cpus": 0.5, "restart": "always"},
            "db": {"mem_limit": "8g", "cpus": 4},
        },
    )
    assert "mem_limit" not in services["agent"] and "cpus" not in services["agent"]
    assert services["agent"]["restart"] == "no"
    assert services["db"]["mem_limit"] == runtime.MEMORY_LIMIT
    assert services["db"]["cpus"] == runtime.CPU_LIMIT


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("512m", 512 * 1024**2),
        ("2g", 2 * 1024**3),
        ("2GB", 2 * 1024**3),
        ("1024k", 1024**2),
        ("100b", 100),
        (1048576, 1048576),
        ("1.5g", int(1.5 * 1024**3)),
        ("lots", None),
        (True, None),
    ],
)
def test_memory_bytes(raw, expected):
    assert runtime._memory_bytes(raw) == expected


# ── container baseline ──


def sidecar(agent_id="stack", service="db", owner=None, **host_changes):
    """A compose side service of agent_id: owner label, empty arena labels, no ports."""
    c = container(agent_id, kind="compose")
    c["Id"] = f"c-{agent_id}-{service}"
    c["Name"] = f"/{resource_name(agent_id)}-{service}-1"
    c["Config"]["Labels"] = {
        LABEL_ID: "",
        LABEL_KIND: "",
        LABEL_PORT: "",
        LABEL_OWNER: paths.arena_owner() if owner is None else owner,
        "com.docker.compose.service": service,
        "com.docker.compose.project": resource_name(agent_id),
    }
    c["HostConfig"]["PortBindings"] = {}
    c["HostConfig"].update(host_changes)
    return c


def test_agent_containers_lists_every_container_of_this_owners_agent(fake):
    other_owner = container("echo")
    other_owner["Id"] = "c-other-owner"
    other_owner["Config"]["Labels"][LABEL_OWNER] = "0123456789ab"
    fake.containers = [
        container("echo"),
        other_owner,
        container("stack", kind="compose"),
        sidecar("stack", "db"),
        container("unrelated"),
    ]
    assert [c["Id"] for c in runtime.agent_containers("echo")] == ["c-echo"]
    assert [c["Id"] for c in runtime.agent_containers("stack")] == [
        "c-stack",
        "c-stack-db",
    ]


def test_agent_containers_argv_is_owner_scoped_and_includes_stopped(fake):
    fake.containers = [container("stack", kind="compose"), sidecar("stack", "db")]
    runtime.agent_containers("stack")
    ps = fake.find("ps")
    assert [c[0][1:] for c in ps] == [
        [
            "ps", "-a", "-q", "--no-trunc",
            "--filter", f"label={LABEL_ID}=stack",
            "--filter", f"label={LABEL_OWNER}={paths.arena_owner()}",
        ],
        [
            "ps", "-a", "-q", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={resource_name('stack')}",
        ],
    ]  # fmt: skip
    (inspect,) = fake.find("inspect")
    # each container once, though both listings return it
    assert inspect[0][2:] == ["c-stack", "c-stack-db"]
    assert all(c[2] == LIST_TIMEOUT_S for c in fake.calls)


def test_agent_containers_none(fake):
    assert runtime.agent_containers("echo") == []
    assert not fake.find("inspect")


def test_agent_containers_unreadable_inspect_is_an_error(fake):
    fake.containers = [container("echo")]
    fake.on(lambda a: a[:1] == ["inspect"], lambda a: _cp(a, 1, "", "permission denied"))
    with pytest.raises(DockerError, match="permission denied"):
        runtime.agent_containers("echo")


def test_agent_containers_keeps_what_inspect_returned_when_one_vanished(fake):
    fake.containers = [container("echo")]
    fake.on(
        lambda a: a[:1] == ["inspect"],
        lambda a: _cp(a, 1, json.dumps([container("echo")]), "Error: No such object: gone"),
    )
    assert len(runtime.agent_containers("echo")) == 1


def test_check_baseline(fake):
    fake.containers = [container("stack", kind="compose"), sidecar("stack", "db", Privileged=True)]
    (v,) = runtime.check_baseline("stack")
    assert (v.container, v.rule) == (f"{resource_name('stack')}-db-1", "not-privileged")
    fake.containers = [container("echo")]
    assert runtime.check_baseline("echo") == []


def test_start_checks_the_baseline_before_reporting_ready(fake, echo, tmp_path):
    fake.containers = [container()]
    start(echo, tmp_path, {})
    argvs = fake.argvs()
    run_at = next(i for i, a in enumerate(argvs) if a[1] == "run")
    assert any(a[1] == "inspect" for a in argvs[run_at + 1 :])
    assert fake.find("ps", "-a", "-q", "--no-trunc")


def test_start_refuses_a_root_container_and_cleans_up(fake, echo, tmp_path):
    root = container()
    root["Config"]["User"] = ""
    fake.containers = [root]
    with pytest.raises(runtime.BaselineError) as e:
        start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    assert isinstance(e.value, DockerError)
    lines = str(e.value).splitlines()
    assert "container baseline" in lines[0]
    assert lines[1].startswith(f"{resource_name('echo')}: non-root: runs as root")
    assert [v.rule for v in e.value.violations] == ["non-root"]
    assert len(fake.find("rm", "-f", "-v", resource_name("echo"))) == 2  # before run + stop
    assert fake.find("network", "rm", resource_name("echo"))
    assert not run_env_file("echo").exists()
    _no_secret_in_argv(fake)


def test_start_refuses_a_compose_side_service_and_cleans_up(fake, compose_agent, host_env):
    m, agent_dir = compose_agent
    fake.containers = [
        container("stack", kind="compose"),
        sidecar("stack", "db", CapAdd=["NET_ADMIN"], PidMode="host"),
    ]
    with pytest.raises(runtime.BaselineError) as e:
        start(m, agent_dir, {"OPENAI_API_KEY": SECRET})
    assert [(v.container, v.rule) for v in e.value.violations] == [
        (f"{resource_name('stack')}-db-1", "capabilities"),
        (f"{resource_name('stack')}-db-1", "host-namespaces"),
    ]
    assert [c for c in fake.calls if c[0][1] == "compose" and "down" in c[0]]
    assert not run_env_file("stack").exists()


def test_start_refuses_when_the_baseline_cannot_be_checked(fake, echo, tmp_path):
    fake.containers = [container()]
    fake.on(
        lambda a: a[:2] == ["ps", "-a"] and "--no-trunc" in a,
        subprocess.TimeoutExpired(["docker", "ps"], LIST_TIMEOUT_S),
    )
    with pytest.raises(DockerError, match="container baseline") as e:
        start(echo, tmp_path, {})
    assert not isinstance(e.value, runtime.BaselineError)
    assert len(fake.find("rm", "-f", "-v", resource_name("echo"))) == 2
    assert not run_env_file("echo").exists()


def test_start_refuses_even_when_cleanup_fails(fake, echo, tmp_path, monkeypatch):
    root = container()
    root["Config"]["User"] = "root"
    fake.containers = [root]

    def broken_stop(*args, **kwargs):
        raise DockerError("docker went away")

    monkeypatch.setattr(runtime, "stop", broken_stop)
    with pytest.raises(runtime.BaselineError):
        start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    assert not run_env_file("echo").exists()  # the keys file never outlives a refusal


def test_reset_fails_on_the_baseline_and_never_waits_for_health(fake, echo, tmp_path, monkeypatch):
    healthy = []
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: healthy.append(agent))
    fake.containers = [container()]
    start(echo, tmp_path, {"ECHO_PREFIX": SECRET})
    fake.containers[0]["HostConfig"]["Privileged"] = True
    with pytest.raises(runtime.BaselineError, match="not-privileged"):
        reset(echo, tmp_path)
    assert healthy == []
    assert not run_env_file("echo").exists()


# ── subprocess text ──


def test_run_decodes_utf8_and_replaces_bad_bytes(monkeypatch):
    seen = {}
    real = subprocess.run

    def spy(argv, **kwargs):
        seen.update(kwargs)
        return real(argv, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", spy)
    code = "import sys; sys.stdout.buffer.write(b'caf\\xc3\\xa9 \\xff\\xfe ok')"
    result = runtime._run([sys.executable, "-c", code], True)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert result.stdout == "café \ufffd\ufffd ok"


# ── what an agent may reach: networks, the baseline, the door's log ──


def test_reset_starts_behind_a_door_again(fake, echo, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "wait_healthy", lambda agent, health: None)
    fake.containers = [container()]
    start(echo, tmp_path, {})
    fake.calls.clear()
    assert reset(echo, tmp_path).host_port == 49153
    assert door_run(fake) and "-p" not in agent_run(fake)[0]
    assert [c[0][3] for c in fake.find("network", "create")][:2] == ["--internal"] * 2


def test_agent_networks_inspects_each_network_once(fake):
    a = container("stack", kind="compose")
    b = container("stack", kind="compose")
    b["NetworkSettings"]["Networks"] = {"p_back": {}, f"{resource_name('stack')}_default": {}}
    nets = runtime.agent_networks([a, b, "junk", {"NetworkSettings": None}])
    assert [n["Name"] for n in nets] == [f"{resource_name('stack')}_default", "p_back"]
    ((argv, _, timeout, _),) = fake.calls
    assert argv[:3] == ["docker", "network", "inspect"] and len(argv) == 5
    assert timeout == LIST_TIMEOUT_S


def test_agent_networks_never_passes_a_flag_or_runs_for_nothing(fake):
    odd = container()
    odd["NetworkSettings"]["Networks"] = {"--format={{.}}": {}, "": {}, 5: {}}
    assert runtime.agent_networks([odd]) == []
    assert fake.calls == []


@pytest.mark.parametrize("stdout", ["", "not json", "{}", "[1, null]"])
def test_unreadable_network_data_is_no_data(fake, stdout):
    fake.on(lambda a: a[:2] == ["network", "inspect"], lambda a: _cp(a, 1, stdout))
    assert runtime.agent_networks([container()]) == []


def test_the_baseline_refuses_a_network_with_a_route_out(fake):
    fake.containers = [container()]
    fake.open_networks = {resource_name("echo")}
    (v,) = runtime.check_baseline("echo")
    assert v.rule == "internal-networks" and "has a route out" in v.message


def test_the_baseline_refuses_a_network_it_cannot_read(fake):
    fake.containers = [container()]
    fake.on(lambda a: a[:2] == ["network", "inspect"], lambda a: _cp(a, 1, "", "gone"))
    (v,) = runtime.check_baseline("echo")
    assert v.rule == "internal-networks" and "no data" in v.message


def test_start_refuses_an_agent_that_ends_up_on_a_network_with_a_route_out(fake, echo, tmp_path):
    """Whatever made it so (another tool, an older Docker): hb checks what is there."""
    fake.containers = [container()]
    fake.on(
        lambda a: a[:2] == ["network", "inspect"],
        lambda a: _cp(a, 0, json.dumps([{"Name": resource_name("echo"), "Internal": False}])),
    )
    with pytest.raises(runtime.BaselineError) as e:
        start(echo, tmp_path, {})
    assert "internal-networks" in str(e.value)
    assert door_stop(resource_name("echo")) in fake.argvs()[-4:]


def test_door_logs(fake):
    runtime.door_logs("echo", follow=True, tail=5)
    ((argv, _, _, capture),) = fake.calls
    assert argv == ["docker", "logs", "--tail", "5", "-f", f"{resource_name('echo')}_door"]
    assert capture is False


def test_refused_destinations_come_from_the_doors_log(fake):
    log = (
        "door: in → echo:8080\n"
        "allowed api.openai.com:443\n"
        "blocked example.com:443\n"
        "failed files.example.com:443 (no connection)\n"
        "blocked example.com:443\n"
        "blocked evil\x1b[31m.example.com:443\n"
        "blocked\n"
        "\n"
    )
    fake.on(lambda a: a[:1] == ["logs"], lambda a: _cp(a, 0, log))
    assert runtime.refused_destinations("echo") == ["example.com:443", "files.example.com:443"]
    ((argv, _, timeout, _),) = fake.calls
    assert argv == ["docker", "logs", "--tail", "500", f"{resource_name('echo')}_door"]
    assert timeout == LIST_TIMEOUT_S
    fake.on(lambda a: a[:1] == ["logs"], DockerError("docker is down"))
    assert runtime.refused_destinations("echo") == []


def test_remove_doors_of_this_owner_only(fake):
    other = "ffffffffffff"
    fake.containers = [
        container("echo"),
        door("echo"),
        door("gone"),
        door("echo", owner=other),
    ]
    runtime.remove_doors()
    mine = paths.arena_owner()
    removed = [c[0][-1] for c in fake.find("rm")] + [c[0][-1] for c in fake.find("network", "rm")]
    assert sorted(removed) == sorted(
        [
            f"arena-{mine}-echo_door",
            f"arena-{mine}-gone_door",
            f"arena-{mine}-echo_out",
            f"arena-{mine}-gone_out",
        ]
    )
    fake.calls.clear()
    runtime.remove_doors(any_owner=True)
    assert [c[0][-1] for c in fake.find("rm")] == [f"arena-{other}-echo_door"]


def test_an_agents_container_is_never_taken_for_a_door(fake):
    """Agents carry the door label too (empty, so an image can't claim it)."""
    claims = container("echo")
    claims["Id"] = "claims"
    claims["Config"]["Labels"][LABEL_DOOR] = "echo"  # an agent that names itself a door
    side = {
        "Id": "side",
        "Name": "/stack-db-1",
        "Config": {
            "Labels": {
                LABEL_DOOR: "stack",
                LABEL_OWNER: paths.arena_owner(),
                "com.docker.compose.project": resource_name("stack"),
            }
        },
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5"}]}},
    }
    misnamed = door("echo", name="something-else")
    fake.containers = [container("echo"), claims, side, misnamed]
    runtime.remove_doors(any_owner=True)
    assert not fake.find("rm") and not fake.find("network", "rm")
    assert runtime._door_ports(None) == {(paths.arena_owner(), "echo"): 49153}


def test_remove_doors_is_best_effort(fake):
    fake.on(lambda a: a[:1] == ["ps"], DockerError("docker is down"))
    runtime.remove_doors()  # never raises


def test_names_of_the_door_and_its_network_are_never_an_agents():
    for agent_id in ("echo", "echo-door", "a" * 63):
        name = resource_name(agent_id)
        assert runtime.door_name(name) == f"{name}_door"
        assert runtime.outside_network(name) == f"{name}_out"
    taken = {resource_name(i) for i in ("echo", "echo-door", "echo-out", "a" * 63, "b" * 63)}
    assert not taken & {runtime.door_name(n) for n in taken}
    assert not taken & {runtime.outside_network(n) for n in taken}
