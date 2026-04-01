"""API key management commands."""

import json
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.group("api-keys", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def api_keys_group(ctx, as_json: bool):
    """Manage API keys. Run without subcommand to list keys."""
    if ctx.invoked_subcommand is not None:
        return
    _list_keys(as_json)


@api_keys_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_keys_cmd(as_json: bool):
    """List all API keys."""
    _list_keys(as_json)


def _list_keys(as_json: bool):
    """List all API keys."""
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    try:
        with console.status("Fetching API keys..."):
            response = client.list_api_keys()

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        keys = response.get("data", []) if isinstance(response, dict) else response
        if isinstance(keys, dict):
            keys = [keys]

        if not keys:
            console.print("[yellow]No API keys found.[/yellow]")
            console.print("[dim]Create one with: hb api-keys create --name \"My Key\"[/dim]")
            return

        table = Table(title="API Keys")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Scopes")
        table.add_column("Active", justify="center")
        table.add_column("Key Prefix", style="dim")
        table.add_column("Created", style="dim")

        for key in keys:
            active = "[green]yes[/green]" if key.get("active", True) else "[red]no[/red]"
            key_val = key.get("key", key.get("key_prefix", ""))
            prefix = (key_val[:12] + "...") if len(str(key_val)) > 12 else str(key_val)

            table.add_row(
                str(key.get("id", "")),
                key.get("name", ""),
                key.get("scopes", ""),
                active,
                prefix,
                str(key.get("created_at", ""))[:10],
            )

        console.print(table)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@api_keys_group.command("create")
@click.option("--name", required=True, help="Name for the API key")
@click.option("--scopes", type=click.Choice(["admin", "write", "read"]), default="admin", help="Key permission scope")
def create_key(name: str, scopes: str):
    """Create a new API key.

    The full key is shown only once after creation - save it immediately.
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    try:
        with console.status("Creating API key..."):
            response = client.create_api_key(name, scopes)

        key_value = response.get("key", response.get("api_key", ""))

        console.print(Panel(
            f"[bold green]{key_value}[/bold green]",
            title="New API Key",
            subtitle="[red bold]Save this key now - it will not be shown again[/red bold]",
            border_style="yellow",
            padding=(1, 2),
        ))

        console.print(f"\n  Name: [bold]{name}[/bold]")
        console.print(f"  Scopes: {scopes}")
        console.print(f"  ID: [dim]{response.get('id', '')}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@api_keys_group.command("update")
@click.argument("key_id")
@click.option("--name", help="New key name")
@click.option("--scopes", type=click.Choice(["admin", "write", "read"]), help="New permission scope")
@click.option("--active/--inactive", default=None, help="Activate or deactivate key")
def update_key(key_id: str, name: str, scopes: str, active):
    """Update an API key.

    KEY_ID: API key UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if name is None and scopes is None and active is None:
        console.print("[yellow]Nothing to update.[/yellow] Provide --name, --scopes, or --active/--inactive.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        key_id = _resolve_key_id(client, key_id)

        payload = {}
        if name is not None:
            payload["name"] = name
        if scopes is not None:
            payload["scopes"] = scopes
        if active is not None:
            payload["active"] = active

        with console.status("Updating API key..."):
            client.update_api_key(key_id, payload)

        console.print(f"[green]API key updated.[/green]")
        console.print(f"[dim]ID: {key_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@api_keys_group.command("delete")
@click.argument("key_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def revoke_key(key_id: str, force: bool):
    """Revoke (delete) an API key.

    KEY_ID: API key UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        key_id = _resolve_key_id(client, key_id)

        if not force:
            if not Confirm.ask(f"Revoke API key [bold]{key_id}[/bold]? Any integrations using this key will stop working"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Revoking API key..."):
            client.delete_api_key(key_id)

        console.print(f"[green]API key revoked.[/green]")
        console.print(f"[dim]ID: {key_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _resolve_key_id(client: HumanboundClient, partial_id: str) -> str:
    """Resolve a partial key ID to full ID."""
    if len(partial_id) >= 32:
        return partial_id

    response = client.list_api_keys()
    keys = response.get("data", []) if isinstance(response, dict) else response
    if isinstance(keys, dict):
        keys = [keys]

    for key in keys:
        if key.get("id", "").startswith(partial_id):
            return key.get("id")

    return partial_id
