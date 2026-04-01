"""Connector management commands for Shadow AI Discovery."""

import json

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

STATUS_STYLES = {
    "active": "[green]active[/green]",
    "disabled": "[yellow]disabled[/yellow]",
    "error": "[red]error[/red]",
}


def _require_client() -> HumanboundClient:
    """Return an authenticated client with an org selected, or exit."""
    client = HumanboundClient()
    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <org-id>' first.")
        raise SystemExit(1)
    return client


@click.group("connectors", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--report", "report_path", is_flag=False, flag_value="auto", default=None,
              help="Export as branded HTML report (optionally pass a filename)")
@click.pass_context
def connectors_group(ctx, as_json, report_path):
    """Manage cloud connectors for Shadow AI Discovery.

    \b
    Examples:
      hb connectors                    # List all connectors
      hb connectors --report           # Export HTML report
      hb connectors add --vendor microsoft --tenant-id <tid> --client-id <cid>
      hb connectors test <id>          # Test connection
      hb connectors remove <id>        # Delete connector
    """
    if ctx.invoked_subcommand is not None:
        return

    client = _require_client()

    try:
        with console.status("Fetching connectors..."):
            response = client.list_connectors()

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        connectors = response.get("data", []) if isinstance(response, dict) else response

        if not connectors:
            console.print("[yellow]No connectors registered.[/yellow]")
            console.print("[dim]Use 'hb connectors add' to register a cloud connector.[/dim]")
            return

        table = Table(title="Connectors")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Vendor", width=12)
        table.add_column("Display Name", width=25)
        table.add_column("Tenant ID", style="dim", no_wrap=True)
        table.add_column("Status", width=10)
        table.add_column("Last Scan", width=16)

        for c in connectors:
            status = str(c.get("status", "")).lower()
            last_scan = str(c.get("last_scan_at", "") or "")[:16]

            table.add_row(
                str(c.get("id", "")),
                c.get("vendor", ""),
                c.get("display_name", ""),
                str(c.get("tenant_id", "") or ""),
                STATUS_STYLES.get(status, status),
                last_scan if last_scan else "[dim]-[/dim]",
            )

        console.print(table)

        # HTML report export
        if report_path is not None:
            from ..report_builder import ReportBuilder, _esc

            rb = ReportBuilder("Connectors", f"{len(connectors)} registered")
            rb.add_kv("Summary", {
                "Total Connectors": len(connectors),
                "Active": sum(1 for c in connectors if str(c.get("status", "")).lower() == "active"),
                "Disabled": sum(1 for c in connectors if str(c.get("status", "")).lower() == "disabled"),
            })

            STATUS_HTML = {
                "active": '<span class="badge badge-success">ACTIVE</span>',
                "disabled": '<span class="badge badge-warning">DISABLED</span>',
                "error": '<span class="badge badge-error">ERROR</span>',
            }
            rows = []
            for c in connectors:
                status = str(c.get("status", "")).lower()
                last_scan = str(c.get("last_scan_at", "") or "")[:16] or "-"
                rows.append([
                    _esc(str(c.get("id", ""))),
                    _esc(c.get("vendor", "")),
                    _esc(c.get("display_name", "")),
                    _esc(str(c.get("tenant_id", "") or "")),
                    STATUS_HTML.get(status, _esc(status)),
                    _esc(last_scan),
                ])

            rb.add_table("Connectors", columns=["ID", "Vendor", "Name", "Tenant", "Status", "Last Scan"], rows=rows)
            saved = rb.save(None if report_path == "auto" else report_path)
            console.print(f"\n[green]Report saved:[/green] {saved}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@connectors_group.command("create")
@click.option("--vendor", default="microsoft", help="Cloud vendor (default: microsoft)")
@click.option("--tenant-id", required=True, help="Cloud tenant ID")
@click.option("--client-id", required=True, help="App registration client ID")
@click.option("--client-secret", required=True, prompt=True, hide_input=True, help="App registration client secret")
@click.option("--name", default=None, help="Display name for the connector")
def add_connector(vendor, tenant_id, client_id, client_secret, name):
    """Register a new cloud connector.

    After creation, automatically tests the connection.

    \b
    Examples:
      hb connectors add --tenant-id abc --client-id def --client-secret ghi
      hb connectors add --vendor microsoft --tenant-id abc --client-id def --name "Production"
    """
    client = _require_client()

    try:
        with console.status("Creating connector..."):
            result = client.create_connector(
                vendor=vendor,
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
                display_name=name,
            )

        connector_id = result.get("id", "")
        display = result.get("display_name", name or f"{vendor.title()} Connector")

        console.print(Panel(
            f"[green]Connector created[/green]\n\n"
            f"  Vendor:  [bold]{vendor}[/bold]\n"
            f"  Name:    {display}\n"
            f"  Tenant:  [dim]{tenant_id}[/dim]\n"
            f"  [dim]ID: {connector_id}[/dim]",
            border_style="green",
            padding=(1, 2),
        ))

        # Auto-test
        with console.status("Testing connection..."):
            try:
                test_result = client.test_connector(connector_id)
                console.print("[green]Connection test passed.[/green]")
                permissions = test_result.get("permissions", [])
                if permissions:
                    console.print(f"[dim]Permissions: {', '.join(permissions)}[/dim]")
            except APIError as e:
                console.print(f"[yellow]Connection test failed:[/yellow] {e}")
                console.print("[dim]The connector was created but connectivity could not be verified.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@connectors_group.command("test")
@click.argument("connector_id")
@click.option("--report", "report_path", is_flag=False, flag_value="auto", default=None,
              help="Export test results as branded HTML report")
def test_connector(connector_id, report_path):
    """Test a connector's connection to the cloud platform.

    CONNECTOR_ID: Connector UUID.
    """
    client = _require_client()

    try:
        with console.status("Testing connection..."):
            result = client.test_connector(connector_id)

        console.print("[green]Connection test passed.[/green]")

        permissions = result.get("permissions", [])
        if permissions:
            console.print(f"\n[bold]Accessible permissions:[/bold]")
            for p in permissions:
                console.print(f"  [green]+[/green] {p}")

        scopes = result.get("scopes", [])
        if scopes:
            console.print(f"\n[bold]Scopes:[/bold]")
            for s in scopes:
                console.print(f"  {s}")

        # HTML report export
        if report_path is not None:
            from ..report_builder import ReportBuilder, _esc

            rb = ReportBuilder("Connector Test", f"Connector {connector_id}")
            rb.add_status("Connection test passed", level="success")
            rb.add_kv("Details", {"Connector ID": connector_id})

            if permissions:
                rows = [[_esc(p)] for p in permissions]
                rb.add_table("Accessible Permissions", columns=["Permission"], rows=rows)

            if scopes:
                rows = [[_esc(s)] for s in scopes]
                rb.add_table("Scopes", columns=["Scope"], rows=rows)

            saved = rb.save(None if report_path == "auto" else report_path)
            console.print(f"\n[green]Report saved:[/green] {saved}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Connection test failed:[/red] {e}")
        raise SystemExit(1)


@connectors_group.command("update")
@click.argument("connector_id")
@click.option("--name", default=None, help="New display name")
@click.option("--client-secret", default=None, prompt=False, hide_input=True, help="New client secret")
@click.option("--status", "new_status", type=click.Choice(["active", "disabled"]), default=None, help="New status")
def update_connector(connector_id, name, client_secret, new_status):
    """Update a connector's settings.

    CONNECTOR_ID: Connector UUID.

    \b
    Examples:
      hb connectors update <id> --name "New Name"
      hb connectors update <id> --status disabled
    """
    client = _require_client()

    data = {}
    if name:
        data["display_name"] = name
    if new_status:
        data["status"] = new_status
    if client_secret:
        data["credentials"] = {"client_secret": client_secret}

    if not data:
        console.print("[yellow]Nothing to update.[/yellow] Provide --name, --status, or --client-secret.")
        raise SystemExit(1)

    try:
        with console.status("Updating connector..."):
            client.update_connector(connector_id, data)

        console.print("[green]Connector updated.[/green]")
        console.print(f"[dim]ID: {connector_id}[/dim]")
        if name:
            console.print(f"  Name: {name}")
        if new_status:
            console.print(f"  Status: {STATUS_STYLES.get(new_status, new_status)}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@connectors_group.command("delete")
@click.argument("connector_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def remove_connector(connector_id, force):
    """Delete a connector.

    CONNECTOR_ID: Connector UUID.
    """
    client = _require_client()

    if not force:
        if not Confirm.ask(f"Delete connector [bold]{connector_id}[/bold]? This cannot be undone."):
            console.print("[dim]Cancelled.[/dim]")
            return

    try:
        with console.status("Deleting connector..."):
            client.delete_connector(connector_id)

        console.print("[green]Connector deleted.[/green]")
        console.print(f"[dim]ID: {connector_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
