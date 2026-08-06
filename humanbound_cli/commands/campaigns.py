# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Campaign management commands."""

import json

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .. import telemetry
from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

console = Console()

# Keys match the backend CampaignPhase enum values carried in `activity`.
ACTIVITY_STYLES = {
    "assess": "[cyan]Assess[/cyan]",
    "investigate": "[yellow]Investigate[/yellow]",
    "monitor": "[green]Monitor[/green]",
}


@click.group("campaigns", invoke_without_command=True, hidden=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def campaigns_group(ctx, as_json):
    """[Deprecated] Use 'hb assessments' instead.

    Campaigns and assessments are the same thing; this alias is kept for
    backward compatibility.
    """
    # Deprecation notice on stderr (skipped in --json mode to keep machine
    # output clean). Shown for `hb campaigns` and its subcommands.
    if not as_json:
        click.secho(
            "'hb campaigns' is deprecated — use 'hb assessments' instead.",
            fg="yellow",
            err=True,
        )

    if ctx.invoked_subcommand is not None:
        return

    client = HumanboundClient()

    if not client.is_authenticated():
        telemetry.fire_gated_command_hit()
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = client.project_id
    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        with console.status("Fetching campaign plan..."):
            response = client.get_campaign(project_id)

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        _display_campaign(response)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _display_campaign(response: dict):
    """Display campaign plan details.

    Mirrors the campaign plan API response:
    {id, activity, status, plan (dict), test_count, synthesized_strategies (int count)}.
    """
    campaign = response.get("campaign", response)

    activity = str(campaign.get("activity", "") or "").lower()
    status = campaign.get("status", "")
    campaign_id = campaign.get("id", "")

    activity_display = ACTIVITY_STYLES.get(activity, activity or "—")
    status_color = (
        "green"
        if status in ("completed", "active")
        else ("yellow" if status == "running" else "white")
    )

    console.print(
        Panel(
            f"Activity: {activity_display}\n"
            f"Status: [{status_color}]{status}[/{status_color}]\n"
            f"[dim]ID: {campaign_id}[/dim]",
            title="Campaign Plan",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Discovery plan — backend returns `plan` as a dict (discovery_plan), not a
    # list of experiments. Render its top-level entries.
    plan = campaign.get("plan", {})
    if isinstance(plan, dict) and plan:
        console.print("\n[bold]Discovery Plan:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Area", width=28)
        table.add_column("Detail", overflow="fold")

        for key, value in plan.items():
            detail = (
                json.dumps(value, default=str) if isinstance(value, list | dict) else str(value)
            )
            if len(detail) > 200:
                detail = detail[:200] + "…"
            table.add_row(str(key), detail)

        console.print(table)

    # Summary stats
    test_count = campaign.get("test_count", 0)
    if test_count:
        console.print(f"\n[dim]Total tests planned: {test_count}[/dim]")

    # API returns a count (int); tolerate the legacy list shape during rollout.
    raw = campaign.get("synthesized_strategies")
    count = raw if isinstance(raw, int) else len(raw or [])
    if count:
        console.print(f"[dim]Synthesized strategies: {count}[/dim]")


@campaigns_group.command("terminate")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def terminate_campaign(force: bool):
    """Terminate the current running campaign."""
    client = HumanboundClient()

    if not client.is_authenticated():
        telemetry.fire_gated_command_hit()
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = client.project_id
    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        # Get current campaign to find ID
        with console.status("Fetching current campaign..."):
            response = client.get_campaign(project_id)

        campaign = response.get("campaign", response)
        campaign_id = campaign.get("id", "")

        if not campaign_id:
            console.print("[yellow]No active campaign found.[/yellow]")
            return

        status = campaign.get("status", "")
        if status in ("completed", "broken"):
            console.print(f"[yellow]Campaign is already {status}.[/yellow]")
            return

        if not force:
            if not Confirm.ask(
                f"Terminate campaign [bold]{campaign_id}[/bold]? Running experiments will be stopped"
            ):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Terminating campaign..."):
            client.terminate_campaign(project_id, campaign_id)

        console.print("[green]Campaign terminated.[/green]")
        console.print(f"[dim]ID: {campaign_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
