"""Findings commands."""

import json
import click
from rich.console import Console
from rich.table import Table

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

SEVERITY_STYLES = {
    "critical": "[red bold]critical[/red bold]",
    "high": "[red]high[/red]",
    "medium": "[yellow]medium[/yellow]",
    "low": "[cyan]low[/cyan]",
    "info": "[dim]info[/dim]",
}

STATUS_STYLES = {
    "open": "[red]open[/red]",
    "regressed": "[red bold]regressed[/red bold]",
    "stale": "[yellow]stale[/yellow]",
    "fixed": "[green]fixed[/green]",
}


@click.group("findings", invoke_without_command=True)
@click.option("--status", type=click.Choice(["open", "stale", "fixed", "regressed"]), help="Filter by status")
@click.option("--severity", type=click.Choice(["critical", "high", "medium", "low", "info"]), help="Filter by severity")
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def findings_group(ctx, status, severity, page, size, as_json):
    """View and manage security findings.

    \b
    Examples:
      hb findings                        # List all findings
      hb findings --status open          # Filter by status
      hb findings --severity high        # Filter by severity
      hb findings --json                 # JSON output
      hb findings update <id> --status fixed
      hb findings assign <id> --assignee <member-id>
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
        with console.status("Fetching findings..."):
            response = client.list_findings(project_id, status=status, severity=severity, page=page, size=size)

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        findings = response.get("data", []) if isinstance(response, dict) else response

        if not findings:
            console.print("[yellow]No findings found.[/yellow]")
            if not status and not severity:
                console.print("[dim]Run experiments to discover findings.[/dim]")
            return

        table = Table(title="Findings")
        table.add_column("ID", style="dim")
        table.add_column("Title", max_width=40)
        table.add_column("Severity", width=10)
        table.add_column("Status", width=10)
        table.add_column("Category", width=15)
        table.add_column("Occurrences", justify="right", width=6)
        table.add_column("Last Seen", width=12)

        for finding in findings:
            sev = str(finding.get("severity", "")).lower()
            stat = str(finding.get("status", "")).lower()

            table.add_row(
                str(finding.get("id", "")),
                finding.get("title", finding.get("description", ""))[:40],
                SEVERITY_STYLES.get(sev, sev),
                STATUS_STYLES.get(stat, stat),
                finding.get("category", ""),
                str(finding.get("occurrences", finding.get("occurrence_count", ""))),
                str(finding.get("last_seen_at", finding.get("updated_at", "")))[:10],
            )

        console.print(table)

        if isinstance(response, dict) and response.get("has_next_page"):
            console.print(f"\n[dim]Page {page}. Use --page to see more.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@findings_group.command("update")
@click.argument("finding_id")
@click.option("--status", type=click.Choice(["open", "fixed"]), help="New status")
@click.option("--severity", type=click.Choice(["critical", "high", "medium", "low", "info"]), help="New severity")
def update_finding(finding_id: str, status: str, severity: str):
    """Update a finding's status or severity.

    FINDING_ID: Finding UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = client.project_id
    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        raise SystemExit(1)

    if not status and not severity:
        console.print("[yellow]Nothing to update.[/yellow] Provide --status and/or --severity.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        finding_id = _resolve_finding_id(client, project_id, finding_id)

        payload = {}
        if status:
            payload["status"] = status
        if severity:
            payload["severity"] = severity

        with console.status("Updating finding..."):
            client.update_finding(project_id, finding_id, payload)

        console.print(f"[green]Finding updated.[/green]")
        console.print(f"[dim]ID: {finding_id}[/dim]")
        if status:
            console.print(f"  Status: {STATUS_STYLES.get(status, status)}")
        if severity:
            console.print(f"  Severity: {SEVERITY_STYLES.get(severity, severity)}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@findings_group.command("assign")
@click.argument("finding_id")
@click.option("--assignee", required=True, help="Member ID to assign the finding to")
@click.option("--status", "delegation_status",
              type=click.Choice(["assigned", "in_progress", "verified"]),
              default="assigned",
              help="Delegation status (default: assigned)")
def assign_finding(finding_id: str, assignee: str, delegation_status: str):
    """Assign a finding to a team member.

    FINDING_ID: Finding UUID (or partial ID).

    \b
    Examples:
      hb findings assign abc123 --assignee member-uuid
      hb findings assign abc123 --assignee member-uuid --status in_progress
    """
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
        finding_id = _resolve_finding_id(client, project_id, finding_id)

        payload = {
            "assignee_id": assignee,
            "delegation_status": delegation_status,
        }

        with console.status("Assigning finding..."):
            client.update_finding(project_id, finding_id, payload)

        console.print(f"[green]Finding assigned.[/green]")
        console.print(f"[dim]ID: {finding_id}[/dim]")
        console.print(f"  Assignee: {assignee}")
        console.print(f"  Status: {delegation_status}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _resolve_finding_id(client: HumanboundClient, project_id: str, partial_id: str) -> str:
    """Resolve a partial finding ID to full ID."""
    if len(partial_id) >= 32:
        return partial_id

    response = client.list_findings(project_id, page=1, size=50)
    findings = response.get("data", []) if isinstance(response, dict) else response
    for finding in findings:
        if finding.get("id", "").startswith(partial_id):
            return finding.get("id")

    return partial_id
