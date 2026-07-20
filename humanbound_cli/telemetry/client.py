# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""PostHog SDK wrapper plus baseline-property builder.

Lazy-init, error-swallowing, fire-and-forget. Baseline properties returned by
`baseline()` are attached automatically to every event by `capture()`. Call
sites only specify event-specific properties on top of these.
"""

import base64
import json
import threading
from pathlib import Path

import posthog as _posthog

from humanbound_cli import __version__

from .. import config
from . import consent

# --- Module state ------------------------------------------------------------

_init_lock = threading.Lock()
_initialized = False
_initialized_ok = False
_user_id: str | None = None  # Set after identify() — overrides anonymous id


# --- Baseline-property helpers ----------------------------------------------


def baseline(is_authenticated: bool) -> dict:
    """Build the dict of baseline properties attached to every event.

    Intentionally minimal — posthog-python auto-attaches `$os`, `$os_version`,
    `$python_version`, `$python_runtime`, `$lib`, `$lib_version` on every event,
    so duplicating them here adds noise.
    """
    return {
        "source": "cli",
        "hb_version": __version__,
        "is_authenticated": is_authenticated,
    }


# --- PostHog client helpers --------------------------------------------------


def _credentials_file() -> Path:
    return config.get_humanbound_dir() / "credentials.json"


def _user_id_from_credentials() -> str | None:
    """Return the user's opaque Auth0 sub from the api_token JWT, or None.

    The sub lives in the `https://aiandme.io/user_id` custom claim — the
    top-level JWT `sub` is the M2M app ID, not the user.
    """
    f = _credentials_file()
    if not f.exists():
        return None
    try:
        token = json.loads(f.read_text())["api_token"]
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims.get("https://aiandme.io/user_id") or None
    except Exception:
        return None


def _email_from_credentials() -> str | None:
    """Return the account email persisted in credentials.json, or None."""
    f = _credentials_file()
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text()).get("email") or None
    except Exception:
        return None


def _resolve_distinct_id() -> str:
    """Auth'd user id if available, else the anonymous machine UUID."""
    global _user_id
    if _user_id is None:
        _user_id = _user_id_from_credentials()
    if _user_id:
        return _user_id
    did, _ = consent.get_distinct_id_and_new_flag()
    return did


def _ensure_init() -> bool:
    """Lazy SDK init. Returns True on success. Idempotent."""
    global _initialized, _initialized_ok
    if _initialized:
        return _initialized_ok
    with _init_lock:
        if _initialized:
            return _initialized_ok
        try:
            # posthog-python 7.x reads `api_key` (NOT `project_api_key`) at
            # the SDK's lazy setup() call. Setting the wrong attribute is a
            # silent no-op that drops every event downstream.
            _posthog.api_key = config.get_posthog_key()
            _posthog.host = config.get_posthog_host()
            # Reasonable defaults; SDK handles batching + background flush.
            _posthog.disabled = False
            # disable_geoip defaults to True in posthog-python; flip it off so
            # PostHog derives country/region/city. Raw IP is discarded project-side.
            _posthog.disable_geoip = False
            _initialized_ok = True
        except Exception:
            _initialized_ok = False
        _initialized = True
        return _initialized_ok


# --- Public API --------------------------------------------------------------


def is_enabled() -> bool:
    return consent.is_enabled()


def capture(event: str, properties: dict | None = None) -> None:
    """Send an event. Never raises. Silently drops if disabled or on error."""
    try:
        if not consent.is_enabled():
            return
        if not _ensure_init():
            return
        distinct_id = _resolve_distinct_id()
        is_auth = _user_id is not None
        merged = baseline(is_authenticated=is_auth)
        if properties:
            merged.update(properties)
        if is_auth:
            email = _email_from_credentials()
            if email:
                merged["$set"] = {"email": email}
        _posthog.capture(
            distinct_id=distinct_id,
            event=event,
            properties=merged,
        )
    except Exception:
        # Telemetry must never break the CLI. Swallow.
        pass


def identify(user_id: str) -> None:
    """Alias the anonymous machine UUID to a stable user ID (e.g. auth0|<sub>)."""
    global _user_id
    try:
        if not consent.is_enabled():
            return
        if not _ensure_init():
            return
        previous_id, _ = consent.get_distinct_id_and_new_flag()
        _posthog.alias(previous_id=previous_id, distinct_id=user_id)
        _user_id = user_id
    except Exception:
        pass


def identify_from_credentials() -> None:
    """Identify the user using the opaque Auth0 sub from the api_token JWT.

    No-op if credentials are missing or the claim cannot be extracted.
    """
    uid = _user_id_from_credentials()
    if uid:
        identify(uid)


def shutdown() -> None:
    """Flush queued events. Called via atexit. Bounded by the SDK's flush timeout."""
    try:
        if _initialized and _initialized_ok:
            _posthog.flush()
            _posthog.shutdown()
    except Exception:
        pass


def reset_for_tests() -> None:
    """Test-only: clear all module-level state."""
    global _initialized, _initialized_ok, _user_id
    _initialized = False
    _initialized_ok = False
    _user_id = None
