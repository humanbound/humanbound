# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb test --target arena://<id>`: turn a running arena agent into an A2A bot config.

`resolve_target` raises only `TargetError`, with a message the CLI can print as-is.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from ..agent_yaml import scope_from_agent_yaml
from . import catalog, daemon, runtime
from .manifest import AGENT_ID_RE
from .paths import auth_headers

__all__ = [
    "ARENA_SCHEME",
    "ArenaTarget",
    "TargetError",
    "bot_config",
    "enforce_baseline",
    "forget_via_gateway",
    "is_arena_target",
    "parse_target",
    "reset_via_gateway",
    "resolve_target",
]

ARENA_SCHEME = "arena://"
SCOPE_FILE = "scope.yaml"
RESET_TIMEOUT_S = 300
FORGET_TIMEOUT_S = 10


class TargetError(RuntimeError):
    """An arena target could not be resolved or prepared."""


@dataclass(frozen=True)
class ArenaTarget:
    agent_id: str
    gateway: str
    bot_config: dict
    scope_path: Path
    context: str
    # Per-turn tool calls reach the judge only from an http agent with response.tool_calls.
    whitebox: bool
    version: str
    # Installed from the default catalog (telemetry names only those agents).
    default_catalog: bool = True
    # What runtime.stop needs to stop the agent (image | compose, and its cached files).
    kind: str = "image"
    agent_dir: Path | None = None


def is_arena_target(value: object) -> bool:
    return isinstance(value, str) and value.startswith(ARENA_SCHEME)


def parse_target(value: str) -> str:
    """The agent id in `arena://<agent-id>`."""
    agent_id = value[len(ARENA_SCHEME) :] if is_arena_target(value) else ""
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise TargetError(f"invalid arena target {value!r}; expected arena://<agent-id>")
    return agent_id


def bot_config(
    agent_id: str, gateway: str, *, whitebox: bool = True, token: str | None = None
) -> dict:
    """An A2A bot config that talks to `agent_id` through the gateway.

    It carries the gateway token (default: this owner's) in an Authorization header, so it
    is a secret: the engine never saves its integration config. With `whitebox`, per-turn
    tool calls are read from the gateway's metadata; without it there is no telemetry
    block, so the engine runs blackbox.
    """
    config = {
        "streaming": None,
        "chat_completion": {
            "endpoint": f"{gateway.rstrip('/')}/a2a/{agent_id}",
            "headers": {"A2A-Version": "1.0", **auth_headers(token)},
            "payload": {
                "jsonrpc": "2.0",
                "id": "$UUID",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": "ROLE_USER",
                        "messageId": "$UUID",
                        "contextId": "$humanbound_conversation_id",
                        "parts": [{"text": "$PROMPT"}],
                    }
                },
            },
        },
    }
    if whitebox:
        config["telemetry"] = {
            "mode": "per_turn",
            "extraction_map": {
                "metadata_path": "result.message.metadata.humanbound",
                "tool_executions": "tool_calls",
            },
        }
    return config


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _is_whitebox(manifest) -> bool:
    integration = manifest.integration
    return (
        integration.type == "http"
        and integration.response is not None
        and bool(integration.response.tool_calls)
    )


def resolve_target(
    value: str,
    *,
    list_running: Callable[[], list[runtime.RunningAgent]] = runtime.list_running,
    installed: Callable[..., tuple | None] = catalog.installed,
    ensure_gateway: Callable[[], str] = daemon.ensure_running,
) -> ArenaTarget:
    agent_id = parse_target(value)
    try:
        agent = next((a for a in list_running() if a.id == agent_id), None)
        if agent is None:
            raise TargetError(catalog.not_running_message(agent_id))
        found = installed(agent_id, agent.version or None)
        if found is None:
            raise TargetError(
                f"{agent_id} is running but its manifest isn't cached → hb arena pull {agent_id}"
            )
        manifest, agent_dir = found
        scope = scope_from_agent_yaml(manifest.agent_yaml())
        scope_path = Path(agent_dir) / SCOPE_FILE
        _write_atomic(scope_path, yaml.safe_dump(scope, sort_keys=False, allow_unicode=True))
        gateway = ensure_gateway()
        whitebox = _is_whitebox(manifest)
        config = bot_config(agent_id, gateway, whitebox=whitebox)
    except (runtime.DockerError, daemon.GatewayError, ValueError) as e:
        # ValueError covers ManifestError and a bad HB_ARENA_PORT.
        raise TargetError(str(e)) from e
    except OSError as e:
        raise TargetError(f"cannot prepare arena target {agent_id}: {e}") from e
    return ArenaTarget(
        agent_id=agent_id,
        gateway=gateway,
        bot_config=config,
        scope_path=scope_path,
        context=manifest.context,
        whitebox=whitebox,
        version=manifest.version,
        default_catalog=catalog.is_trusted(Path(agent_dir)),
        kind=agent.kind,
        agent_dir=Path(agent_dir),
    )


def enforce_baseline(
    t: ArenaTarget,
    *,
    check: Callable[[str], list] | None = None,
    stop: Callable[..., None] | None = None,
) -> None:
    """Refuse to test an agent whose containers don't meet the container baseline: stop it
    and raise TargetError listing the violations, one per line. A check that can't run
    (Docker down) raises TargetError too, without stopping anything."""
    check = check or runtime.check_baseline
    stop = stop or runtime.stop
    try:
        violations = check(t.agent_id)
    except runtime.DockerError as e:
        raise TargetError(
            f"could not check {t.agent_id}'s containers against the container baseline: {e}"
        ) from e
    if not violations:
        return
    try:
        stop(t.agent_id, t.kind, agent_dir=t.agent_dir)
    except runtime.DockerError:
        pass
    raise TargetError(str(runtime.BaselineError(t.agent_id, violations)))


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return resp.text.strip() or f"HTTP {resp.status_code}"


def reset_via_gateway(agent_id: str, gateway: str) -> None:
    """Reset the agent to a clean state through the gateway (drops its conversations too)."""
    url = f"{gateway.rstrip('/')}/arena/v1/agents/{agent_id}/reset"
    try:
        resp = httpx.post(
            url, json={}, headers=auth_headers(), timeout=RESET_TIMEOUT_S, trust_env=False
        )
    except httpx.HTTPError as e:
        raise TargetError(f"could not reset {agent_id}: {e}") from e
    if not resp.is_success:
        raise TargetError(_error_message(resp))


def forget_via_gateway(agent_id: str, gateway: str) -> None:
    """Make the gateway drop `agent_id`'s conversations and re-read the running agents."""
    url = f"{gateway.rstrip('/')}/arena/v1/agents/{agent_id}/forget"
    try:
        resp = httpx.post(
            url, json={}, headers=auth_headers(), timeout=FORGET_TIMEOUT_S, trust_env=False
        )
    except httpx.HTTPError as e:
        raise TargetError(f"could not reach the gateway: {e}") from e
    if not resp.is_success:
        raise TargetError(_error_message(resp))
