# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The telemetry part of a saved conversation log (`meta.telemetry` in logs.jsonl).

Besides the tool names, it keeps every tool execution with its arguments, result and turn
(what a benchmark needs to check a ground truth such as `tool_called {name, arg_regex}`)
and, when the engine has it, the per-turn metadata the integration returned (for any
`per_turn` telemetry config, not only arena), minus the tool calls `tool_executions`
already holds. Values are made JSON-safe (NaN and infinities become null) and capped (long
strings, long lists, dicts with many keys) so logs stay a reasonable size.
"""

from __future__ import annotations

import math
from typing import Any

MAX_STRING = 4000
MAX_DEPTH = 20
MAX_ITEMS = 200
MAX_KEYS = 200
TRUNCATED = "…[truncated {n} chars]"
MORE_ITEMS = "…[{n} more items]"
MORE_KEYS_KEY = "…"
MORE_KEYS = "[{n} more keys]"
# Per-turn metadata keys that duplicate `tool_executions` (the arena gateway's names).
TURN_TOOL_KEYS = ("tool_calls", "tool_calls_raw")


def cap(value: Any, limit: int = MAX_STRING, _depth: int = 0) -> Any:
    """A JSON-safe copy of `value`: strings longer than `limit` cut, lists cut to MAX_ITEMS
    and dicts to MAX_KEYS keys (each with a marker), NaN and infinities as None."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + TRUNCATED.format(n=len(value) - limit)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if _depth >= MAX_DEPTH:
        return "…[nested too deep]"
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i == MAX_KEYS:
                out[MORE_KEYS_KEY] = MORE_KEYS.format(n=len(value) - MAX_KEYS)
                break
            out[cap(str(k), limit)] = cap(v, limit, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return _cap_items(value, lambda v: cap(v, limit, _depth + 1))
    return cap(str(value), limit, _depth + 1)


def _cap_items(items, convert) -> list:
    out = [convert(v) for v in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        out.append(MORE_ITEMS.format(n=len(items) - MAX_ITEMS))
    return out


def _turn_to_save(turn: Any) -> Any:
    if not isinstance(turn, dict):
        return turn
    metadata = turn.get("metadata")
    if isinstance(metadata, dict):
        metadata = {k: v for k, v in metadata.items() if k not in TURN_TOOL_KEYS}
        return {**turn, "metadata": metadata}
    return turn


def telemetry_meta(thread_id: str, telemetry_data: dict | None) -> dict:
    """`{"telemetry": {...}}` for a conversation's log meta, or {} without telemetry."""
    if not telemetry_data:
        return {}
    executions = [t for t in telemetry_data.get("tool_executions") or [] if isinstance(t, dict)]
    usage = telemetry_data.get("resource_usage") or {}
    telemetry = {
        "trace_id": thread_id,
        "tools": _cap_items(executions, lambda t: cap(t.get("tool_name", ""))),
        "tokens": cap(usage.get("tokens_used", 0)),
        "api_calls": cap(usage.get("api_calls_count", 0)),
        "tool_executions": _cap_items(
            executions,
            lambda t: {
                "turn": cap(t.get("turn", 0)),
                "tool_name": cap(t.get("tool_name", "")),
                "parameters": cap(t.get("parameters", {})),
                "result": cap(t.get("result", "")),
            },
        ),
    }
    turns = telemetry_data.get("turns")
    if turns:
        items = turns if isinstance(turns, list) else [turns]
        telemetry["turns"] = cap([_turn_to_save(t) for t in items if isinstance(t, dict)])
    return {"telemetry": telemetry}
