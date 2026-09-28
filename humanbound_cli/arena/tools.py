# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tool-call normalization for whitebox telemetry.

Agents report tool calls in their own shapes. The engine's telemetry reads `name`,
`parameters` and `result` per item, so the gateway normalizes every item to
`{"name", "parameters", "result"}` before handing it on.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["normalize_tool_calls"]

_NAME_KEYS = ("name", "tool", "tool_name")
_PARAM_KEYS = ("parameters", "args", "arguments", "input")
_RESULT_KEYS = ("result", "output", "content")
_CALL_TYPES = frozenset({"call", "tool_call"})
_RESULT_TYPES = frozenset({"result", "tool_result"})


def _first(item: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _parameters(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        return parsed if isinstance(parsed, dict) else value
    return value


def normalize_tool_calls(items: Any) -> list[dict]:
    """Normalize an agent's tool-call list to `[{"name", "parameters", "result"}]`.

    Accepted aliases: name ← name|tool|tool_name; parameters ← parameters|args|arguments|input
    (a JSON-object string is parsed); result ← result|output|content. A result entry
    (`type` result/tool_result) right after a call entry (`type` call/tool_call) of the same
    name (or with no name) is merged into it. Non-dict items are dropped.
    """
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    pending: dict | None = None  # the last call entry still waiting for its result
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").lower()
        name = _first(item, _NAME_KEYS)
        name = "" if name is None else str(name)
        result = _first(item, _RESULT_KEYS)
        if kind in _RESULT_TYPES and pending is not None and name in ("", pending["name"]):
            pending["result"] = "" if result is None else result
            pending = None
            continue
        entry = {
            "name": name,
            "parameters": _parameters(_first(item, _PARAM_KEYS)),
            "result": "" if result is None else result,
        }
        out.append(entry)
        pending = entry if kind in _CALL_TYPES and result is None else None
    return out
