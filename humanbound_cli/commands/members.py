"""Organisation member management commands."""

import json
import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.group("members", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def members_group(ctx, as_json: bool):
    """Manage organisation members. Run without subcommand to list members."""
    if ctx.invoked_subcommand is not None:
        return
    _list_members(as_json)


@members_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_members_cmd(as_json: bool):
    """List organisation members."""
    _list_members(as_json)


def _list_members(as_json: bool):
    """List organisation members."""
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select one first.")
        raise SystemExit(1)

    try:
        with console.status("Fetching members..."):
            response = client.list_members()

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        members = response.get("data", []) if isinstance(response, dict) else response

        if not members:
            console.print("[yellow]No members found.[/yellow]")
            return

        table = Table(title="Organisation Members")
        table.add_column("ID", style="dim")
        table.add_column("Email", style="bold")
        table.add_column("Username")
        table.add_column("Role")
        table.add_column("Joined", style="dim")

        for member in members:
            role = member.get("access_level", member.get("role", ""))
            role_style = {
                "owner": "[bold yellow]owner[/bold yellow]",
                "admin": "[bold cyan]admin[/bold cyan]",
                "developer": "developer",
            }.get(str(role).lower(), str(role))

            table.add_row(
                str(member.get("id", "")),
                member.get("email", ""),
                member.get("username", ""),
                role_style,
                str(member.get("created_at", member.get("joined_at", "")))[:10],
            )

        console.print(table)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@members_group.command("invite")
@click.argument("email")
@click.option("--role", type=click.Choice(["admin", "developer", "expert"]), default="developer", help="Access level for the member")
def invite_member(email: str, role: str):
    """Invite a member to the organisation.

    EMAIL: Email address to invite.
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select one first.")
        raise SystemExit(1)

    try:
        with console.status(f"Inviting {email}..."):
            client.invite_member(email, role)

        console.print(f"[green]Invitation sent.[/green]")
        console.print(f"  Email: [bold]{email}[/bold]")
        console.print(f"  Role: {role}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@members_group.command("delete")
@click.argument("member_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def remove_member(member_id: str, force: bool):
    """Remove a member from the organisation.

    MEMBER_ID: Member UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select one first.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        member_id = _resolve_member_id(client, member_id)

        if not force:
            if not Confirm.ask(f"Remove member [bold]{member_id}[/bold] from the organisation?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Removing member..."):
            client.remove_member(member_id)

        console.print(f"[green]Member removed.[/green]")
        console.print(f"[dim]ID: {member_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _resolve_member_id(client: HumanboundClient, partial_id: str) -> str:
    """Resolve a partial member ID to full ID."""
    if len(partial_id) >= 32:
        return partial_id

    response = client.list_members()
    members = response.get("data", []) if isinstance(response, dict) else response

    for member in members:
        if member.get("id", "").startswith(partial_id):
            return member.get("id")

    return partial_id
