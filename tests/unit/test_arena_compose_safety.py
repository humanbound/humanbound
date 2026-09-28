# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the allowlist-based compose file check."""

import copy

import pytest
import yaml

from humanbound_cli.arena.compose_safety import DockerError, check_compose, checked_services
from humanbound_cli.arena.manifest import parse_manifest

from .arena_testing import ECHO_YAML

ECHO = yaml.safe_load(ECHO_YAML.read_text())

VALID = {
    "version": "3.9",
    "x-common": {"restart": "unless-stopped"},
    "services": {
        "agent": {
            "image": "ghcr.io/example/arena-agent:1.0.0",
            "command": ["sh", "-c", "echo $$HOME"],
            "entrypoint": "/bin/sh",
            "environment": {"MODE": "demo", "PREFIX": "${ECHO_PREFIX}"},
            "expose": [8080],
            "healthcheck": {"test": ["CMD", "true"]},
            "depends_on": ["db"],
            "restart": "unless-stopped",
            "working_dir": "/app",
            "user": "65534",
            "volumes": ["data:/data", {"type": "volume", "source": "cache", "target": "/cache"}],
            "networks": ["backend"],
            "tmpfs": ["/tmp"],
            "read_only": True,
            "labels": {"com.example.role": "agent"},
            "stop_signal": "SIGTERM",
            "stop_grace_period": "5s",
            "init": True,
            "mem_limit": "512m",
            "cpus": 1,
            "shm_size": "64m",
            "ulimits": {"nofile": 1024},
            "logging": {"driver": "json-file"},
            "platform": "linux/amd64",
            "hostname": "agent",
        },
        "db": {"image": "postgres:16", "labels": ["com.example.role=db"], "networks": ["backend"]},
        "worker": {
            "image": "busybox@sha256:" + "a" * 64,
            "volumes": ["/scratch"],
            "environment": ["PREFIX=${ECHO_PREFIX}", "PLAIN=1"],
        },
    },
    "volumes": {"data": None, "cache": {"driver": "local"}},
    "networks": {"backend": {"driver": "bridge"}},
}


def _manifest(service="agent"):
    data = copy.deepcopy(ECHO)
    data["source"] = {"compose": "docker-compose.yml", "service": service}
    return parse_manifest(data)


def _write(tmp_path, compose):
    text = compose if isinstance(compose, str) else yaml.safe_dump(compose)
    (tmp_path / "docker-compose.yml").write_text(text)
    return tmp_path


def _with(mutator):
    data = copy.deepcopy(VALID)
    mutator(data)
    return data


def _svc(key, value, service="agent"):
    return _with(lambda d: d["services"][service].__setitem__(key, value))


def test_valid_multi_service_file_passes(tmp_path):
    names = check_compose(_manifest(), _write(tmp_path, VALID))
    assert sorted(names) == ["agent", "db", "worker"]


def test_missing_file(tmp_path):
    with pytest.raises(DockerError, match="docker-compose.yml"):
        check_compose(_manifest(), tmp_path)


@pytest.mark.parametrize(
    "text", ["services: [unterminated", "- just\n- a list\n", "services: [a, b]\n"]
)
def test_malformed_file(tmp_path, text):
    with pytest.raises(DockerError):
        check_compose(_manifest(), _write(tmp_path, text))


def test_service_not_in_file(tmp_path):
    with pytest.raises(DockerError, match="nope"):
        check_compose(_manifest("nope"), _write(tmp_path, VALID))


def test_dotenv_in_agent_dir_rejected(tmp_path):
    _write(tmp_path, VALID)
    (tmp_path / ".env").write_text("X=1\n")
    with pytest.raises(DockerError, match=r"\.env"):
        check_compose(_manifest(), tmp_path)


def test_dotenv_allowed_when_asked(tmp_path):
    # `hb arena validate` passes allow_dotenv=True: an author's local .env is fine there.
    _write(tmp_path, VALID)
    (tmp_path / ".env").write_text("X=1\n")
    assert "agent" in check_compose(_manifest(), tmp_path, allow_dotenv=True)


@pytest.mark.parametrize("key", ["name", "include", "secrets", "configs", "models"])
def test_top_level_key_rejected(tmp_path, key):
    data = _with(lambda d: d.__setitem__(key, "x" if key == "name" else ["x"]))
    with pytest.raises(DockerError, match=key):
        check_compose(_manifest(), _write(tmp_path, data))


REJECTED_SERVICE_KEYS = {
    "ports": ["8080:8080"],
    "privileged": True,
    "network_mode": "host",
    "pid": "host",
    "ipc": "host",
    "userns_mode": "host",
    "uts": "host",
    "cgroup": "host",
    "cap_add": ["SYS_ADMIN"],
    "devices": ["/dev/sda:/dev/sda"],
    "volumes_from": ["db"],
    "security_opt": ["seccomp:unconfined"],
    "env_file": [".secrets"],
    "container_name": "fixed",
    "use_api_socket": True,
    "provider": {"type": "x"},
    "extends": {"service": "db"},
    "secrets": ["s"],
    "configs": ["c"],
    "extra_hosts": ["host.docker.internal:host-gateway"],
    "x-custom": {"a": 1},
}


@pytest.mark.parametrize(("key", "value"), list(REJECTED_SERVICE_KEYS.items()))
def test_service_key_rejected(tmp_path, key, value):
    with pytest.raises(DockerError, match=rf"agent.*{key}"):
        check_compose(_manifest(), _write(tmp_path, _svc(key, value)))


def test_rejected_key_on_non_target_service(tmp_path):
    with pytest.raises(DockerError, match=r"db.*privileged"):
        check_compose(_manifest(), _write(tmp_path, _svc("privileged", True, service="db")))


@pytest.mark.parametrize(
    "labels",
    [
        {"io.humanbound.arena.id": "other"},
        ["io.humanbound.arena.port=1"],
        ["IO.HUMANBOUND.x"],
    ],
)
def test_humanbound_labels_rejected(tmp_path, labels):
    with pytest.raises(DockerError, match="io.humanbound"):
        check_compose(_manifest(), _write(tmp_path, _svc("labels", labels)))


@pytest.mark.parametrize("driver", ["syslog", "fluentd", "gelf"])
def test_logging_driver_rejected(tmp_path, driver):
    with pytest.raises(DockerError, match="logging"):
        check_compose(_manifest(), _write(tmp_path, _svc("logging", {"driver": driver})))


@pytest.mark.parametrize("driver", ["local", "none"])  # json-file is in VALID
def test_logging_driver_allowed(tmp_path, driver):
    check_compose(_manifest(), _write(tmp_path, _svc("logging", {"driver": driver})))


@pytest.mark.parametrize(
    "volume",
    [
        "/etc:/host-etc",
        "./src:/app",
        "../up:/x",
        "~/.ssh:/root/.ssh",
        "$HOME:/h",
        "${HOME}:/h",
        "/var/run/docker.sock:/var/run/docker.sock",
        "C:\\Users\\me:/x",
        "c:/data:/x",
        {"type": "bind", "source": "/", "target": "/host"},
        {"type": "volume", "source": "/etc", "target": "/x"},
        {"type": "npipe", "source": "x", "target": "/x"},
    ],
)
def test_bind_mounts_rejected(tmp_path, volume):
    with pytest.raises(DockerError, match="volume"):
        check_compose(_manifest(), _write(tmp_path, _svc("volumes", [volume])))


@pytest.mark.parametrize(
    "build",
    [
        ".",
        "./worker",
        {"context": "."},
        {"context": "x/${X:-..}/${X:-..}/${X:-..}", "dockerfile": "x/${X:-..}/docker-compose.yml"},
    ],
)
def test_build_rejected(tmp_path, build):
    with pytest.raises(DockerError, match=r"agent.*build is not supported"):
        check_compose(_manifest(), _write(tmp_path, _svc("build", build)))


def test_service_without_image_rejected(tmp_path):
    data = _with(lambda d: d["services"]["db"].pop("image"))
    with pytest.raises(DockerError, match=r"db.*image"):
        check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize(
    ("mutator", "where"),
    [
        # label spoof: compose would turn this into io.humanbound.arena.id=victim
        (
            lambda d: d["services"]["agent"].__setitem__(
                "labels", ["io${X:-.humanbound.arena.id}=victim"]
            ),
            "services.agent.labels",
        ),
        # host leak: compose would read the host's HOME / HTTPS_PROXY
        (
            lambda d: d["services"]["agent"].__setitem__(
                "environment", {"LEAK": "${HOME}|${HTTPS_PROXY}"}
            ),
            "services.agent.environment.LEAK",
        ),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", ["LEAK=${HOME}"]),
            "services.agent.environment",
        ),
        # network driver chosen by interpolation
        (
            lambda d: d["networks"].__setitem__("backend", {"driver": "${D:-macvlan}"}),
            "networks.backend.driver",
        ),
        (lambda d: d["services"]["agent"].__setitem__("command", "run $X"), "command"),
        (lambda d: d["services"]["agent"].__setitem__("command", "run $$$X"), "command"),
        (lambda d: d["services"]["agent"].__setitem__("labels", {"${K}": "v"}), "labels"),
        (lambda d: d.__setitem__("x-anchor", {"a": "${HOME}"}), "x-anchor"),
        # declared names are only allowed as a whole environment value
        (lambda d: d["services"]["agent"].__setitem__("command", "${ECHO_PREFIX}"), "command"),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", {"P": "x${ECHO_PREFIX}"}),
            "environment",
        ),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", {"P": "${ECHO_PREFIX:-x}"}),
            "environment",
        ),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", {"P": "$ECHO_PREFIX"}),
            "environment",
        ),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", {"P": "${UNDECLARED}"}),
            "environment",
        ),
        (
            lambda d: d["services"]["agent"].__setitem__("environment", {"${ECHO_PREFIX}": "v"}),
            "environment",
        ),
    ],
)
def test_interpolation_rejected(tmp_path, mutator, where):
    with pytest.raises(DockerError, match="interpolat") as e:
        check_compose(_manifest(), _write(tmp_path, _with(mutator)))
    assert where in str(e.value)


def test_declared_env_passthrough_allowed(tmp_path):
    data = _svc("environment", {"A": "${ECHO_PREFIX}", "B": "$$literal"})
    check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize("name", ["true", "1", "null"])
def test_non_string_service_name_rejected(tmp_path, name):
    text = f"services:\n  agent: {{image: a}}\n  {name}: {{image: b}}\n"
    with pytest.raises(DockerError, match="service name"):
        check_compose(_manifest(), _write(tmp_path, text))


def test_single_letter_volume_rejected_with_clear_reason(tmp_path):
    # compose reads "v:/data" as a Windows drive path (an anonymous volume at target
    # "v:/data"), and "w:/x:ro" as a bind mount of w:/x, so single-letter names are refused.
    with pytest.raises(DockerError, match="drive letter"):
        check_compose(_manifest(), _write(tmp_path, _svc("volumes", ["v:/data"])))
    check_compose(_manifest(), _write(tmp_path, _svc("volumes", ["vv:/data"])))


@pytest.mark.parametrize(
    "network",
    [
        {"external": True},
        {"driver_opts": {"com.docker.network.bridge.name": "x"}},
        {"driver": "host"},
        {"driver": "none"},
        {"driver": "macvlan"},
        {"driver": "ipvlan"},
        {"driver": "overlay"},
        {"driver": "custom-plugin"},
        {"name": "bridge"},
        {"ipam": {"config": [{"subnet": "172.30.0.0/16"}]}},
        {"ipam": {"driver": "default"}},
        {"surprise": 1},
    ],
)
def test_unsafe_top_level_network_rejected(tmp_path, network):
    data = _with(lambda d: d["networks"].__setitem__("backend", network))
    with pytest.raises(DockerError, match="network"):
        check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize(
    "volume",
    [
        {"external": True},
        {"driver_opts": {"type": "none", "o": "bind", "device": "/"}},
        {"name": "someone-elses-volume"},
        {"driver": "nfs"},
        {"driver": "some-plugin"},
        {"surprise": 1},
        {"x-custom": 1},
    ],
)
def test_unsafe_top_level_volume_rejected(tmp_path, volume):
    data = _with(lambda d: d["volumes"].__setitem__("data", volume))
    with pytest.raises(DockerError, match="volume"):
        check_compose(_manifest(), _write(tmp_path, data))


# None is in VALID
@pytest.mark.parametrize("volume", [{}, {"driver": "local"}, {"labels": {"a": "b"}}])
def test_local_volume_allowed(tmp_path, volume):
    data = _with(lambda d: d["volumes"].__setitem__("data", volume))
    check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize(
    "network",
    [None, {}, {"internal": True}, {"labels": ["a=b"]}],  # bridge is in VALID
)
def test_bridge_network_allowed(tmp_path, network):
    data = _with(lambda d: d["networks"].__setitem__("backend", network))
    check_compose(_manifest(), _write(tmp_path, data))


def test_explicit_compose_file_is_checked(tmp_path):
    (tmp_path / "stack.yml").write_text(yaml.safe_dump(VALID))
    names = check_compose(_manifest(), tmp_path, tmp_path / "stack.yml")
    assert sorted(names) == ["agent", "db", "worker"]
    (tmp_path / "stack.yml").write_text(yaml.safe_dump(_svc("privileged", True)))
    with pytest.raises(DockerError, match="privileged"):
        check_compose(_manifest(), tmp_path, tmp_path / "stack.yml")


# ── hardening: YAML limits; tags and digests ──


def test_alias_in_compose_rejected(tmp_path):
    from .test_arena_manifest import ALIAS_BOMB

    with pytest.raises(DockerError, match="alias|anchor"):
        check_compose(_manifest(), _write(tmp_path, ALIAS_BOMB))


def test_anchor_and_merge_key_rejected(tmp_path):
    text = "x-base: &base\n  image: busybox\nservices:\n  agent:\n    <<: *base\n"
    with pytest.raises(DockerError, match="alias|anchor"):
        check_compose(_manifest(), _write(tmp_path, text))


def test_deeply_nested_compose_is_a_clean_error(tmp_path):
    text = "services:\n  agent:\n    image: x\nx-deep: " + "[" * 20000 + "]" * 20000 + "\n"
    with pytest.raises(DockerError):
        check_compose(_manifest(), _write(tmp_path, text))


def test_oversize_compose_rejected(tmp_path):
    text = yaml.safe_dump(VALID) + "#" + "x" * (300 * 1024) + "\n"
    with pytest.raises(DockerError, match="too large"):
        check_compose(_manifest(), _write(tmp_path, text))


DIGEST = "@sha256:" + "0123456789abcdef" * 4


def _pinned(compose: dict) -> dict:
    data = copy.deepcopy(compose)
    for spec in data["services"].values():
        if "@sha256:" not in spec["image"]:
            spec["image"] = spec["image"].split(":")[0] + DIGEST
    return data


def test_compose_images_may_use_tags_or_digests(tmp_path):
    # Digests come from the catalog index (checked at pull/run time), not the compose file.
    assert "db" in check_compose(_manifest(), _write(tmp_path, VALID))
    services = checked_services(_manifest(), _write(tmp_path, _pinned(VALID)))
    assert services["agent"]["image"] == "ghcr.io/example/arena-agent" + DIGEST


# ── environment entries that would read the compose process environment ──


@pytest.mark.parametrize(
    "environment",
    [["HOME"], ["PLAIN=1", "AWS_SECRET_ACCESS_KEY"], {"HOME": None}, {"OK": "1", "PATH": None}],
)
def test_env_passthrough_of_undeclared_names_rejected(tmp_path, environment):
    data = _svc("environment", environment)
    with pytest.raises(DockerError, match="environment.*(HOME|AWS_SECRET_ACCESS_KEY|PATH)"):
        check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize("environment", [["ECHO_PREFIX"], {"ECHO_PREFIX": None}])
def test_env_passthrough_of_declared_names_allowed(tmp_path, environment):
    data = _svc("environment", environment, service="db")
    assert "db" in check_compose(_manifest(), _write(tmp_path, data))


@pytest.mark.parametrize("environment", [[123], ["=x"], {"": "x"}, "HOME"])
def test_env_odd_entries_rejected(tmp_path, environment):
    # "HOME": not a list or mapping
    with pytest.raises(DockerError, match="environment"):
        check_compose(_manifest(), _write(tmp_path, _svc("environment", environment)))


def test_checked_services_returns_the_specs(tmp_path):
    services = checked_services(_manifest(), _write(tmp_path, VALID))
    assert services["agent"]["mem_limit"] == "512m"
    assert set(services) == {"agent", "db", "worker"}


# ── the networks a compose file declares ──


def test_network_names_are_the_top_level_networks(tmp_path):
    from humanbound_cli.arena.compose_safety import network_names

    path = tmp_path / "docker-compose.yml"
    path.write_text("services:\n  a:\n    image: x\n")
    assert network_names(tmp_path) == []
    path.write_text("services: {}\nnetworks:\n")
    assert network_names(tmp_path) == []
    path.write_text("services: {}\nnetworks:\n  front:\n  back:\n    internal: false\n  7: {}\n")
    assert network_names(tmp_path) == ["front", "back"]
    other = tmp_path / "other.yml"
    other.write_text("networks: {only: {}}\n")
    assert network_names(tmp_path, other) == ["only"]
    path.write_text("- not\n- a mapping\n")
    assert network_names(tmp_path) == []


def test_network_names_of_an_unreadable_file(tmp_path):
    from humanbound_cli.arena.compose_safety import DockerError, network_names

    with pytest.raises(DockerError, match="cannot read"):
        network_names(tmp_path)
    (tmp_path / "docker-compose.yml").write_text("networks: &a {x: *a}\n")
    with pytest.raises(DockerError, match="anchors"):
        network_names(tmp_path)
