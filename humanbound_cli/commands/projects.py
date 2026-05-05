# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Project commands."""

import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError, ValidationError

console = Console()


@click.group("projects", invoke_without_command=True)
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
@click.pass_context
def projects_group(ctx, page: int, size: int):
    """Project management commands. Run without subcommand to list projects."""
    if ctx.invoked_subcommand is not None:
        return
    _list_projects(page, size)


@projects_group.command("list")
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
def list_projects_cmd(page: int, size: int):
    """List projects in the current organisation."""
    _list_projects(page, size)


def _list_projects(page: int, size: int):
    """List projects in the current organisation."""
    client = HumanboundClient()

    try:
        response = client.list_projects(page=page, size=size)
        projects = response.get("data", [])

        if not projects:
            console.print("[yellow]No projects found.[/yellow]")
            return

        table = Table(title="Projects")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Description")
        table.add_column("Active", justify="center")

        for proj in projects:
            is_active = "" if proj.get("id") != client.project_id else "[green]active[/green]"
            table.add_row(
                proj.get("id", ""),
                proj.get("name", "Unknown"),
                (proj.get("description", "") or "")[:40],
                is_active,
            )

        console.print(table)

        if response.get("has_next_page"):
            console.print(f"\n[dim]Page {page} of more. Use --page to navigate.[/dim]")

        if not client.project_id:
            console.print("\n[dim]Tip: Use 'hb projects use <id>' to select a project.[/dim]")

    except ValidationError as e:
        console.print(f"[yellow]{e}[/yellow]")
        console.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)
    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@projects_group.command("use")
@click.argument("project_id")
def use_project(project_id: str):
    """Set the active project.

    PROJECT_ID: Project UUID to use.
    """
    client = HumanboundClient()

    try:
        response = client.list_projects(size=100)
        projects = response.get("data", [])
        project = next((p for p in projects if p.get("id") == project_id), None)

        if not project:
            # Try partial match
            matches = [p for p in projects if p.get("id", "").startswith(project_id)]
            if len(matches) == 1:
                project = matches[0]
            elif len(matches) > 1:
                console.print(f"[yellow]Multiple projects match '{project_id}':[/yellow]")
                for p in matches:
                    console.print(f"  {p.get('id')} - {p.get('name')}")
                raise SystemExit(1)
            else:
                console.print(f"[red]Project not found:[/red] {project_id}")
                raise SystemExit(1)

        client.set_project(project.get("id"))
        console.print(f"[green]Switched to project:[/green] {project.get('name')}")

    except ValidationError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise SystemExit(1)
    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@projects_group.command("current")
def current_project():
    """Show the currently selected project."""
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select one.")
        return

    try:
        response = client.list_projects(size=100)
        projects = response.get("data", [])
        project = next((p for p in projects if p.get("id") == client.project_id), None)

        if project:
            console.print(f"[bold]{project.get('name')}[/bold]")
            console.print(f"[dim]ID: {client.project_id}[/dim]")
            if project.get("description"):
                console.print(f"Description: {project.get('description')}")
        else:
            console.print(f"[yellow]Project ID:[/yellow] {client.project_id}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)


@projects_group.command("show")
@click.argument("project_id", required=False)
def show_project(project_id: str):
    """Show project details.

    PROJECT_ID: Project UUID (uses current if not specified).
    """
    client = HumanboundClient()

    project_id = project_id or client.project_id

    if not project_id:
        console.print("[yellow]No project specified.[/yellow]")
        console.print("Use 'hb projects show <id>' or select a project first.")
        raise SystemExit(1)

    try:
        # Temporarily set project to fetch details
        original_project = client.project_id
        client.set_project(project_id)

        response = client.get(f"projects/{project_id}", include_project=True)

        console.print(f"\n[bold]{response.get('name')}[/bold]")
        console.print(f"[dim]ID: {response.get('id')}[/dim]\n")

        if response.get("description"):
            console.print(f"Description: {response.get('description')}\n")

        scope = response.get("scope", {})
        if scope:
            console.print("[bold]Scope:[/bold]")
            console.print(f"  Business: {scope.get('overall_business_scope', '')[:100]}...")

            intents = scope.get("intents", {})
            if intents.get("permitted"):
                console.print(f"  Permitted intents: {len(intents.get('permitted', []))} defined")
            if intents.get("restricted"):
                console.print(f"  Restricted intents: {len(intents.get('restricted', []))} defined")

        # Restore original project
        if original_project:
            client.set_project(original_project)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@projects_group.command("update")
@click.argument("project_id", required=False)
@click.option("--name", help="New project name")
@click.option("--description", help="New project description")
@click.option(
    "--capabilities",
    help="Set scope.capabilities (e.g. 'tools=on,memory=off'). Supports 'all=on/off' shorthand.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip dataset-archive confirmation")
def update_project(project_id: str, name: str, description: str, capabilities: str, yes: bool):
    """Update a project.

    PROJECT_ID: Project UUID (uses current if not specified).
    """
    client = HumanboundClient()

    project_id = project_id or client.project_id

    if not project_id:
        console.print("[yellow]No project specified.[/yellow]")
        console.print("Use 'hb projects update <id>' or select a project first.")
        raise SystemExit(1)

    if not name and not description and not capabilities:
        console.print(
            "[yellow]Nothing to update.[/yellow] "
            "Provide --name, --description, and/or --capabilities."
        )
        raise SystemExit(1)

    try:
        # name/description: existing flow, sent without scope wrapper
        if name or description:
            payload: dict = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description

            with console.status("Updating project..."):
                client.update_project(project_id, payload)

            console.print("[green]Project updated.[/green]")
            console.print(f"[dim]ID: {project_id}[/dim]")
            if name:
                console.print(f"  Name: {name}")
            if description:
                console.print(f"  Description: {description}")

        # capabilities: read-modify-write via the shared helper
        if capabilities:
            from humanbound_cli.commands._capabilities_flag import parse_capabilities_spec
            from humanbound_cli.engine.capabilities_writer import write_capabilities

            try:
                override = parse_capabilities_spec(capabilities)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                raise SystemExit(1)

            write_capabilities(client, project_id, override, yes=yes, console=console)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@projects_group.command("delete")
@click.argument("project_id", required=False)
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete_project(project_id: str, force: bool):
    """Delete a project and archive all its experiments.

    PROJECT_ID: Project UUID (uses current if not specified).
    """
    client = HumanboundClient()

    project_id = project_id or client.project_id

    if not project_id:
        console.print("[yellow]No project specified.[/yellow]")
        console.print("Use 'hb projects delete <id>' or select a project first.")
        raise SystemExit(1)

    try:
        # Get project name for confirmation
        response = client.list_projects(size=100)
        projects = response.get("data", [])
        project = next((p for p in projects if p.get("id") == project_id), None)
        project_name = project.get("name", project_id) if project else project_id

        if not force:
            console.print(
                f"[yellow]This will delete project [bold]{project_name}[/bold] and archive all its experiments.[/yellow]"
            )
            if not Confirm.ask("Are you sure?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Deleting project..."):
            client.delete_project(project_id)

        # Clear project context if we deleted the active project
        if client.project_id == project_id:
            client.set_project(None)

        console.print("[green]Project deleted.[/green]")
        console.print(f"[dim]{project_name} ({project_id})[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@projects_group.command("report")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--no-open", is_flag=True, help="Save without opening browser")
def project_report(output: str, no_open: bool):
    """Generate security report for the current project.

    Downloads the report from the platform and opens it in your browser.

    \b
    Examples:
      hb projects report
      hb projects report -o report.html
      hb projects report --no-open
    """
    from ._report_helper import download_and_open

    client = HumanboundClient()
    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow] Run 'hb projects use <id>'")
        raise SystemExit(1)

    pid = client.project_id
    download_and_open(
        client,
        f"projects/{pid}/report",
        f"project-{pid[:8]}-report.html",
        output=output,
        no_open=no_open,
        include_project=True,
    )


@projects_group.command("status")
@click.option("--watch", "-w", is_flag=True, help="Poll every 3 minutes until idle")
def project_status(watch: bool):
    """Show project activity status — is anything running?

    \b
    Examples:
      hb projects status
      hb projects status -w
    """
    client = HumanboundClient()
    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow] Run 'hb projects use <id>'")
        raise SystemExit(1)

    pid = client.project_id

    try:
        if watch:
            _watch_project_status(client, pid)
        else:
            data = client.get(f"projects/{pid}/status")
            _display_project_status(data)
    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        msg = str(e) or "Could not fetch project status"
        console.print(f"[red]Error:[/red] {msg}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _display_project_status(data):
    """Render project status panel."""
    name = data.get("project_name", "Unknown")
    active = data.get("active", False)
    monitoring = data.get("monitoring", "off")
    running = data.get("running_experiments", 0)
    grade = data.get("posture_grade")
    score = data.get("posture_score")
    campaign = data.get("active_campaign")

    # Status indicator
    if active:
        status_line = f"[yellow]Active[/yellow] — {running} experiment(s) running"
    else:
        status_line = "[green]Idle[/green] — no experiments running"

    # Posture
    if grade and score is not None:
        grade_color = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}.get(
            grade, "white"
        )
        posture_line = f"Posture: [{grade_color}]{grade}[/{grade_color}] ({score}/100)"
    else:
        posture_line = "Posture: [dim]not yet evaluated[/dim]"

    # Monitoring
    mon_color = {"active": "green", "paused": "yellow", "off": "dim"}.get(monitoring, "dim")
    mon_line = f"Monitoring: [{mon_color}]{monitoring}[/{mon_color}]"

    # Campaign
    campaign_line = ""
    if campaign:
        campaign_line = (
            f"\nCampaign: {campaign.get('activity', '?')} ({campaign.get('scope', '?')})"
        )

    # Running experiments detail
    exp_lines = ""
    for exp in data.get("experiments", []):
        cat = exp.get("test_category", "").split("/")[-1] if exp.get("test_category") else "?"
        exp_lines += f"\n  [{exp.get('status')}] {cat} ({exp.get('id', '')[:8]})"

    body = f"{status_line}\n{posture_line}\n{mon_line}{campaign_line}{exp_lines}"

    console.print(Panel(body, title=f"{name}"))


def _watch_project_status(client, pid):
    """Poll project status every 3 minutes until idle."""
    console.print("[dim]Watching project status (Ctrl+C to stop)...[/dim]\n")
    try:
        while True:
            data = client.get(f"projects/{pid}/status")
            console.clear()
            _display_project_status(data)

            if not data.get("active", False):
                console.print("\n[green]All experiments completed.[/green]")
                break

            console.print("\n[dim]Next check in 3 minutes... (Ctrl+C to stop)[/dim]")
            time.sleep(180)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching.[/dim]")
