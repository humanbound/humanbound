"""Monitor command — start/stop continuous security monitoring."""

import click
from rich.console import Console
from rich.panel import Panel

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.command("monitor")
@click.option("--pause", is_flag=True, help="Pause continuous monitoring")
@click.option("--resume", is_flag=True, help="Resume paused monitoring")
@click.option("--testing-level", type=click.Choice(["unit", "system", "acceptance"]), help="Testing depth for monitoring campaigns")
@click.option("--project", "-p", help="Project ID (uses current if not specified)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def monitor_command(pause: bool, resume: bool, testing_level: str, project: str, as_json: bool):
    """Start, pause, or resume continuous security monitoring (ASCAM).

    Without flags, starts monitoring on the current project.
    ASCAM runs automated campaigns: reconnaissance, red teaming, and monitoring
    phases that continuously test your agent for regressions and new threats.

    \b
    Examples:
      hb monitor                    # Start monitoring
      hb monitor --pause            # Pause monitoring
      hb monitor --resume           # Resume monitoring
      hb monitor --testing-level system  # Start with deeper tests
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = project or client.project_id
    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' or --project to specify one.")
        raise SystemExit(1)

    try:
        if pause and resume:
            console.print("[red]Cannot use --pause and --resume together.[/red]")
            raise SystemExit(1)

        if pause:
            _pause_monitoring(client, project_id)
        elif resume:
            _resume_monitoring(client, project_id)
        else:
            _start_monitoring(client, project_id, testing_level, as_json)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _start_monitoring(client, project_id, testing_level, as_json):
    """Start ASCAM continuous monitoring."""
    # Check current ASCAM state
    with console.status("Checking project status..."):
        project_data = client.get(f"projects/{project_id}", include_project=False)

    ascam_phase = project_data.get("ascam_phase", "")

    if ascam_phase == "monitoring":
        console.print("[green]Monitoring is already active.[/green]")
        _show_status(client, project_id, project_data, as_json)
        return

    # Trigger ASCAM campaign
    campaign_data = {"trigger": "manual"}
    if testing_level:
        campaign_data["testing_level"] = testing_level

    with console.status("Starting continuous monitoring..."):
        response = client.post(
            f"projects/{project_id}/campaigns",
            data=campaign_data,
            include_project=False,
        )

    if as_json:
        import json
        print(json.dumps(response, indent=2, default=str))
        return

    console.print("[green]Monitoring started.[/green]")
    console.print()

    campaign = response.get("campaign", response)
    phase = campaign.get("phase", campaign.get("current_phase", ""))

    console.print(Panel(
        f"ASCAM Phase: [bold]{phase}[/bold]\n"
        f"[dim]Automated campaigns will run on schedule.[/dim]\n"
        f"[dim]Triggers: regressions, drift, new findings, posture drop.[/dim]",
        title="Continuous Monitoring",
        border_style="green",
        padding=(1, 2),
    ))

    console.print("\n[dim]Next:[/dim]")
    console.print("  [bold]hb posture[/bold]          Check posture score")
    console.print("  [bold]hb findings[/bold]         View findings")
    console.print("  [bold]hb monitor --pause[/bold]  Pause monitoring")


def _pause_monitoring(client, project_id):
    """Pause ASCAM monitoring."""
    with console.status("Pausing monitoring..."):
        # Get current campaign
        response = client.get(f"projects/{project_id}/campaigns", include_project=False)

    campaign = response.get("campaign", response)
    campaign_id = campaign.get("id")

    if not campaign_id:
        console.print("[yellow]No active campaign to pause.[/yellow]")
        return

    with console.status("Pausing campaign..."):
        client.post(
            f"projects/{project_id}/campaigns/{campaign_id}/pause",
            data={},
            include_project=False,
        )

    console.print("[green]Monitoring paused.[/green]")
    console.print("[dim]Use 'hb monitor --resume' to restart.[/dim]")


def _resume_monitoring(client, project_id):
    """Resume paused ASCAM monitoring."""
    with console.status("Resuming monitoring..."):
        response = client.get(f"projects/{project_id}/campaigns", include_project=False)

    campaign = response.get("campaign", response)
    campaign_id = campaign.get("id")

    if not campaign_id:
        console.print("[yellow]No paused campaign to resume.[/yellow]")
        console.print("[dim]Use 'hb monitor' to start monitoring.[/dim]")
        return

    with console.status("Resuming campaign..."):
        client.post(
            f"projects/{project_id}/campaigns/{campaign_id}/resume",
            data={},
            include_project=False,
        )

    console.print("[green]Monitoring resumed.[/green]")
    console.print("[dim]Use 'hb posture' to check current score.[/dim]")


def _show_status(client, project_id, project_data, as_json):
    """Show current monitoring status."""
    try:
        campaign_response = client.get(f"projects/{project_id}/campaigns", include_project=False)
        campaign = campaign_response.get("campaign", campaign_response)
    except APIError:
        campaign = {}

    if as_json:
        import json
        print(json.dumps({"project": project_data, "campaign": campaign}, indent=2, default=str))
        return

    phase = project_data.get("ascam_phase", "unknown")
    status = campaign.get("status", "")

    console.print(Panel(
        f"Phase: [bold]{phase}[/bold]\n"
        f"Campaign status: {status}\n"
        f"[dim]Project: {project_data.get('name', project_id)}[/dim]",
        title="Monitoring Status",
        border_style="green",
        padding=(1, 2),
    ))
