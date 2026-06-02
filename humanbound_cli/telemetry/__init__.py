# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Anonymous CLI usage telemetry.

See PRIVACY.md at the repo root for what is collected and how to disable.

Public API:
    telemetry.capture(event, properties)   — fire one event, never raises
    telemetry.identify(user_id)            — alias anonymous id to user id on login
    telemetry.identify_from_credentials()  — same, but reads the user id from credentials.json
    telemetry.shutdown()                   — flush queued events; called via atexit
    telemetry.is_enabled()                 — check whether sends are currently active
    telemetry.fire_gated_command_hit()     — capture('gated_command_hit', ...) with current command path
"""

from . import consent as _consent
from .client import capture, identify, identify_from_credentials, is_enabled, shutdown


def fire_gated_command_hit() -> None:
    """Fire `gated_command_hit` tagged with the current Click context's command_path.

    Never raises — falls back to "unknown" if no Click context is active. Use
    this at every `if not client.is_authenticated(): raise SystemExit(1)`
    short-circuit so the funnel captures all gated-command-hits, not just the
    handful that propagate as `NotAuthenticatedError`.
    """
    try:
        import click

        ctx = click.get_current_context(silent=True)
        cmd = ctx.command_path if ctx is not None else "unknown"
        capture("gated_command_hit", {"command": cmd})
    except Exception:
        pass


def maybe_fire_install_event(argv: list[str] | None = None) -> None:
    """Fire the `install` event on the first enabled run for this machine.

    Skipped if telemetry is disabled or the user is running an `hb telemetry`
    subcommand (so the opt-out flow doesn't count itself as an install).

    Never raises — disk errors during UUID file creation are swallowed so a
    read-only $HOME or full disk cannot prevent the CLI from running.
    """
    try:
        import sys

        argv = argv if argv is not None else sys.argv
        if len(argv) >= 2 and argv[1] == "telemetry":
            return
        if not _consent.is_enabled():
            return
        _, was_new = _consent.get_distinct_id_and_new_flag()
        if was_new:
            capture("install")
            _print_first_run_notice()
    except Exception:
        pass


def _print_first_run_notice() -> None:
    """One-line notice on stderr explaining telemetry. Printed once per machine."""
    try:
        import click

        click.echo(
            "humanbound: anonymous usage data is enabled to help improve the CLI. "
            "No personal data is sent. Disable with `hb telemetry disable`. "
            "Details: https://github.com/humanbound/humanbound/blob/main/PRIVACY.md",
            err=True,
        )
    except Exception:
        pass


__all__ = [
    "capture",
    "fire_gated_command_hit",
    "identify",
    "identify_from_credentials",
    "is_enabled",
    "maybe_fire_install_event",
    "shutdown",
]
