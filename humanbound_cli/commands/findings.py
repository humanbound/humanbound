# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Findings commands."""

import json
import time

import click
from rich.console import Console
from rich.table import Table

from .. import telemetry
from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

console = Console()


def _fire_findings_view(filter_applied: bool) -> None:
    telemetry.capture(
        "findings_view",
        {"filter_applied": filter_applied},
    )


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

# Regression retest outcomes (from the _regression harness).
OUTCOME_STYLES = {
    "still_vulnerable": "[red bold]still_vulnerable[/red bold]",
    "not_reproduced": "[green]not_reproduced[/green]",
    "insufficient_evidence": "[yellow]insufficient_evidence[/yellow]",
}

# Experiment statuses that end a run (mirrors experiments.py).
TERMINAL_STATUSES = ["Finished", "Failed"]


@click.group("findings", invoke_without_command=True)
@click.option(
    "--status", type=click.Choice(["open", "stale", "fixed", "regressed"]), help="Filter by status"
)
@click.option(
    "--severity",
    type=click.Choice(["critical", "high", "medium", "low", "info"]),
    help="Filter by severity",
)
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--output", "-o", type=click.Path(), default=None, help="Save output to file (JSON)")
@click.pass_context
def findings_group(ctx, status, severity, page, size, as_json, output):
    """View and manage security findings.

    \b
    Examples:
      hb findings                        # List all findings
      hb findings --status open          # Filter by status
      hb findings --severity high        # Filter by severity
      hb findings --json                 # JSON to stdout
      hb findings -o findings.json       # Save to file
      hb findings update <id> --status fixed
      hb findings assign <id> --assignee <member-id>
      hb findings retest <id>            # Verify a fix by replaying its attacks
      hb findings regressions <id>       # Retest history
    """
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
        with console.status("Fetching findings..."):
            response = client.list_findings(
                project_id, status=status, severity=severity, page=page, size=size
            )

        findings = response.get("data", []) if isinstance(response, dict) else response
        filter_applied = bool(status or severity)

        if output:
            from pathlib import Path

            Path(output).write_text(json.dumps(response, indent=2, default=str))
            console.print(f"[green]Findings saved to:[/green] {output}")
            _fire_findings_view(filter_applied=filter_applied)
            return

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            _fire_findings_view(filter_applied=filter_applied)
            return

        if not findings:
            console.print("[yellow]No findings found.[/yellow]")
            if not status and not severity:
                console.print("[dim]Run experiments to discover findings.[/dim]")
            _fire_findings_view(filter_applied=filter_applied)
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

        _fire_findings_view(filter_applied=filter_applied)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@findings_group.command("update")
@click.argument("finding_id")
@click.option("--status", type=click.Choice(["open", "fixed"]), help="New status")
@click.option(
    "--severity",
    type=click.Choice(["critical", "high", "medium", "low", "info"]),
    help="New severity",
)
def update_finding(finding_id: str, status: str, severity: str):
    """Update a finding's status or severity.

    FINDING_ID: Finding UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        telemetry.fire_gated_command_hit()
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

        console.print("[green]Finding updated.[/green]")
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
@click.option(
    "--delegation-status",
    "delegation_status",
    type=click.Choice(["assigned", "in_progress", "verified"]),
    default="assigned",
    help="Delegation status (default: assigned)",
)
def assign_finding(finding_id: str, assignee: str, delegation_status: str):
    """Assign a finding to a team member.

    FINDING_ID: Finding UUID (or partial ID).

    \b
    Examples:
      hb findings assign abc123 --assignee member-uuid
      hb findings assign abc123 --assignee member-uuid --delegation-status in_progress
    """
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
        finding_id = _resolve_finding_id(client, project_id, finding_id)

        payload = {
            "assignee_id": assignee,
            "delegation_status": delegation_status,
        }

        with console.status("Assigning finding..."):
            client.update_finding(project_id, finding_id, payload)

        console.print("[green]Finding assigned.[/green]")
        console.print(f"[dim]ID: {finding_id}[/dim]")
        console.print(f"  Assignee: {assignee}")
        console.print(f"  Status: {delegation_status}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@findings_group.command("retest")
@click.argument("finding_id")
@click.option(
    "--testing-level",
    "-l",
    type=click.Choice(["unit", "system", "acceptance"], case_sensitive=False),
    default="unit",
    help="Replay breadth: unit (representatives), system (+samples), acceptance (+more).",
)
@click.option("--deep", is_flag=True, default=False, help="Shortcut for --testing-level system.")
@click.option(
    "--full", is_flag=True, default=False, help="Shortcut for --testing-level acceptance."
)
@click.option(
    "--watch", "-w", is_flag=True, help="Poll until the retest completes and show the outcome."
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def retest_finding(
    finding_id: str, testing_level: str, deep: bool, full: bool, watch: bool, as_json: bool
):
    """Retest a finding to check whether it is actually fixed.

    Replays the finding's own recorded attacks against the current agent. By
    default this fires the retest and returns the experiment id; poll it with
    'hb experiments status <id>' or pass --watch to wait for the outcome.

    Testing levels mirror 'hb test': unit (representatives only), system and
    acceptance add cluster samples for broader coverage.

    FINDING_ID: Finding UUID (or partial ID).

    \b
    Examples:
      hb findings retest abc123                       # Fire and return the experiment id
      hb findings retest abc123 --watch               # Wait for the outcome
      hb findings retest abc123 --full                # Broadest replay (acceptance)
    """
    # Shortcuts only apply when an explicit level wasn't given (matches hb test).
    if deep and testing_level == "unit":
        testing_level = "system"
    elif full and testing_level == "unit":
        testing_level = "acceptance"

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
        # Resolve partial ID (needs the project); the retest call is org-scoped.
        finding_id = _resolve_finding_id(client, project_id, finding_id)

        with console.status("Starting retest..."):
            response = client.retest_finding(finding_id, testing_level=testing_level)

        experiment_id = response.get("experiment_id") if isinstance(response, dict) else None

        if not watch:
            if as_json:
                print(json.dumps(response, indent=2, default=str))
                return
            console.print("[green]Retest started.[/green]")
            console.print(f"  Experiment: [dim]{experiment_id}[/dim]")
            console.print(f"  Testing level: {testing_level}")
            console.print(f"\n[dim]Poll with:[/dim] hb experiments status {experiment_id} --watch")
            return

        if not experiment_id:
            console.print("[red]Error:[/red] retest did not return an experiment id.")
            raise SystemExit(1)

        # --watch: poll to completion, then read the outcome off the experiment.
        with console.status("Retest running...") as spin:
            while True:
                status_resp = client.get_experiment_status(experiment_id)
                current_status = (
                    status_resp.get("status", "Unknown")
                    if isinstance(status_resp, dict)
                    else "Unknown"
                )
                spin.update(f"Retest running... ({current_status})")
                if current_status in TERMINAL_STATUSES:
                    break
                time.sleep(15)

        experiment = client.get_experiment(experiment_id)
        results = experiment.get("results", {}) if isinstance(experiment, dict) else {}
        regression = results.get("regression") or {}
        outcome = regression.get("outcome")

        if as_json:
            print(json.dumps({"experiment_id": experiment_id, **regression}, indent=2, default=str))
        else:
            if current_status == "Failed":
                console.print("[red]Retest experiment failed.[/red]")
            elif outcome:
                console.print(f"Outcome: {OUTCOME_STYLES.get(outcome, outcome)}")
                if regression.get("partial"):
                    console.print("[dim]  (partial — some vectors errored)[/dim]")
            else:
                console.print(
                    "[yellow]Retest finished but no regression outcome was recorded.[/yellow]"
                )

        if current_status == "Failed" or outcome == "still_vulnerable":
            raise SystemExit(1)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@findings_group.command("regressions")
@click.argument("finding_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def finding_regressions(finding_id: str, as_json: bool):
    """Show a finding's regression-retest history (newest first).

    FINDING_ID: Finding UUID (or partial ID).
    """
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
        finding_id = _resolve_finding_id(client, project_id, finding_id)

        with console.status("Fetching retest history..."):
            history = client.list_finding_regressions(finding_id)

        if as_json:
            print(json.dumps(history, indent=2, default=str))
            return

        if not history:
            console.print("[yellow]This finding has never been retested.[/yellow]")
            console.print(f"[dim]Run 'hb findings retest {finding_id}' to start one.[/dim]")
            return

        table = Table(title="Regression history")
        table.add_column("Experiment", style="dim")
        table.add_column("Outcome", width=22)
        table.add_column("Partial", width=8)
        table.add_column("Level", width=10)
        table.add_column("Created", width=12)

        for entry in history:
            outcome = str(entry.get("outcome") or "")
            table.add_row(
                str(entry.get("experiment_id", "")),
                OUTCOME_STYLES.get(outcome, outcome),
                "yes" if entry.get("partial") else "",
                str(entry.get("testing_level") or ""),
                str(entry.get("created_at") or "")[:10],
            )

        console.print(table)

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
