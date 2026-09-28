# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Owner-scoped arena resources: two HOMEs (owners) on one Docker daemon never see or
touch each other's agents. Docker is a stateful fake shared by both owners."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from humanbound_cli.arena import daemon, paths, runtime
from humanbound_cli.arena.manifest import load_manifest
from humanbound_cli.arena.runtime import LABEL_ID, LABEL_OWNER, LABEL_PORT, resource_name
from humanbound_cli.main import cli

from .arena_testing import ECHO_YAML
from .arena_testing import completed as _cp


def _value(args, flag):
    return [args[i + 1] for i in range(len(args) - 1) if args[i] == flag]


class MachineDocker:
    """One Docker daemon shared by every HOME: containers by name, label filters honoured."""

    def __init__(self):
        self.containers: dict[str, dict] = {}
        self.networks: dict[str, bool] = {}  # name -> it has no route out (--internal)
        self.next_port = 40000
        self.serial = 0

    def add(
        self, name: str, labels: dict[str, str], port: int = 8080, run_args: list | None = None
    ) -> dict:
        """A container; with `run_args` (a `docker run` argv), its HostConfig is what those
        flags ask for, as Docker would report it (the image runs as a non-root user)."""
        self.serial += 1
        self.next_port += 1
        args = run_args or []
        bindings = {}
        published = {}
        for spec in _value(args, "-p"):
            host_ip, _, container_port = spec.rpartition(":")
            host_ip = host_ip.rstrip(":")
            bindings[f"{container_port}/tcp"] = [{"HostIp": host_ip, "HostPort": ""}]
            published[f"{container_port}/tcp"] = [
                {"HostIp": host_ip, "HostPort": str(self.next_port)}
            ]
        if run_args is None:  # put there by a test: it publishes its port itself
            published = {f"{port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.next_port)}]}
        network = (_value(args, "--network") or [name])[0]
        container = {
            "Id": f"id{self.serial}",
            "Name": f"/{name}",
            "Config": {"User": "65534", "Labels": labels},
            "Mounts": [],
            "HostConfig": {
                "Privileged": "--privileged" in args,
                "CapDrop": _value(args, "--cap-drop") if run_args is not None else ["ALL"],
                "CapAdd": _value(args, "--cap-add") or None,
                "SecurityOpt": (
                    _value(args, "--security-opt")
                    if run_args is not None
                    else ["no-new-privileges"]
                ),
                "PidMode": "",
                "IpcMode": "private",
                "NetworkMode": network,
                "UTSMode": "",
                "UsernsMode": "",
                "PortBindings": bindings,
            },
            "NetworkSettings": {"Ports": published, "Networks": {network: {}}},
        }
        self.containers[name] = container
        return container

    def _matches(self, container: dict, filters: list[str]) -> bool:
        labels = container["Config"]["Labels"]
        for f in filters:
            key, _, want = f.removeprefix("label=").partition("=")
            if key not in labels or (want and labels[key] != want):
                return False
        return True

    def __call__(self, argv, capture, env=None, timeout=None):
        args = list(argv[1:])
        cmd = args[0]
        if cmd == "network":
            name = args[-1]
            if args[1] == "inspect":
                found = [
                    {"Name": n, "Internal": self.networks[n]}
                    for n in args[2:]
                    if n in self.networks
                ]
                return _cp(argv, 0 if len(found) == len(args[2:]) else 1, json.dumps(found))
            if args[1] == "create":
                self.networks[name] = "--internal" in args
            if args[1] == "rm":
                self.networks.pop(name, None)
            return _cp(argv)
        if cmd == "rm":
            self.containers.pop(args[-1], None)
            return _cp(argv)
        if cmd == "run":
            labels = dict(label.split("=", 1) for label in _value(args, "--label"))
            self.add(_value(args, "--name")[0], labels, int(labels.get(LABEL_PORT, 8080)), args)
            return _cp(argv, 0, "cid\n")
        if cmd == "ps":
            filters = _value(args, "--filter")
            ids = [c["Id"] for c in self.containers.values() if self._matches(c, filters)]
            return _cp(argv, 0, "\n".join(ids))
        if cmd == "inspect":
            wanted = set(args[1:])
            found = [c for c in self.containers.values() if c["Id"] in wanted]
            return _cp(argv, 0, json.dumps(found))
        return _cp(argv)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    fake = MachineDocker()
    monkeypatch.setattr(runtime, "_run", fake)
    monkeypatch.setattr(runtime, "preflight", lambda m=None: None)
    monkeypatch.setattr(runtime, "docker_cli", lambda: "/usr/bin/docker")
    monkeypatch.delenv("HB_DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("HB_ARENA_PORT", raising=False)
    monkeypatch.delenv("HB_ARENA_INDEX", raising=False)
    return fake


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """as_owner('a') / as_owner('b') switches HOME, and so the arena owner."""
    made = {}

    def as_owner(name: str) -> str:
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        made[name] = paths.arena_owner()
        return made[name]

    return as_owner


@pytest.fixture
def echo():
    return load_manifest(ECHO_YAML)


@pytest.fixture
def gateways(monkeypatch):
    stops = []

    def stop_gateway(port=None, **kwargs):
        stops.append(paths.arena_owner())
        return True

    monkeypatch.setattr(daemon, "stop_gateway", stop_gateway)
    return stops


def resources(*owners_and_ids):
    """The names of an agent's resources: itself and its door (containers), or its network
    and its door's (networks)."""
    names = []
    for owner, agent_id in owners_and_ids:
        name = f"arena-{owner}-{agent_id}"
        names += [name, f"{name}_door"]
    return sorted(names)


def networks(*owners_and_ids):
    names = []
    for owner, agent_id in owners_and_ids:
        name = f"arena-{owner}-{agent_id}"
        names += [name, f"{name}_out"]
    return sorted(names)


def arena(*args):
    return CliRunner().invoke(cli, ["arena", *args], catch_exceptions=False)


def test_two_owners_run_the_same_agent_side_by_side(machine, homes, echo, tmp_path):
    owner_a = homes("a")
    agent_a = runtime.start(echo, tmp_path, {})
    first_id = machine.containers[resource_name("echo")]["Id"]

    owner_b = homes("b")
    agent_b = runtime.start(echo, tmp_path, {})
    assert owner_a != owner_b

    # B's start did not replace A's container (no `docker rm -f` on A's name).
    names = sorted(machine.containers)
    assert names == resources((owner_a, "echo"), (owner_b, "echo"))
    assert machine.containers[f"arena-{owner_a}-echo"]["Id"] == first_id
    assert sorted(machine.networks) == networks((owner_a, "echo"), (owner_b, "echo"))
    # the agents' networks have no route out; their doors' networks do
    assert machine.networks[f"arena-{owner_a}-echo"] is True
    assert machine.networks[f"arena-{owner_a}-echo_out"] is False
    assert agent_a.host_port != agent_b.host_port  # each behind its own door

    # Each owner sees only its own agent.
    assert [a.host_port for a in runtime.list_running()] == [agent_b.host_port]
    homes("a")
    assert [a.host_port for a in runtime.list_running()] == [agent_a.host_port]
    assert runtime.find_running("echo").owner == owner_a


def test_stop_all_leaves_the_other_owner_alone(machine, homes, echo, tmp_path, gateways):
    owner_a = homes("a")
    runtime.start(echo, tmp_path, {})
    owner_b = homes("b")
    runtime.start(echo, tmp_path, {})

    result = arena("stop", "--all")
    assert result.exit_code == 0, result.output
    assert "✓ echo stopped" in result.output
    assert sorted(machine.containers) == resources((owner_a, "echo"))
    assert sorted(machine.networks) == networks((owner_a, "echo"))
    assert gateways == [owner_b]  # only this owner's gateway

    homes("a")
    assert "echo" in arena("ps").output
    assert [a.id for a in runtime.list_running()] == ["echo"]


def test_stop_one_leaves_the_other_owners_agent(machine, homes, echo, tmp_path, gateways):
    owner_a = homes("a")
    runtime.start(echo, tmp_path, {})
    homes("b")
    runtime.start(echo, tmp_path, {})
    assert arena("stop", "echo").exit_code == 0
    assert sorted(machine.containers) == resources((owner_a, "echo"))
    assert sorted(machine.networks) == networks((owner_a, "echo"))


def test_stop_all_any_owner_stops_everyone(machine, homes, echo, tmp_path, gateways):
    homes("a")
    runtime.start(echo, tmp_path, {})
    a_keys = runtime.run_env_file("echo")
    assert a_keys.exists()
    owner_b = homes("b")
    runtime.start(echo, tmp_path, {})
    # a pre-owner (legacy) container: id label, no owner label, named arena-<id>
    machine.add(
        "arena-legacy",
        {LABEL_ID: "legacy", runtime.LABEL_KIND: "image", runtime.LABEL_PORT: "8080"},
    )

    result = arena("stop", "--all", "--any-owner")
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "1 agent from other owners" in out
    assert "1 from an older hb" in out
    assert out.count("✓ echo stopped") == 2
    assert "✓ legacy stopped" in out
    assert machine.containers == {}
    assert machine.networks == {}
    assert gateways == [owner_b]  # other owners' gateways are theirs to stop
    assert a_keys.exists()  # another HOME's files are never touched


def test_any_owner_needs_all(machine, homes):
    homes("a")
    result = arena("stop", "echo", "--any-owner")
    assert result.exit_code == 1
    assert "--any-owner" in result.output and "--all" in result.output


def test_other_owner_agent_is_not_running_here(machine, homes, echo, tmp_path):
    homes("a")
    runtime.start(echo, tmp_path, {})
    homes("b")
    result = arena("stop", "echo")
    assert result.exit_code == 1
    assert "echo is not running" in result.output
    assert len(machine.containers) == 2  # the other owner's agent and its door


def test_owner_is_case_insensitive_on_macos_and_windows(monkeypatch, tmp_path):
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(paths.sys, "platform", platform)
        assert paths.owner_of(tmp_path / "Home") == paths.owner_of(tmp_path / "hOME")
    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths.owner_of(tmp_path / "Home") != paths.owner_of(tmp_path / "hOME")


def test_any_owner_stop_uses_the_reported_name(machine, homes, echo, tmp_path, gateways):
    homes("a")
    # another owner's container whose name isn't what we would compute
    machine.add(
        "renamed-by-hand",
        {
            LABEL_ID: "echo",
            runtime.LABEL_KIND: "image",
            runtime.LABEL_PORT: "8080",
            LABEL_OWNER: "ffffffffffff",
        },
    )
    result = arena("stop", "--all", "--any-owner")
    assert result.exit_code == 0, result.output
    assert machine.containers == {}


def test_ps_and_stop_all_hint_at_legacy_containers(machine, homes, echo, tmp_path, gateways):
    homes("a")
    runtime.start(echo, tmp_path, {})
    for agent_id in ("old-one", "old-two"):
        machine.add(
            f"arena-{agent_id}",
            {LABEL_ID: agent_id, runtime.LABEL_KIND: "image", runtime.LABEL_PORT: "8080"},
        )
    hint = "2 arena containers from an older hb → hb arena stop --all --any-owner"
    out = " ".join(arena("ps").output.split())
    assert hint in out
    out = " ".join(arena("stop", "--all").output.split())
    assert "✓ echo stopped" in out and hint in out
    assert sorted(machine.containers) == ["arena-old-one", "arena-old-two"]  # left alone


def test_no_legacy_hint_without_legacy_containers(machine, homes, echo, tmp_path):
    homes("a")
    runtime.start(echo, tmp_path, {})
    assert "older hb" not in arena("ps").output


def test_stop_legacy_agent_removes_our_stale_keys_file(machine, homes, echo, tmp_path, gateways):
    homes("a")
    keys_file = runtime.run_env_file("legacy")
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    keys_file.write_text("")
    machine.add(
        "arena-legacy",
        {LABEL_ID: "legacy", runtime.LABEL_KIND: "image", runtime.LABEL_PORT: "8080"},
    )
    assert arena("stop", "--all", "--any-owner").exit_code == 0
    assert not keys_file.exists()


def test_stop_all_removes_a_door_whose_agent_is_gone(machine, homes, echo, tmp_path, gateways):
    owner_a = homes("a")
    runtime.start(echo, tmp_path, {})
    owner_b = homes("b")
    runtime.start(echo, tmp_path, {})
    del machine.containers[f"arena-{owner_b}-echo"]  # crashed and removed outside hb
    result = arena("stop", "--all")
    assert result.exit_code == 0, result.output
    assert "No arena agents running." in result.output
    assert sorted(machine.containers) == resources((owner_a, "echo"))  # never another owner's
    assert f"arena-{owner_b}-echo_out" not in machine.networks
