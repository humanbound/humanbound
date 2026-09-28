# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The container baseline: how every container of an arena agent must be configured.

hb starts agents without privileges and out of reach of the host; this module checks, from
`docker inspect` data, that the containers really run that way (and that the image does not
run as root, and that their networks have no route out) before hb reports an agent ready or
tests it. It covers configuration only: not what an agent does, and not what it sends to
the destinations it is allowed to reach.

Pure and Docker-free: `check(containers, networks)` takes the inspect data of every
container of one agent, and of every network they are attached to, and returns the
violations. Rules are entries of the ordered list RULES. Each gets an `Inspected`
(everything inspected for one agent) and yields Violations, so a new rule is one more entry,
with no change to check() or its callers. `container_rule` turns a function of one container
into such a rule.

Inspect data is never trusted to be well formed: a field a rule needs that is missing or of
the wrong type is a violation (the rule can't be confirmed), never an exception.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .compose_safety import DockerError

__all__ = [
    "AGENT",
    "INTERNAL_NETWORKS",
    "RULES",
    "BaselineError",
    "Inspected",
    "Rule",
    "Violation",
    "check",
    "container_name",
    "container_rule",
]

# The subject of a violation found by a rule over the whole agent (not one container).
AGENT = "(agent)"
LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class Violation:
    container: str  # the container name, or AGENT for a rule over the whole agent
    rule: str  # the Rule id
    message: str  # what was found

    def __str__(self) -> str:
        return f"{self.container}: {self.rule}: {self.message}"

    def as_dict(self) -> dict[str, str]:
        return {"container": self.container, "rule": self.rule, "message": self.message}


@dataclass(frozen=True)
class Inspected:
    """Everything inspected for one agent. Rules over other objects (networks, volumes) get
    them as new fields here."""

    containers: tuple[Any, ...] = field(default_factory=tuple)
    # `docker network inspect` data of the networks the containers are attached to.
    networks: tuple[Any, ...] = field(default_factory=tuple)

    def named(self) -> Iterator[tuple[str, dict]]:
        """(name, inspect data) of each container that is a JSON object."""
        for i, container in enumerate(self.containers):
            if isinstance(container, dict):
                yield container_name(container, i), container


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    check: Callable[[Inspected], Iterable[Violation]]


class BaselineError(DockerError):
    """An agent's containers do not meet the container baseline. One violation per line."""

    def __init__(self, agent_id: str, violations: list[Violation]):
        self.agent_id = agent_id
        self.violations = list(violations)
        lines = [
            f"refusing {agent_id}: its containers do not meet the container baseline, "
            "so hb stopped it:"
        ]
        lines += [str(v) for v in self.violations]
        super().__init__("\n".join(lines))


def container_name(container: object, index: int | None = None) -> str:
    """The container's name without the leading '/', else its short id, else a placeholder."""
    if isinstance(container, dict):
        name = container.get("Name")
        if isinstance(name, str) and name.strip("/").strip():
            return name.strip().lstrip("/")
        cid = container.get("Id")
        if isinstance(cid, str) and cid.strip():
            return cid.strip()[:12]
    return f"container {index + 1}" if index is not None else "?"


def container_rule(rule_id: str, description: str):
    """Decorator: a function(container inspect data) -> iterable of messages becomes a Rule
    that runs on every container of the agent."""

    def wrap(fn: Callable[[dict], Iterable[str]]) -> Rule:
        def run(agent: Inspected) -> Iterator[Violation]:
            for name, container in agent.named():
                for message in fn(container):
                    yield Violation(name, rule_id, message)

        return Rule(rule_id, description, run)

    return wrap


# ── helpers ──

_MISSING = object()


def _get(node: object, *path: str) -> object:
    """node[path[0]][path[1]]…, or _MISSING when a key is absent or a level isn't a dict."""
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _show(value: object) -> str:
    return "missing" if value is _MISSING else repr(value)


def _cannot_confirm(what: str, field_path: str, value: object) -> str:
    if value is _MISSING:
        return f"cannot confirm {what}: {field_path} is missing"
    return f"cannot confirm {what}: {field_path} is {_show(value)}"


# ── agent-level rules ──


def _inspect_data(agent: Inspected) -> Iterator[Violation]:
    if not agent.containers:
        yield Violation(AGENT, "inspect-data", "no containers to check")
    for i, container in enumerate(agent.containers):
        if not isinstance(container, dict):
            yield Violation(
                AGENT, "inspect-data", f"entry {i + 1} of the inspect data is not an object"
            )


INTERNAL_NETWORKS = "internal-networks"


def _internal_networks(agent: Inspected) -> Iterator[Violation]:
    inspected = {
        net["Name"]: net
        for net in agent.networks
        if isinstance(net, dict) and isinstance(net.get("Name"), str)
    }
    for name, container in agent.named():
        attached = _get(container, "NetworkSettings", "Networks")
        if not isinstance(attached, dict):
            message = _cannot_confirm("its networks", "NetworkSettings.Networks", attached)
            yield Violation(name, INTERNAL_NETWORKS, message)
            continue
        for network in attached:
            internal = _get(inspected.get(network), "Internal")
            if internal is True:
                continue
            if internal is False:
                message = f"is on the network {network}, which has a route out (Internal is false)"
            elif network not in inspected:
                message = f"cannot confirm that the network {network} has no route out: no data"
            else:
                message = _cannot_confirm(
                    f"that the network {network} has no route out", "Internal", internal
                )
            yield Violation(name, INTERNAL_NETWORKS, message)


# ── container rules ──


@container_rule(
    "non-root", "Runs as a user other than root (Config.User is set and not root or 0)."
)
def _non_root(c: dict) -> Iterator[str]:
    user = _get(c, "Config", "User")
    if not isinstance(user, str):
        yield _cannot_confirm("the user", "Config.User", user)
        return
    name = user.split(":", 1)[0].strip()
    if not name:
        yield "runs as root (Config.User is empty, so the image's default, root, applies)"
    elif name.lower() == "root" or (name.isdigit() and int(name) == 0):
        yield f"runs as root (Config.User is {user!r})"


@container_rule("not-privileged", "Is not privileged (HostConfig.Privileged is false).")
def _not_privileged(c: dict) -> Iterator[str]:
    privileged = _get(c, "HostConfig", "Privileged")
    if privileged is True:
        yield "runs privileged (HostConfig.Privileged is true)"
    elif privileged is not False:
        yield _cannot_confirm("it is not privileged", "HostConfig.Privileged", privileged)


def _cap_name(value: object) -> str | None:
    return value.strip().upper() if isinstance(value, str) else None


@container_rule(
    "capabilities",
    "Drops all Linux capabilities (HostConfig.CapDrop has ALL) and adds none (CapAdd is empty).",
)
def _capabilities(c: dict) -> Iterator[str]:
    drop = _get(c, "HostConfig", "CapDrop")
    names = [_cap_name(x) for x in drop] if isinstance(drop, list) else []
    if not ({"ALL", "CAP_ALL"} & set(names)):
        shown = "missing" if drop is _MISSING else repr(drop)
        yield f"does not drop all capabilities (HostConfig.CapDrop is {shown})"
    add = _get(c, "HostConfig", "CapAdd")
    if add is None or add == []:
        return
    if not isinstance(add, list):
        yield _cannot_confirm("that no capability is added", "HostConfig.CapAdd", add)
        return
    yield f"adds capabilities ({', '.join(str(x) for x in add)})"


@container_rule(
    "no-new-privileges",
    "Can't gain new privileges (HostConfig.SecurityOpt has no-new-privileges).",
)
def _no_new_privileges(c: dict) -> Iterator[str]:
    opts = _get(c, "HostConfig", "SecurityOpt")
    if not isinstance(opts, list) and opts is not None:
        yield _cannot_confirm("no-new-privileges", "HostConfig.SecurityOpt", opts)
        return
    enabled = disabled = False
    for opt in opts or []:
        if not isinstance(opt, str):
            continue
        text = opt.strip().lower()
        if text in ("no-new-privileges", "no-new-privileges:true", "no-new-privileges=true"):
            enabled = True
        elif text.startswith(("no-new-privileges:", "no-new-privileges=")):
            disabled = True
    if disabled:
        yield f"may gain new privileges (HostConfig.SecurityOpt is {opts!r})"
    elif not enabled:
        yield "may gain new privileges (no no-new-privileges in HostConfig.SecurityOpt)"


# (field, namespace, may it join another container's namespace)
_NAMESPACES = (
    ("PidMode", "pid", False),
    ("IpcMode", "ipc", False),
    ("NetworkMode", "network", False),
    ("UTSMode", "uts", True),
    ("UsernsMode", "user", True),
)


@container_rule(
    "host-namespaces",
    "Shares no namespace with the host (Pid/Ipc/Network/UTS/UsernsMode is not host) or, for "
    "pid, ipc and network, with another container.",
)
def _host_namespaces(c: dict) -> Iterator[str]:
    for key, namespace, container_ok in _NAMESPACES:
        mode = _get(c, "HostConfig", key)
        if not isinstance(mode, str):
            yield _cannot_confirm(f"the {namespace} namespace", f"HostConfig.{key}", mode)
        elif mode.strip().lower() == "host":
            yield f"shares the host's {namespace} namespace (HostConfig.{key} is 'host')"
        elif not container_ok and mode.strip().lower().startswith("container:"):
            yield (
                f"shares the {namespace} namespace of another container "
                f"(HostConfig.{key} is {mode!r})"
            )


_HOST_MOUNT_TYPES = frozenset({"bind", "npipe"})


@container_rule(
    "host-mounts",
    "Mounts no host path (no bind or npipe mounts; named volumes and tmpfs are fine) and maps "
    "no host device.",
)
def _host_mounts(c: dict) -> Iterator[str]:
    mounts = _get(c, "Mounts")
    if mounts is not None and not isinstance(mounts, list):
        yield _cannot_confirm("that no host path is mounted", "Mounts", mounts)
    for mount in mounts if isinstance(mounts, list) else []:
        kind = mount.get("Type") if isinstance(mount, dict) else None
        if not isinstance(kind, str):
            yield _cannot_confirm("that no host path is mounted", "a Mounts entry", mount)
        elif kind.strip().lower() in _HOST_MOUNT_TYPES:
            source = mount.get("Source") or "?"
            yield f"mounts the host path {source} ({kind.strip().lower()} mount)"
    devices = _get(c, "HostConfig", "Devices")
    if devices is _MISSING or devices is None or devices == []:
        return
    if not isinstance(devices, list):
        yield _cannot_confirm("that no host device is mapped", "HostConfig.Devices", devices)
        return
    for device in devices:
        path = device.get("PathOnHost") if isinstance(device, dict) else None
        yield f"maps the host device {path or device!r}"


def _where(host_ip: object) -> str:
    if host_ip == "" or host_ip is None:
        return "all interfaces"
    return str(host_ip)


def _bindings(port_map: object, field_path: str) -> Iterator[tuple[str, object] | str]:
    """(port, HostIp) of each binding in a port map, or a message when it can't be read."""
    if port_map is None or port_map is _MISSING:
        return
    if not isinstance(port_map, dict):
        yield _cannot_confirm("where ports are published", field_path, port_map)
        return
    for port, bindings in port_map.items():
        if bindings is None:
            continue
        if not isinstance(bindings, list):
            yield _cannot_confirm(f"where {port} is published", field_path, bindings)
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                yield _cannot_confirm(f"where {port} is published", field_path, binding)
                continue
            yield str(port), binding.get("HostIp")


@container_rule(
    "loopback-ports",
    "Publishes ports on 127.0.0.1 only (NetworkSettings.Ports and HostConfig.PortBindings); "
    "publishing nothing is fine.",
)
def _loopback_ports(c: dict) -> Iterator[str]:
    settings = _get(c, "NetworkSettings")
    if not isinstance(settings, dict):
        yield _cannot_confirm("where ports are published", "NetworkSettings", settings)
        published: Iterable = ()
    else:
        published = _bindings(settings.get("Ports"), "NetworkSettings.Ports")
    configured = _bindings(_get(c, "HostConfig", "PortBindings"), "HostConfig.PortBindings")
    seen: set[tuple[str, str]] = set()
    for item in (*published, *configured):
        if isinstance(item, str):
            yield item
            continue
        port, host_ip = item
        if host_ip == LOOPBACK:
            continue
        key = (port, _where(host_ip))
        if key not in seen:
            seen.add(key)
            yield f"publishes {port} on {key[1]}, not only on {LOOPBACK}"
    if _get(c, "HostConfig", "PublishAllPorts") is True:
        yield "publishes every exposed port on all interfaces (HostConfig.PublishAllPorts)"


RULES: list[Rule] = [
    Rule(
        "inspect-data",
        "There are containers to check, and their inspect data is readable.",
        _inspect_data,
    ),
    _non_root,
    _not_privileged,
    _capabilities,
    _no_new_privileges,
    _host_namespaces,
    _host_mounts,
    _loopback_ports,
    Rule(
        INTERNAL_NETWORKS,
        "Is only on networks that have no route out (Internal is true for every network in "
        "NetworkSettings.Networks).",
        _internal_networks,
    ),
]


def check(containers: list[dict], networks: list[dict] | None = None) -> list[Violation]:
    """The violations of every rule in RULES by one agent's containers (`docker inspect` data,
    side services included) and the networks they are on (`docker network inspect` data).
    Grouped by container, in RULES order within each; problems with the agent as a whole come
    first. Never raises on malformed data."""
    items = tuple(containers) if isinstance(containers, (list, tuple)) else None
    if items is None:
        return [Violation(AGENT, "inspect-data", "the inspect data is not a list of containers")]
    agent = Inspected(items, tuple(networks) if isinstance(networks, (list, tuple)) else ())
    found: list[Violation] = []
    for rule in RULES:
        try:
            found.extend(rule.check(agent))
        except Exception as e:  # noqa: BLE001 - a rule that can't run is a failure, not a crash
            found.append(Violation(AGENT, rule.id, f"could not be checked ({type(e).__name__})"))
    order = {name: i for i, (name, _) in enumerate(agent.named())}
    return sorted(found, key=lambda v: order.get(v.container, -1))
