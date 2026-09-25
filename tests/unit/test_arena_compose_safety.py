# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""compose_safety: an agent's own docker-compose.yml must not reach the host."""

import copy

import pytest
import yaml
from conftest import ARENA_FIXTURES

from humanbound_cli.arena import compose_safety, runtime
from humanbound_cli.arena.compose_safety import COMPOSE_FILE, DockerError, check_compose
from humanbound_cli.arena.manifest import load_manifest, parse_manifest

ECHO = load_manifest(ARENA_FIXTURES / "catalog" / "agents" / "echo" / "arena.yaml")


def _compose_manifest():
    data = copy.deepcopy(ECHO.model_dump(mode="json"))
    data["source"] = {"compose": "docker-compose.yml", "service": "agent"}
    return parse_manifest(data)


def _write_compose(agent_dir, services, **top):
    doc = {"services": services, **top}
    (agent_dir / COMPOSE_FILE).write_text(yaml.safe_dump(doc))


def _check(agent_dir):
    check_compose(_compose_manifest(), agent_dir)


def test_runtime_keeps_check_compose_and_docker_error_as_re_exports():
    assert runtime.check_compose is compose_safety.check_compose
    assert runtime.DockerError is compose_safety.DockerError
    assert runtime.COMPOSE_FILE == COMPOSE_FILE


@pytest.mark.parametrize(
    "service, field",
    [
        # not on the service allowlist
        ({"image": "x", "ports": ["8080:8080"]}, "ports"),
        ({"image": "x", "network_mode": "host"}, "network_mode"),
        ({"image": "x", "network_mode": "service:db"}, "network_mode"),
        ({"image": "x", "privileged": True}, "privileged"),
        ({"image": "x", "privileged": "${P}"}, "privileged"),
        ({"image": "x", "cap_add": ["NET_ADMIN"]}, "cap_add"),
        ({"image": "x", "pid": "host"}, "pid"),
        ({"image": "x", "ipc": "host"}, "ipc"),
        ({"image": "x", "devices": ["/dev/sda:/dev/sda"]}, "devices"),
        ({"image": "x", "userns_mode": "host"}, "userns_mode"),
        ({"image": "x", "uts": "host"}, "uts"),
        ({"image": "x", "security_opt": ["seccomp:unconfined"]}, "security_opt"),
        ({"image": "x", "volumes_from": ["other"]}, "volumes_from"),
        ({"image": "x", "env_file": ["agent.env"]}, "env_file"),
        ({"image": "x", "env_file": "../../.humanbound/x.env"}, "env_file"),
        ({"image": "x", "extends": {"file": "other.yml", "service": "a"}}, "extends"),
        ({"image": "x", "container_name": "arena-other"}, "container_name"),
        ({"image": "x", "use_api_socket": True}, "use_api_socket"),
        ({"provider": {"type": "model", "options": {}}}, "provider"),
        ({"image": "x", "secrets": ["s"]}, "secrets"),
        ({"image": "x", "configs": ["c"]}, "configs"),
        ({"image": "x", "extra_hosts": ["host.docker.internal:host-gateway"]}, "extra_hosts"),
        ({"image": "x", "sysctls": {"net.ipv4.ip_forward": 1}}, "sysctls"),
        ({"image": "x", "cgroup_parent": "/"}, "cgroup_parent"),
        ({"image": "x", "profiles": ["debug"]}, "profiles"),
        # volumes: named/anonymous volumes only
        ({"image": "x", "volumes": ["/etc:/host-etc"]}, "volumes"),
        ({"image": "x", "volumes": ["./src:/src"]}, "volumes"),
        ({"image": "x", "volumes": ["~/.ssh:/root/.ssh:ro"]}, "volumes"),
        ({"image": "x", "volumes": ["${HOME}:/h"]}, "volumes"),
        ({"image": "x", "volumes": [{"type": "bind", "source": "/", "target": "/h"}]}, "volumes"),
        ({"image": "x", "volumes": [{"type": "npipe", "source": "x", "target": "/h"}]}, "volumes"),
        # labels: hb's own namespace is reserved
        ({"image": "x", "labels": {"io.humanbound.arena.id": "other"}}, "labels"),
        ({"image": "x", "labels": ["io.humanbound.arena.port=1"]}, "labels"),
        ({"image": "x", "labels": {"IO.Humanbound.x": "y"}}, "labels"),
        # logging: local drivers only
        ({"image": "x", "logging": {"driver": "syslog"}}, "logging"),
        # build: context inside the agent dir, allowlisted keys only
        ({"build": ".."}, "build.context"),
        ({"build": {"context": "/"}}, "build.context"),
        ({"build": "https://github.com/evil/repo.git"}, "build.context"),
        ({"build": "git@github.com:evil/repo.git"}, "build.context"),
        ({"build": "github.com/evil/repo"}, "build.context"),
        ({"build": {"context": ".#main"}}, "build.context"),
        ({"build": {"context": ".", "dockerfile": "../Dockerfile"}}, "build.dockerfile"),
        ({"build": {"context": ".", "dockerfile": "/etc/Dockerfile"}}, "build.dockerfile"),
        ({"build": {"context": ".", "ssh": ["default"]}}, "build.ssh"),
        ({"build": {"context": ".", "network": "host"}}, "build.network"),
        ({"build": {"context": ".", "privileged": True}}, "build.privileged"),
        ({"build": {"context": ".", "entitlements": ["network.host"]}}, "build.entitlements"),
        (
            {"build": {"context": ".", "additional_contexts": {"x": "/"}}},
            "build.additional_contexts",
        ),
        ({"build": {"context": ".", "secrets": ["s"]}}, "build.secrets"),
        ({"build": {"context": ".", "dockerfile_inline": "FROM x"}}, "build.dockerfile_inline"),
    ],
)
def test_unsafe_services_are_rejected_naming_service_and_key(tmp_path, service, field):
    _write_compose(tmp_path, {"agent": {"image": "a"}, "sidecar": service})
    with pytest.raises(DockerError) as exc:
        _check(tmp_path)
    assert "sidecar" in str(exc.value) and field in str(exc.value)


@pytest.mark.parametrize(
    "top, field",
    [
        ({"include": ["other.yml"]}, "include"),
        ({"name": "someone-elses-project"}, "name"),
        ({"secrets": {"s": {"file": "s.txt"}}}, "secrets"),
        ({"configs": {"c": {"file": "c.txt"}}}, "configs"),
        ({"models": {"m": {"model": "x"}}}, "models"),
        ({"networks": {"n": {"external": True, "name": "host"}}}, "external"),
        ({"networks": {"n": {"driver": "host"}}}, "driver"),
        ({"networks": {"n": {"driver": "macvlan"}}}, "driver"),
        ({"volumes": {"v": {"external": True}}}, "external"),
        (
            {"volumes": {"v": {"driver_opts": {"type": "none", "o": "bind", "device": "/"}}}},
            "driver_opts",
        ),
    ],
)
def test_unsafe_top_level_keys_are_rejected(tmp_path, top, field):
    _write_compose(tmp_path, {"agent": {"image": "a"}}, **top)
    with pytest.raises(DockerError, match=field):
        _check(tmp_path)


@pytest.mark.parametrize(
    "services, top",
    [
        ({"agent": {"image": "a", "volumes": "/etc:/x"}}, {}),
        ({"agent": {"image": "a", "labels": "io.humanbound.arena.id=x"}}, {}),
        ({"agent": {"build": 3}}, {}),
        ({"agent": {"image": "a"}}, {"volumes": ["v"]}),
    ],
)
def test_malformed_sections_are_rejected(tmp_path, services, top):
    _write_compose(tmp_path, services, **top)
    with pytest.raises(DockerError, match="must be a"):
        _check(tmp_path)


def test_the_talked_to_service_must_exist(tmp_path):
    _write_compose(tmp_path, {"other": {"image": "a"}})
    with pytest.raises(DockerError, match="no service 'agent'"):
        _check(tmp_path)


def test_every_allowlisted_feature_is_accepted(tmp_path):
    services = {
        "agent": {
            "build": {
                "context": "./agent",
                "dockerfile": "Dockerfile.arena",
                "args": {"A": "1"},
                "target": "runtime",
            },
            "command": ["python", "app.py"],
            "entrypoint": ["/bin/sh", "-c"],
            "environment": {"MODE": "demo"},
            "expose": ["8080"],
            "healthcheck": {"test": ["CMD", "true"], "interval": "5s"},
            "depends_on": {"db": {"condition": "service_healthy"}},
            "restart": "unless-stopped",
            "working_dir": "/app",
            "user": "1000:1000",
            "volumes": ["/anon", "named:/data", {"type": "tmpfs", "target": "/tmp"}],
            "networks": ["backend"],
            "tmpfs": ["/run"],
            "read_only": True,
            "labels": {"com.example.role": "agent"},
            "stop_signal": "SIGINT",
            "stop_grace_period": "5s",
            "init": True,
            "mem_limit": "512m",
            "cpus": 1.5,
            "shm_size": "64m",
            "ulimits": {"nofile": 1024},
            "logging": {"driver": "json-file", "options": {"max-size": "1m"}},
            "platform": "linux/amd64",
            "hostname": "agent",
        },
        "db": {"image": "postgres:16", "networks": {"backend": {"aliases": ["pg"]}}},
    }
    _write_compose(
        tmp_path,
        services,
        volumes={"named": {}},
        networks={"backend": {"driver": "bridge"}},
        **{"x-common": {"restart": "no"}},
    )
    _check(tmp_path)


def test_build_shorthand_string_is_a_context(tmp_path):
    _write_compose(tmp_path, {"agent": {"build": "."}})
    _check(tmp_path)


def test_agent_dir_with_dotenv_is_rejected(tmp_path):
    """A `.env` next to the compose file is picked up automatically by `docker compose`
    for ${VAR} interpolation, bypassing our allowlisted subprocess env entirely."""
    _write_compose(tmp_path, {"agent": {"image": "a"}})
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=leaked\n")
    with pytest.raises(DockerError, match=r"\.env"):
        _check(tmp_path)


@pytest.mark.parametrize("content", [None, "services: [", "- a list", "services: {agent: 3}"])
def test_missing_or_invalid_compose_file_is_rejected(tmp_path, content):
    if content is not None:
        (tmp_path / COMPOSE_FILE).write_text(content)
    with pytest.raises(DockerError, match=COMPOSE_FILE):
        _check(tmp_path)
