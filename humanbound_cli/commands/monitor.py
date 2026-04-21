# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
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
@click.option("--project", "-p", help="Project ID (uses current if not specified)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def monitor_command(pause: bool, resume: bool, project: str, as_json: bool):
    """Start, pause, or resume continuous security monitoring (ASCAM).

    Without flags, shows current monitoring status.
    ASCAM runs daily automated assessments that continuously test
    your agent for regressions and new threats.

    \b
    Examples:
      hb monitor                    # Show monitoring status
      hb monitor --pause            # Pause monitoring
      hb monitor --resume           # Resume monitoring
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
            _toggle_ascam(client, project_id, paused=True)
        elif resume:
            _toggle_ascam(client, project_id, paused=False)
        else:
            _show_status(client, project_id, as_json)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _toggle_ascam(client, project_id, paused: bool):
    """Pause or resume ASCAM via PUT /projects/{id}/ascam/pause."""
    action = "Pausing" if paused else "Resuming"
    with console.status(f"{action} monitoring..."):
        client.put(
            f"projects/{project_id}/ascam/pause",
            data={"paused": paused},
        )

    if paused:
        console.print("[yellow]Monitoring paused.[/yellow]")
        console.print("[dim]Use 'hb monitor --resume' to restart.[/dim]")
    else:
        console.print("[green]Monitoring resumed.[/green]")
        console.print("[dim]Use 'hb posture' to check current score.[/dim]")


def _show_status(client, project_id, as_json):
    """Show current ASCAM monitoring status."""
    with console.status("Checking project status..."):
        project_data = client.get(f"projects/{project_id}", include_project=False)

    if as_json:
        import json
        print(json.dumps(project_data, indent=2, default=str))
        return

    name = project_data.get("name", project_id)
    ascam_paused = project_data.get("ascam_paused", True)
    ascam_activity = project_data.get("ascam_activity", "unknown")
    last_posture = project_data.get("last_posture_score")
    last_grade = project_data.get("last_posture_grade", "-")

    if ascam_paused:
        status_line = "[yellow]paused[/yellow]"
    else:
        status_line = f"[green]active[/green] ({ascam_activity})"

    posture_line = f"{last_posture:.1f} / {last_grade}" if last_posture else "[dim]not yet scored[/dim]"

    console.print(Panel(
        f"  Status   {status_line}\n"
        f"  Posture  {posture_line}\n"
        f"  Project  [dim]{name}[/dim]",
        title="[bold]Continuous Monitoring[/bold]",
        border_style="green" if not ascam_paused else "yellow",
        padding=(1, 2),
    ))

    if ascam_paused:
        console.print("\n[dim]Use 'hb monitor --resume' to start monitoring.[/dim]")
    else:
        console.print("\n[dim]Next:[/dim]")
        console.print("  [bold]hb posture[/bold]          Check posture score")
        console.print("  [bold]hb findings[/bold]         View findings")
        console.print("  [bold]hb monitor --pause[/bold]  Pause monitoring")
