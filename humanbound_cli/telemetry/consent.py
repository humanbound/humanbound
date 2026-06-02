# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Consent and disable-condition logic for telemetry.

Decision is computed once per process and cached. Use `reset_cache()` in tests.
"""

import json
import os
import sys
import threading
import uuid
from pathlib import Path

from .. import config


def _state_file() -> Path:
    """Path to the telemetry state file. Resolves at call time so tests can monkeypatch HOME."""
    return config.get_humanbound_dir() / "telemetry.json"


_CI_ENV_VARS = (
    "CI",
    "GITHUB_ACTIONS",
    "BUILDKITE",
    "JENKINS_HOME",
    "TF_BUILD",
    "GITLAB_CI",
    "CIRCLECI",
    "TRAVIS",
)

_cache_lock = threading.Lock()
_cached_enabled: bool | None = None
_cached_reason: str | None = None


def _read_state() -> dict:
    """Return the parsed state dict, or {} if file is missing/unreadable/invalid."""
    f = _state_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    """Persist the state dict atomically-ish with mode 0600."""
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state) + "\n")
    f.chmod(0o600)


def _compute() -> tuple[bool, str | None]:
    """Return (enabled, reason_if_disabled). Order matters — first match wins."""
    if os.environ.get("DO_NOT_TRACK") == "1":
        return False, "DO_NOT_TRACK=1"
    if os.environ.get("HB_TELEMETRY_DISABLED") == "1":
        return False, "HB_TELEMETRY_DISABLED=1"
    if _read_state().get("opted_out") is True:
        return False, "user opt-out (hb telemetry disable)"
    for v in _CI_ENV_VARS:
        if os.environ.get(v):
            return False, f"CI detected ({v})"
    if os.environ.get("HUMANBOUND_DEV") == "1":
        return False, "dev mode (HUMANBOUND_DEV=1)"
    if not sys.stdout.isatty():
        return False, "non-TTY stdout"
    return True, None


def _populate_cache() -> None:
    global _cached_enabled, _cached_reason
    with _cache_lock:
        if _cached_enabled is None:
            enabled, reason = _compute()
            _cached_enabled = enabled
            _cached_reason = reason


def is_enabled() -> bool:
    """Return True if telemetry will send. Caches result for the process lifetime."""
    _populate_cache()
    return bool(_cached_enabled)


def disabled_reason() -> str | None:
    """If disabled, returns a short human-readable reason. Else None."""
    _populate_cache()
    return _cached_reason


def reset_cache() -> None:
    """Test-only: clear cached decision so the next call re-computes."""
    global _cached_enabled, _cached_reason
    with _cache_lock:
        _cached_enabled = None
        _cached_reason = None


def get_distinct_id_and_new_flag() -> tuple[str, bool]:
    """Return (distinct_id, was_just_created).

    If the state file is missing or has no `id`, generate a fresh UUID,
    persist it (with `opted_out: false`), and report it as new. The
    `was_just_created` flag drives the `install` event.
    """
    state = _read_state()
    existing = state.get("id")
    if existing:
        return existing, False

    new_id = f"tlm_{uuid.uuid4()}"
    state["id"] = new_id
    state.setdefault("opted_out", False)
    _write_state(state)
    return new_id, True


def write_opt_out() -> None:
    """Mark the user as opted out. UUID is preserved across opt-out cycles."""
    state = _read_state()
    if not state.get("id"):
        state["id"] = f"tlm_{uuid.uuid4()}"
    state["opted_out"] = True
    _write_state(state)


def clear_opt_out() -> None:
    """Mark the user as opted back in. UUID is preserved."""
    state = _read_state()
    if not state.get("id"):
        state["id"] = f"tlm_{uuid.uuid4()}"
    state["opted_out"] = False
    _write_state(state)
