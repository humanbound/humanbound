# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the container baseline (humanbound_cli.arena.baseline). Pure: no Docker."""

from __future__ import annotations

import copy

import pytest

from humanbound_cli.arena import baseline
from humanbound_cli.arena.baseline import (
    AGENT,
    RULES,
    BaselineError,
    Inspected,
    Rule,
    Violation,
    container_name,
)
from humanbound_cli.arena.compose_safety import DockerError

NAME = "arena-abc123def456-echo"


def good(name: str = NAME, **changes) -> dict:
    """What `docker inspect` reports for a container that meets the baseline.

    `changes` use "__" for nesting (HostConfig__Privileged=True); the value DROP removes
    the key."""
    info = {
        "Id": "0123456789abcdef0123456789abcdef",
        "Name": f"/{name}",
        "Config": {"User": "65534", "Labels": {}},
        "Mounts": [],
        "HostConfig": {
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges"],
            "PidMode": "",
            "IpcMode": "private",
            "NetworkMode": name,
            "UTSMode": "",
            "UsernsMode": "",
            "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]},
            "PublishAllPorts": False,
            "Devices": [],
        },
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49153"}]},
            "Networks": {name: {"IPAddress": "172.20.0.2"}},
        },
    }
    for path, value in changes.items():
        *parents, leaf = path.split("__")
        node = info
        for key in parents:
            node = node[key]
        if value is DROP:
            node.pop(leaf, None)
        else:
            node[leaf] = value
    return info


DROP = object()


def network(name: str = NAME, **fields) -> dict:
    """What `docker network inspect` reports for a network with no route out."""
    return {"Name": name, "Driver": "bridge", "Internal": True, **fields}


def check(containers, networks=None) -> list[Violation]:
    """baseline.check; without `networks`, every network the containers are on is one with
    no route out."""
    if networks is None and isinstance(containers, (list, tuple)):
        names: dict[str, None] = {}
        for c in containers:
            settings = c.get("NetworkSettings") if isinstance(c, dict) else None
            attached = settings.get("Networks") if isinstance(settings, dict) else None
            for name in attached if isinstance(attached, dict) else ():
                names[name] = None
        networks = [network(name) for name in names]
    return baseline.check(containers, networks)


def only(violations: list[Violation]) -> Violation:
    assert len(violations) == 1, [str(v) for v in violations]
    return violations[0]


# ── the rules and their order ──


def test_rules_are_an_ordered_list_with_unique_ids():
    """Rule ids are stable identifiers: scripts match on them (hb arena check, --json), and
    the docs list them. Renaming, removing or reordering one is a breaking change."""
    assert isinstance(RULES, list)
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    assert ids == [
        "inspect-data",
        "non-root",
        "not-privileged",
        "capabilities",
        "no-new-privileges",
        "host-namespaces",
        "host-mounts",
        "loopback-ports",
        "internal-networks",
    ]
    for rule in RULES:
        assert isinstance(rule, Rule)
        assert rule.description.strip()


def test_a_container_that_meets_the_baseline_has_no_violations():
    assert check([good()]) == []


def test_compose_style_container_meets_the_baseline():
    # compose writes the option with a value; a side service publishes nothing; named volumes
    # and tmpfs are not host paths; a user:group pair that isn't root.
    info = good(
        HostConfig__SecurityOpt=["no-new-privileges:true"],
        HostConfig__PortBindings={},
        NetworkSettings__Ports={"8001/tcp": None},
        Mounts=[
            {"Type": "volume", "Name": "data", "Source": "/var/lib/docker/volumes/data/_data"},
            {"Type": "tmpfs", "Destination": "/tmp"},
        ],
        Config__User="1000:1000",
    )
    assert check([info]) == []


# ── non-root ──


@pytest.mark.parametrize("user", ["1000:0", "node", "app:app", " 1001 "])
def test_non_root_users_pass(user):
    assert check([good(Config__User=user)]) == []


@pytest.mark.parametrize("user", ["", "root", "0", "0:0", "root:root", "00", "ROOT", " 0 "])
def test_root_users_fail(user):
    v = only(check([good(Config__User=user)]))
    assert (v.container, v.rule) == (NAME, "non-root")
    assert "root" in v.message


@pytest.mark.parametrize(
    "changes",
    [{"Config__User": DROP}, {"Config": DROP}, {"Config": "x"}, {"Config__User": 0}],
)
def test_unconfirmable_user_fails(changes):
    v = only(check([good(**changes)]))
    assert v.rule == "non-root"


# ── privileged ──


def test_privileged_fails():
    v = only(check([good(HostConfig__Privileged=True)]))
    assert (v.rule, v.container) == ("not-privileged", NAME)
    assert "privileged" in v.message


@pytest.mark.parametrize("value", [DROP, None, "false", 0])
def test_unconfirmable_privileged_fails(value):
    assert only(check([good(HostConfig__Privileged=value)])).rule == "not-privileged"


# ── capabilities ──


@pytest.mark.parametrize("drop", [["all"], ["CAP_ALL"], ["cap_all"], ["NET_RAW", "ALL"]])
def test_dropping_all_capabilities_passes(drop):
    assert check([good(HostConfig__CapDrop=drop)]) == []


@pytest.mark.parametrize("drop", [[], None, DROP, ["NET_RAW"], "ALL", [None]])
def test_not_dropping_all_capabilities_fails(drop):
    v = only(check([good(HostConfig__CapDrop=drop)]))
    assert v.rule == "capabilities"
    assert "drop" in v.message


def test_adding_an_empty_capability_list_passes():
    assert check([good(HostConfig__CapAdd=[])]) == []


def test_adding_capabilities_fails():
    v = only(check([good(HostConfig__CapAdd=["NET_ADMIN", "SYS_PTRACE"])]))
    assert v.rule == "capabilities"
    assert "NET_ADMIN" in v.message and "SYS_PTRACE" in v.message


@pytest.mark.parametrize("add", [DROP, "NET_ADMIN", {"a": 1}])
def test_unconfirmable_cap_add_fails(add):
    assert only(check([good(HostConfig__CapAdd=add)])).rule == "capabilities"


def test_both_capability_problems_are_reported():
    violations = check([good(HostConfig__CapDrop=[], HostConfig__CapAdd=["NET_ADMIN"])])
    assert [v.rule for v in violations] == ["capabilities", "capabilities"]


# ── no-new-privileges ──


@pytest.mark.parametrize(
    "opts",
    [
        ["no-new-privileges:true"],
        ["no-new-privileges=true"],
        ["NO-NEW-PRIVILEGES:TRUE"],
        ["seccomp=unconfined", "no-new-privileges"],
    ],
)
def test_no_new_privileges_passes(opts):
    assert check([good(HostConfig__SecurityOpt=opts)]) == []


@pytest.mark.parametrize(
    "opts",
    [
        [],
        None,
        DROP,
        ["no-new-privileges:false"],
        ["no-new-privileges=false"],
        ["no-new-privileges", "no-new-privileges:false"],
        ["label=disable"],
        "no-new-privileges",
        ["no-new-privileges-please"],
    ],
)
def test_missing_or_disabled_no_new_privileges_fails(opts):
    v = only(check([good(HostConfig__SecurityOpt=opts)]))
    assert v.rule == "no-new-privileges"


# ── host namespaces ──


@pytest.mark.parametrize("mode", ["PidMode", "IpcMode", "NetworkMode", "UTSMode", "UsernsMode"])
def test_sharing_a_host_namespace_fails(mode):
    v = only(check([good(**{f"HostConfig__{mode}": "host"})]))
    assert v.rule == "host-namespaces"
    assert "host" in v.message


@pytest.mark.parametrize("mode", ["PidMode", "IpcMode", "NetworkMode"])
def test_sharing_another_containers_namespace_fails(mode):
    v = only(check([good(**{f"HostConfig__{mode}": "container:abc123"})]))
    assert v.rule == "host-namespaces"
    assert "container:abc123" in v.message


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        ("IpcMode", "shareable"),
        ("IpcMode", "none"),
        ("NetworkMode", "bridge"),
        ("NetworkMode", "default"),
        ("NetworkMode", "none"),
    ],
)
def test_private_namespaces_pass(mode, value):
    assert check([good(**{f"HostConfig__{mode}": value})]) == []


@pytest.mark.parametrize("mode", ["PidMode", "IpcMode", "NetworkMode", "UTSMode", "UsernsMode"])
def test_unconfirmable_namespace_fails(mode):
    assert only(check([good(**{f"HostConfig__{mode}": DROP})])).rule == "host-namespaces"
    assert only(check([good(**{f"HostConfig__{mode}": 5})])).rule == "host-namespaces"


# ── host mounts ──


@pytest.mark.parametrize("kind", ["bind", "npipe"])
def test_host_mounts_fail(kind):
    mount = {"Type": kind, "Source": "/some/host/dir", "Destination": "/data"}
    v = only(check([good(Mounts=[mount])]))
    assert v.rule == "host-mounts"
    assert "/some/host/dir" in v.message


def test_null_mounts_pass():
    assert check([good(Mounts=None)]) == []


@pytest.mark.parametrize("mounts", [DROP, "x", [None], [{"Source": "/x"}]])
def test_unconfirmable_mounts_fail(mounts):
    assert only(check([good(Mounts=mounts)])).rule == "host-mounts"


def test_host_devices_fail():
    device = {"PathOnHost": "/dev/kvm", "PathInContainer": "/dev/kvm"}
    v = only(check([good(HostConfig__Devices=[device])]))
    assert v.rule == "host-mounts"
    assert "/dev/kvm" in v.message


# ── published ports ──


@pytest.mark.parametrize("ip", ["0.0.0.0", "::", "", "192.168.1.10", "::1", None])
def test_publishing_off_loopback_fails(ip):
    ports = {"8080/tcp": [{"HostIp": ip, "HostPort": "49153"}]}
    v = only(check([good(NetworkSettings__Ports=ports, HostConfig__PortBindings={})]))
    assert v.rule == "loopback-ports"
    assert "8080/tcp" in v.message


def test_dual_stack_publish_reports_each_address():
    ports = {
        "8080/tcp": [
            {"HostIp": "0.0.0.0", "HostPort": "49153"},
            {"HostIp": "::", "HostPort": "49153"},
        ]
    }
    violations = check([good(NetworkSettings__Ports=ports, HostConfig__PortBindings={})])
    assert [v.rule for v in violations] == ["loopback-ports", "loopback-ports"]
    assert "0.0.0.0" in violations[0].message and "::" in violations[1].message


def test_configured_bindings_are_checked_too():
    # A stopped container publishes nothing, but its configuration still says where it would.
    bindings = {"8080/tcp": [{"HostIp": "", "HostPort": ""}]}
    v = only(check([good(NetworkSettings__Ports={}, HostConfig__PortBindings=bindings)]))
    assert v.rule == "loopback-ports"
    assert "all interfaces" in v.message


def test_the_same_binding_is_reported_once():
    ports = {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "49153"}]}
    bindings = {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": ""}]}
    only(check([good(NetworkSettings__Ports=ports, HostConfig__PortBindings=bindings)]))


def test_publish_all_fails():
    v = only(check([good(HostConfig__PublishAllPorts=True)]))
    assert v.rule == "loopback-ports"


@pytest.mark.parametrize("ports", [None, {}, {"8080/tcp": None}, {"8080/tcp": []}])
def test_publishing_nothing_passes(ports):
    assert check([good(NetworkSettings__Ports=ports, HostConfig__PortBindings=None)]) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"NetworkSettings": DROP},
        {"NetworkSettings": "x"},
        {"NetworkSettings__Ports": ["8080/tcp"]},
        {"NetworkSettings__Ports": {"8080/tcp": "0.0.0.0"}},
        {"NetworkSettings__Ports": {"8080/tcp": ["0.0.0.0"]}},
        {"HostConfig__PortBindings": "x"},
    ],
)
def test_unconfirmable_ports_fail(changes):
    assert any(v.rule == "loopback-ports" for v in check([good(**changes)]))


# ── malformed input ──


@pytest.mark.parametrize("hostconfig", [DROP, None, "x", []])
def test_missing_hostconfig_fails_every_hostconfig_rule_without_raising(hostconfig):
    violations = check([good(HostConfig=hostconfig)])
    rules = {v.rule for v in violations}
    assert {"not-privileged", "capabilities", "no-new-privileges", "host-namespaces"} <= rules


@pytest.mark.parametrize(
    "garbage",
    [{}, {"Name": 5}, {"Name": None, "Id": None}, {"HostConfig": {"CapDrop": [["ALL"]]}}],
)
def test_garbage_never_raises_and_always_fails(garbage):
    violations = check([garbage])
    assert violations
    for v in violations:
        assert isinstance(v.container, str) and v.container


def test_non_dict_entries_are_violations():
    violations = check([good(), "nope", None])
    assert [(v.container, v.rule) for v in violations] == [
        (AGENT, "inspect-data"),
        (AGENT, "inspect-data"),
    ]


def test_no_containers_is_a_violation():
    v = only(check([]))
    assert (v.container, v.rule) == (AGENT, "inspect-data")
    assert "no containers" in v.message


@pytest.mark.parametrize("value", [None, "x", {"a": 1}])
def test_not_a_list_is_a_violation(value):
    assert only(check(value)).rule == "inspect-data"


def test_check_does_not_modify_its_input():
    containers = [good(Config__User="root"), good("other", HostConfig__Privileged=True)]
    before = copy.deepcopy(containers)
    check(containers)
    assert containers == before


# ── naming ──


def test_container_name():
    assert container_name(good("x")) == "x"
    assert container_name({"Id": "0123456789abcdef"}) == "0123456789ab"
    assert container_name({}) == "?"
    assert container_name({}, 2) == "container 3"
    assert container_name("nope") == "?"


# ── several containers (a compose agent) ──


def test_every_container_of_the_agent_is_checked_and_grouped():
    agent = good("arena-x-duo-agent-1")
    backend = good(
        "arena-x-duo-backend-1",
        Config__User="",
        HostConfig__PortBindings={},
        NetworkSettings__Ports={"8080/tcp": None},
        Mounts=[{"Type": "bind", "Source": "/etc", "Destination": "/host-etc"}],
    )
    cache = good("arena-x-duo-cache-1", HostConfig__Privileged=True)
    violations = check([agent, backend, cache])
    assert [(v.container, v.rule) for v in violations] == [
        ("arena-x-duo-backend-1", "non-root"),
        ("arena-x-duo-backend-1", "host-mounts"),
        ("arena-x-duo-cache-1", "not-privileged"),
    ]


def test_violation_rendering():
    v = Violation("c1", "non-root", "runs as root (Config.User is empty)")
    assert str(v) == "c1: non-root: runs as root (Config.User is empty)"
    assert v.as_dict() == {
        "container": "c1",
        "rule": "non-root",
        "message": "runs as root (Config.User is empty)",
    }


# ── agent-level rules fit the same list ──


def test_an_agent_level_rule_needs_no_change_to_callers(monkeypatch):
    """A future rule over the whole agent (e.g. its network has no route out) is one more
    entry in RULES; check() and its callers stay the same."""

    def at_most_two(agent: Inspected):
        if len(agent.containers) > 2:
            yield Violation(AGENT, "at-most-two", f"has {len(agent.containers)} containers")

    monkeypatch.setattr(
        baseline, "RULES", [*RULES, Rule("at-most-two", "At most two containers.", at_most_two)]
    )
    assert check([good("a"), good("b")]) == []
    v = only(check([good("a"), good("b"), good("c")]))
    assert (v.container, v.rule) == (AGENT, "at-most-two")


def test_a_rule_that_raises_is_a_violation_not_a_crash(monkeypatch):
    def broken(agent: Inspected):
        raise KeyError("boom")

    monkeypatch.setattr(baseline, "RULES", [*RULES, Rule("broken", "Broken.", broken)])
    v = only(check([good()]))
    assert (v.container, v.rule) == (AGENT, "broken")
    assert "could not be checked" in v.message


# ── BaselineError ──


def test_baseline_error_lists_one_violation_per_line():
    violations = [
        Violation("c1", "non-root", "runs as root (Config.User is empty)"),
        Violation("c2", "not-privileged", "runs privileged"),
    ]
    err = BaselineError("echo", violations)
    assert isinstance(err, DockerError)
    assert err.agent_id == "echo"
    assert err.violations == violations
    lines = str(err).splitlines()
    assert "echo" in lines[0] and "container baseline" in lines[0]
    assert lines[1:] == [str(v) for v in violations]
    text = str(err).lower()
    assert "safe" not in text and "secure" not in text


# ── internal-networks ──


def test_a_network_with_a_route_out_is_a_violation():
    v = only(check([good()], [network(Internal=False)]))
    assert (v.container, v.rule) == (NAME, "internal-networks")
    assert v.message == f"is on the network {NAME}, which has a route out (Internal is false)"


def test_every_network_of_every_container_is_checked():
    agent = good("agent", NetworkSettings__Networks={"front": {}, "back": {}})
    db = good("db", NetworkSettings__Networks={"back": {}, "bridge": {}})
    networks = [network("front"), network("back"), network("bridge", Internal=False)]
    v = only(check([agent, db], networks))
    assert (v.container, v.rule) == ("db", "internal-networks")
    assert "the network bridge" in v.message


def test_a_network_without_data_cannot_be_confirmed():
    v = only(check([good()], []))
    assert v.rule == "internal-networks"
    assert v.message == f"cannot confirm that the network {NAME} has no route out: no data"
    assert only(baseline.check([good()])).rule == "internal-networks"  # networks left out


@pytest.mark.parametrize("value", [None, "true", 1, 0, "", DROP])
def test_only_a_true_internal_flag_counts(value):
    data = network()
    if value is DROP:
        del data["Internal"]
    else:
        data["Internal"] = value
    v = only(check([good()], [data]))
    assert v.rule == "internal-networks"
    assert v.message.startswith(f"cannot confirm that the network {NAME} has no route out")


@pytest.mark.parametrize("attached", [DROP, None, [], "arena", 5])
def test_unreadable_networks_of_a_container_cannot_be_confirmed(attached):
    v = only(check([good(NetworkSettings__Networks=attached)], [network()]))
    assert v.rule == "internal-networks"
    assert v.message.startswith("cannot confirm its networks: NetworkSettings.Networks is")


def test_a_container_on_no_network_meets_the_rule():
    assert check([good(NetworkSettings__Networks={})], []) == []


@pytest.mark.parametrize("networks", ["nope", 5, [None, "x", 7, {"Internal": True}, {"Name": 3}]])
def test_malformed_network_data_is_never_an_exception(networks):
    v = only(baseline.check([good()], networks))
    assert v.rule == "internal-networks"


def test_network_data_for_other_networks_is_ignored():
    assert check([good()], [network(), network("other", Internal=False)]) == []
