# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Resolve `arena://<id>` for `hb test`: an A2A bot config aimed at the gateway, plus
the agent's scope (from its embedded agent.yaml) and judge context."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from ..agent_yaml import scope_from_agent_yaml
from . import catalog, daemon, runtime
from .manifest import AGENT_ID_RE

ARENA_SCHEME = "arena://"


class TargetError(RuntimeError):
    """The arena target can't be used. The message is ready to show."""


@dataclass
class ArenaTarget:
    agent_id: str
    gateway: str
    bot_config: dict
    scope_path: Path
    context: str


def is_arena_target(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(ARENA_SCHEME)


def parse_target(value: str) -> str:
    agent_id = value[len(ARENA_SCHEME) :] if is_arena_target(value) else ""
    if not AGENT_ID_RE.match(agent_id):
        raise TargetError(f"invalid arena target {value!r}; expected arena://<agent-id>")
    return agent_id


def bot_config(agent_id: str, gateway: str) -> dict:
    """An hb bot config that speaks A2A v1.0 SendMessage to the gateway."""
    return {
        "streaming": None,
        "chat_completion": {
            "endpoint": f"{gateway}/a2a/{agent_id}",
            "headers": {"A2A-Version": "1.0"},
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
        "telemetry": {
            "mode": "per_turn",
            "extraction_map": {"metadata_path": "result.message.metadata.humanbound"},
        },
    }


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, so readers never see a partial file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def resolve_target(
    value: str,
    *,
    list_running: Callable[[], list[runtime.RunningAgent]] = runtime.list_running,
    installed: Callable[..., tuple | None] = catalog.installed,
    ensure_gateway: Callable[[], str] = daemon.ensure_running,
) -> ArenaTarget:
    agent_id = parse_target(value)
    try:
        agents = list_running()
    except runtime.DockerError as e:
        raise TargetError(str(e)) from None
    running = next((a for a in agents if a.id == agent_id), None)
    if running is None:
        raise TargetError(f"{agent_id} is not running → hb arena run {agent_id}")
    found = installed(agent_id, running.version)
    if found is None:
        raise TargetError(
            f"{agent_id} is running but its manifest isn't cached → hb arena pull {agent_id}"
        )
    manifest, agent_dir = found
    scope_path = Path(agent_dir) / "scope.yaml"
    _write_atomic(
        scope_path, yaml.safe_dump(scope_from_agent_yaml(manifest.agent_yaml()), sort_keys=False)
    )
    try:
        gateway = ensure_gateway()
    except daemon.GatewayError as e:
        raise TargetError(str(e)) from None
    return ArenaTarget(
        agent_id, gateway, bot_config(agent_id, gateway), scope_path, manifest.context
    )


def reset_via_gateway(agent_id: str, gateway: str) -> None:
    """Recreate the agent from its image and drop its conversations (clean run)."""
    try:
        resp = httpx.post(f"{gateway}/arena/v1/agents/{agent_id}/reset", json={}, timeout=300)
    except httpx.HTTPError as e:
        raise TargetError(f"could not reset {agent_id}: {e}") from None
    if not resp.is_success:
        raise TargetError(f"could not reset {agent_id}: {_error_message(resp)}")


def _error_message(resp: httpx.Response) -> str:
    """The gateway's `error.message` when the body is its JSON error, else the raw text."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message:
        return message
    return resp.text[:300]
