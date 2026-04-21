# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Campaign management commands."""

import json
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

PHASE_STYLES = {
    "reconnaissance": "[cyan]Reconnaissance[/cyan]",
    "red_teaming": "[red]Red Teaming[/red]",
    "monitoring": "[green]Monitoring[/green]",
}


@click.group("campaigns", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def campaigns_group(ctx, as_json):
    """View and manage ASCAM campaigns.

    \b
    Examples:
      hb campaigns                   # Show current campaign plan
      hb campaigns --json            # JSON output
      hb campaigns terminate         # Terminate a running campaign
    """
    if ctx.invoked_subcommand is not None:
        return

    client = HumanboundClient()

    if not client.is_authenticated():
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
    """Display campaign plan details."""
    campaign = response.get("campaign", response)

    phase = str(campaign.get("phase", campaign.get("current_phase", ""))).lower()
    status = campaign.get("status", "")
    campaign_id = campaign.get("id", "")

    phase_display = PHASE_STYLES.get(phase, phase)
    status_color = "green" if status in ("completed", "active") else ("yellow" if status == "running" else "white")

    console.print(Panel(
        f"Phase: {phase_display}\n"
        f"Status: [{status_color}]{status}[/{status_color}]\n"
        f"[dim]ID: {campaign_id}[/dim]",
        title="Campaign Plan",
        border_style="blue",
        padding=(1, 2),
    ))

    # Experiments in plan
    experiments = campaign.get("experiments", campaign.get("plan", []))
    if experiments:
        console.print("\n[bold]Planned Experiments:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Category", width=25)
        table.add_column("Tests", justify="right", width=8)
        table.add_column("Strategy", width=20)
        table.add_column("Status", width=12)

        for exp in experiments:
            cat = exp.get("test_category", exp.get("category", ""))
            if "/" in cat:
                cat = cat.split("/")[-1]
            tests = exp.get("test_count", exp.get("size", ""))
            strategy = exp.get("strategy", "")
            exp_status = exp.get("status", "pending")

            status_style = {
                "completed": "[green]completed[/green]",
                "running": "[yellow]running[/yellow]",
                "failed": "[red]failed[/red]",
                "pending": "[dim]pending[/dim]",
            }.get(str(exp_status).lower(), str(exp_status))

            table.add_row(cat, str(tests), strategy, status_style)

        console.print(table)

    # Summary stats
    total_tests = campaign.get("total_tests", campaign.get("total_size", 0))
    if total_tests:
        console.print(f"\n[dim]Total tests planned: {total_tests}[/dim]")


@campaigns_group.command("terminate")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def terminate_campaign(force: bool):
    """Terminate the current running campaign."""
    client = HumanboundClient()

    if not client.is_authenticated():
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
            if not Confirm.ask(f"Terminate campaign [bold]{campaign_id}[/bold]? Running experiments will be stopped"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Terminating campaign..."):
            client.terminate_campaign(project_id, campaign_id)

        console.print(f"[green]Campaign terminated.[/green]")
        console.print(f"[dim]ID: {campaign_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
