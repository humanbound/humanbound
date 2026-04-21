# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Organisation commands."""

import json

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.group("orgs", invoke_without_command=True)
@click.pass_context
def orgs_group(ctx):
    """Organisation management. Run without subcommand to list organisations."""
    if ctx.invoked_subcommand is not None:
        return
    _list_orgs()


@orgs_group.command("list")
def list_orgs_cmd():
    """List organisations you have access to."""
    _list_orgs()


def _list_orgs():
    """List organisations you have access to."""
    client = HumanboundClient()

    try:
        orgs = client.list_organisations()

        if not orgs:
            console.print("[yellow]No organisations found.[/yellow]")
            return

        table = Table(title="Organisations")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Subscription ID", style="dim")
        table.add_column("Active", justify="center")

        for org in orgs:
            is_active = "  " if org.get("id") != client.organisation_id else "[green]active[/green]"
            table.add_row(
                org.get("id", ""),
                org.get("name", "Unknown"),
                org.get("subscription_id", ""),
                is_active,
            )

        console.print(table)

        if not client.organisation_id:
            console.print("\n[dim]Tip: Use 'hb orgs use <id>' to select an organisation.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@orgs_group.command("use")
@click.argument("org_id")
def use_org(org_id: str):
    """Switch to a different organisation.

    \b
    Examples:
      hb orgs use <id>
    """
    client = HumanboundClient()
    try:
        orgs_list = client.list_organisations()
        org = next((o for o in orgs_list if o.get("id") == org_id), None)
        if not org:
            console.print(f"[red]Organisation not found:[/red] {org_id}")
            console.print("\nAvailable organisations:")
            for o in orgs_list:
                console.print(f"  {o.get('id')} - {o.get('name')}")
            raise SystemExit(1)
        client.set_organisation(org_id)
        console.print(f"[green]Switched to organisation:[/green] {org.get('name')}")
    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@orgs_group.command("current")
def current_org():
    """Show the currently selected organisation."""
    client = HumanboundClient()

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select one.")
        return

    try:
        orgs = client.list_organisations()
        org = next((o for o in orgs if o.get("id") == client.organisation_id), None)

        if org:
            console.print(f"[bold]{org.get('name')}[/bold]")
            console.print(f"[dim]ID: {client.organisation_id}[/dim]")
            console.print(f"[dim]Subscription: {org.get('subscription_id', 'N/A')}[/dim]")
        else:
            console.print(f"[yellow]Organisation ID:[/yellow] {client.organisation_id}")
            console.print("[dim]Unable to fetch organisation details.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)


@orgs_group.command("subscription")
def subscription_details():
    """Show subscription details for the current organisation."""
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' first.")
        raise SystemExit(1)

    try:
        # Get org to find subscription_id
        orgs = client.list_organisations()
        org = next((o for o in orgs if o.get("id") == client.organisation_id), None)

        if not org:
            console.print("[red]Organisation not found.[/red]")
            raise SystemExit(1)

        sub_id = org.get("subscription_id")
        if not sub_id:
            console.print("[yellow]No subscription linked to this organisation.[/yellow]")
            raise SystemExit(1)

        with console.status("Fetching subscription..."):
            response = client.get_subscription(sub_id)

        # Response is a list with one item
        sub = response[0] if isinstance(response, list) else response

        plan_level = sub.get("plan_level", "N/A")
        plan_freq = sub.get("plan_freq", "N/A")

        quota = sub.get("quota", {})
        features = sub.get("features", {})

        console.print(Panel(
            f"Plan: [bold]{plan_level}[/bold] ({plan_freq})\n"
            f"[dim]ID: {sub_id}[/dim]",
            title="Subscription",
            border_style="blue",
            padding=(1, 2),
        ))

        # Quota
        if quota:
            console.print("\n[bold]Quota:[/bold]")
            for key, val in quota.items():
                console.print(f"  {key}: {val}")

        # Features
        if features:
            console.print("\n[bold]Features:[/bold]")
            for key, val in features.items():
                status = "[green]enabled[/green]" if val else "[dim]disabled[/dim]"
                console.print(f"  {key}: {status}")
        else:
            console.print("\n[dim]No features enabled.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@orgs_group.command("report")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--no-open", is_flag=True, help="Save without opening browser")
def org_report(output: str, no_open: bool):
    """Generate security report for the current organisation.

    \b
    Examples:
      hb orgs report
      hb orgs report -o org-report.html
    """
    from ._report_helper import download_and_open

    client = HumanboundClient()
    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow] Run 'hb switch <id>'")
        raise SystemExit(1)

    oid = client.organisation_id
    download_and_open(
        client,
        f"organisations/{oid}/report",
        f"org-{oid[:8]}-report.html",
        output=output,
        no_open=no_open,
    )
