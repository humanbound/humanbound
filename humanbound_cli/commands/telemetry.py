# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb telemetry enable|disable|status` — manage anonymous CLI telemetry."""

import click
from rich.console import Console

from .. import telemetry as telemetry_pkg
from ..telemetry import consent

console = Console()


@click.group("telemetry")
def telemetry_group():
    """Manage anonymous CLI telemetry.

    \b
    Examples:
      hb telemetry status     # Show current state
      hb telemetry disable    # Stop sending events from this machine
      hb telemetry enable     # Resume sending events
    """
    pass


@telemetry_group.command("enable")
def telemetry_enable():
    """Re-enable telemetry on this machine."""
    consent.clear_opt_out()
    consent.reset_cache()
    console.print("[green]Telemetry enabled.[/green]")
    console.print(
        "See [link=https://github.com/humanbound/humanbound/blob/main/PRIVACY.md]"
        "PRIVACY.md[/link] for what is collected."
    )


def _fire_final_optout_event() -> bool:
    """Send the once-ever `telemetry_disabled` event while telemetry is still
    enabled, gated on the shared `disabled_ping_sent` flag. Returns whether
    the event was sent."""
    if not consent.is_enabled() or consent.disabled_ping_already_sent():
        return False
    if not consent.mark_disabled_ping_sent():
        return False
    telemetry_pkg.capture("telemetry_disabled", {"reason": "command"})
    return True


@telemetry_group.command("disable")
def telemetry_disable():
    """Disable telemetry on this machine."""
    fired = _fire_final_optout_event()
    consent.write_opt_out()
    consent.reset_cache()
    console.print("[yellow]Telemetry disabled.[/yellow]")
    console.print(
        "A final [bold]telemetry_disabled[/bold] event was sent so we can "
        "count opt-outs; nothing further will be sent from this machine."
        if fired
        else "No events will be sent from this machine."
    )
    console.print(
        "Details: [link=https://github.com/humanbound/humanbound/blob/main/PRIVACY.md]"
        "PRIVACY.md[/link]"
    )


@telemetry_group.command("status")
def telemetry_status():
    """Show current telemetry state and why."""
    enabled = consent.is_enabled()
    if enabled:
        console.print("[green]Telemetry: enabled[/green]")
        console.print(
            "Disable with: [bold]hb telemetry disable[/bold] or "
            "[bold]HB_TELEMETRY_DISABLED=1[/bold]"
        )
    else:
        reason = consent.disabled_reason() or "unknown"
        console.print("[yellow]Telemetry: disabled[/yellow]")
        console.print(f"Reason: {reason}")
        console.print("Enable with: [bold]hb telemetry enable[/bold]")
    console.print("Docs: https://github.com/humanbound/humanbound/blob/main/PRIVACY.md")
