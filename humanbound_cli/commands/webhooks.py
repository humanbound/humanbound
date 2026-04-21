# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Webhook management commands."""

import json
import secrets

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

ALL_EVENT_TYPES = [
    "finding.created",
    "finding.regressed",
    "posture.grade_changed",
    "drift.detected",
    "campaign.completed",
    "ascam.phase_changed",
    "ascam.paused",
    "ascam.resumed",
]


def _require_auth() -> HumanboundClient:
    """Return an authenticated client or exit."""
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <org-id>' first.")
        raise SystemExit(1)

    return client


@click.group("webhooks", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def webhooks_group(ctx, as_json: bool):
    """Manage webhooks for security event delivery.

    \b
    Without a subcommand, lists all webhooks for the current organisation.

    \b
    Supported event types:
      finding.created, finding.regressed, posture.grade_changed,
      drift.detected, campaign.completed, ascam.phase_changed,
      ascam.paused, ascam.resumed
    """
    if ctx.invoked_subcommand is not None:
        return

    client = _require_auth()

    try:
        org_id = client.organisation_id
        with console.status("Fetching webhooks..."):
            result = client.get(f"organisations/{org_id}/webhooks", include_org=False)

        webhooks = result.get("data", []) if isinstance(result, dict) else result

        if as_json:
            print(json.dumps(webhooks, indent=2, default=str))
            return

        if not webhooks:
            console.print("[dim]No webhooks configured.[/dim]")
            console.print("Create one with: [green]hb webhooks add --url <url>[/green]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("ID", no_wrap=True)
        table.add_column("Name")
        table.add_column("URL")
        table.add_column("Status", width=10)
        table.add_column("Events")

        for wh in webhooks:
            is_active = wh.get("is_active", False)
            status_str = "[green]active[/green]" if is_active else "[red]inactive[/red]"
            events = wh.get("event_types", [])
            events_str = ", ".join(events) if events else "[dim]all[/dim]"
            table.add_row(
                str(wh.get("id", "")),
                wh.get("name", ""),
                wh.get("url", ""),
                status_str,
                events_str,
            )

        console.print(table)
        console.print(f"\n[dim]{len(webhooks)} webhook(s)[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@webhooks_group.command("add")
@click.option("--url", required=True, help="Webhook endpoint URL (HTTPS)")
@click.option("--name", default="Untitled Webhook", help="Display name")
@click.option("--secret", default=None, help="Signing secret (auto-generated if omitted)")
@click.option("--events", default=None, help="Comma-separated event types (default: all)")
def add(url: str, name: str, secret: str, events: str):
    """Create a new webhook.

    \b
    Examples:
      hb webhooks add --url https://example.com/hook
      hb webhooks add --url https://example.com/hook --name "My SIEM" --events finding.created,finding.regressed
    """
    client = _require_auth()

    webhook_secret = secret or secrets.token_hex(32)
    event_types = [e.strip() for e in events.split(",")] if events else ALL_EVENT_TYPES

    try:
        with console.status("Creating webhook..."):
            result = client.create_webhook(
                url=url,
                secret=webhook_secret,
                name=name,
                event_types=event_types,
            )

        webhook_id = result.get("id")
        if not webhook_id:
            console.print("[red]Failed to create webhook -- no ID returned.[/red]")
            raise SystemExit(1)

        console.print(f"[green]Webhook created.[/green] ID: {webhook_id}")
        console.print(f"\n[dim]Signing secret:[/dim] {webhook_secret}")
        console.print("[dim]Store this secret securely -- it cannot be retrieved later.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@webhooks_group.command("remove")
@click.argument("webhook_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def remove(webhook_id: str, force: bool):
    """Delete a webhook.

    \b
    WEBHOOK_ID is the ID of the webhook to delete.
    """
    client = _require_auth()

    if not force:
        if not Confirm.ask(f"Delete webhook [bold]{webhook_id}[/bold]? Events will stop being delivered."):
            console.print("[dim]Cancelled.[/dim]")
            return

    try:
        with console.status("Deleting webhook..."):
            client.delete_webhook(webhook_id)

        console.print("[green]Webhook deleted.[/green]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@webhooks_group.command("test")
@click.argument("webhook_id")
def test(webhook_id: str):
    """Send a test event to verify connectivity.

    \b
    WEBHOOK_ID is the ID of the webhook to test.
    """
    client = _require_auth()

    try:
        with console.status("Sending test event..."):
            client.test_webhook(webhook_id)

        console.print("[green]Test event delivered successfully.[/green]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Test failed:[/red] {e}")
        raise SystemExit(1)


@webhooks_group.command("sync")
@click.argument("webhook_id")
@click.option("--since", default=None, help="Start date (ISO 8601, e.g. 2026-01-01)")
@click.option("--until", default=None, help="End date (ISO 8601)")
@click.option("--project", "project_id", default=None, help="Filter by project ID")
@click.option("--event-type", default=None, help="Filter by event type")
def sync(webhook_id: str, since: str, until: str, project_id: str, event_type: str):
    """Replay historical events through a webhook.

    \b
    WEBHOOK_ID is the ID of the webhook to replay events through.
    Triggers async delivery of past security events. Max 1000 events per request.

    \b
    Examples:
      hb webhooks sync abc123 --since 2026-01-01
      hb webhooks sync abc123 --event-type finding.created --project def456
    """
    client = _require_auth()

    try:
        with console.status("Starting replay..."):
            result = client.replay_webhook(
                webhook_id=webhook_id,
                since=since,
                until=until,
                project_id=project_id,
                event_type=event_type,
            )

        queued = result.get("events_queued", 0)
        if queued == 0:
            console.print("[yellow]No matching events found.[/yellow]")
        else:
            console.print(f"[green]Replay started[/green] -- {queued} events queued for delivery.")
            console.print("[dim]Events are being delivered asynchronously.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@webhooks_group.command("update")
@click.argument("webhook_id")
@click.option("--url", default=None, help="New endpoint URL")
@click.option("--name", default=None, help="New display name")
@click.option("--status", "webhook_status", default=None, type=click.Choice(["active", "disabled"]), help="Set webhook status")
def update(webhook_id: str, url: str, name: str, webhook_status: str):
    """Update an existing webhook.

    \b
    WEBHOOK_ID is the ID of the webhook to update.

    \b
    Examples:
      hb webhooks update abc123 --name "Production SIEM"
      hb webhooks update abc123 --status disabled
      hb webhooks update abc123 --url https://new-endpoint.example.com --name "Updated"
    """
    client = _require_auth()

    data = {}
    if url is not None:
        data["url"] = url
    if name is not None:
        data["name"] = name
    if webhook_status is not None:
        data["is_active"] = webhook_status == "active"

    if not data:
        console.print("[yellow]Nothing to update.[/yellow] Provide at least one of --url, --name, or --status.")
        raise SystemExit(1)

    try:
        org_id = client.organisation_id
        with console.status("Updating webhook..."):
            result = client.put(
                f"organisations/{org_id}/webhooks/{webhook_id}",
                data=data,
                include_org=False,
            )

        console.print(f"[green]Webhook updated.[/green]")

        # Show current state
        updated_name = result.get("name", name or "")
        updated_url = result.get("url", url or "")
        is_active = result.get("is_active", True)
        active_str = "[green]active[/green]" if is_active else "[red]disabled[/red]"
        if updated_name:
            console.print(f"  Name:   {updated_name}")
        if updated_url:
            console.print(f"  URL:    [dim]{updated_url}[/dim]")
        console.print(f"  Status: {active_str}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
