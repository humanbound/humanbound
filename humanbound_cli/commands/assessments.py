# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Assessment commands — view past security assessments."""

import json

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

console = Console()

STATUS_STYLES = {
    "completed": "[green]completed[/green]",
    "running": "[yellow]running[/yellow]",
    "failed": "[red]failed[/red]",
    "pending": "[dim]pending[/dim]",
}

GRADE_STYLES = {
    "A": "[green bold]A[/green bold]",
    "B": "[green]B[/green]",
    "C": "[yellow]C[/yellow]",
    "D": "[red]D[/red]",
    "F": "[red bold]F[/red bold]",
}


@click.group("assessments", invoke_without_command=True)
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def assessments_group(ctx, page, size, as_json):
    """View past security assessments.

    Assessments are snapshots of your project's security state produced
    by ASCAM activities (assess, investigate, monitor).

    \b
    Examples:
      hb assessments                    # List past assessments
      hb assessments --json             # JSON output
      hb assessments show <id>          # View assessment detail
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
        with console.status("Fetching assessments..."):
            response = client.get(
                f"projects/{project_id}/assessments",
                params={"page": page, "size": size},
            )

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        assessments = response.get("data", []) if isinstance(response, dict) else response

        if not assessments:
            console.print("[yellow]No assessments found.[/yellow]")
            console.print("[dim]Run 'hb test' or 'hb monitor' to create assessments.[/dim]")
            return

        table = Table(title="Assessments")
        table.add_column("ID", style="dim")
        table.add_column("Scope", width=10)
        table.add_column("Status", width=12)
        table.add_column("Findings", justify="right", width=10)
        table.add_column("Started", width=12)
        table.add_column("Completed", width=12)

        for a in assessments:
            status = str(a.get("status", "")).lower()
            started = str(a.get("started_at", ""))[:10]
            completed = str(a.get("completed_at", "") or "")[:10]

            table.add_row(
                str(a.get("id", "")),
                a.get("scope", ""),
                STATUS_STYLES.get(status, status),
                str(a.get("findings_discovered", "")),
                started,
                completed,
            )

        console.print(table)

        total = response.get("total", 0) if isinstance(response, dict) else len(assessments)
        if total > page * size:
            console.print(f"\n[dim]Page {page}. Use --page to see more.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@assessments_group.command("show")
@click.argument("assessment_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_assessment(assessment_id: str, as_json: bool):
    """Show assessment details.

    ASSESSMENT_ID: Assessment UUID.

    \b
    Examples:
      hb assessments show <id>
      hb assessments show <id> --json
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
        with console.status("Fetching assessment..."):
            response = client.get(f"projects/{project_id}/assessments/{assessment_id}")

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        _display_assessment(response)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _display_assessment(data: dict):
    """Display assessment detail panel."""
    status = str(data.get("status", "")).lower()
    scope = data.get("scope", "security")

    # Posture before/after
    before = data.get("posture_before") or {}
    after = data.get("posture_after") or {}
    score_before = before.get("score", "—")
    score_after = after.get("score", "—")
    grade_before = str(before.get("grade", "—"))
    grade_after = str(after.get("grade", "—"))

    grade_before_styled = GRADE_STYLES.get(grade_before, grade_before)
    grade_after_styled = GRADE_STYLES.get(grade_after, grade_after)

    drift = data.get("drift_score")
    drift_display = f"{drift:+.2f}" if drift is not None else "—"

    lines = [
        f"Scope: [bold]{scope}[/bold]",
        f"Status: {STATUS_STYLES.get(status, status)}",
        f"Tests: {data.get('test_count', '—')}",
        "",
        f"Posture: {grade_before_styled} {score_before} → {grade_after_styled} {score_after}",
        f"Drift: {drift_display}",
    ]

    started = str(data.get("started_at", ""))[:19]
    completed = str(data.get("completed_at", "") or "")[:19]
    if started:
        lines.append("")
        lines.append(f"[dim]Started: {started}[/dim]")
    if completed:
        lines.append(f"[dim]Completed: {completed}[/dim]")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"Assessment {str(data.get('id', ''))[:8]}…",
            border_style="blue",
            padding=(1, 2),
        )
    )

    console.print("\n[dim]Next:[/dim]")
    console.print(
        f"  [bold]hb assessments report {data.get('id', '')}[/bold]  Generate full report"
    )
    console.print("  [bold]hb findings[/bold]                              View current findings")


@assessments_group.command("report")
@click.argument("assessment_id")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--no-open", is_flag=True, help="Save without opening browser")
def assessment_report(assessment_id: str, output: str, no_open: bool):
    """Generate report for a specific assessment.

    \b
    Examples:
      hb assessments report abc123
      hb assessments report abc123 -o report.html
    """
    from ._report_helper import download_and_open

    client = HumanboundClient()
    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow] Run 'hb projects use <id>'")
        raise SystemExit(1)

    download_and_open(
        client,
        f"projects/{client.project_id}/assessments/{assessment_id}/report",
        f"assessment-{assessment_id[:8]}-report.html",
        output=output,
        no_open=no_open,
        include_project=True,
    )
