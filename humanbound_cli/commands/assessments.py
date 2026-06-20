# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Assessment commands — view past security assessments."""

import datetime as _dt
import json

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .. import telemetry
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


def _epoch_date(ts) -> str:
    """Format an epoch-seconds value as YYYY-MM-DD (UTC).

    started_at/completed_at come back as epoch numbers; the old code sliced
    them as if they were ISO strings (showing raw epochs). Falls back to the
    first 10 chars for an already-string value, or "" when absent.
    """
    if ts in (None, ""):
        return ""
    try:
        return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return str(ts)[:10]


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
        telemetry.fire_gated_command_hit()
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
        table.add_column("Domain", width=18)  # fits "security, quality" on one line
        table.add_column("Status", width=12)
        table.add_column("Posture", width=11)
        table.add_column("Drift", justify="right", width=8)
        table.add_column("New Findings", justify="right", width=12)
        table.add_column("Started", width=12)
        table.add_column("Completed", width=12)

        for a in assessments:
            status = str(a.get("status", "")).lower()
            started = _epoch_date(a.get("started_at"))
            completed = _epoch_date(a.get("completed_at"))

            # Posture grade + score from the completion snapshot ({posture, grade}).
            posture = a.get("posture_after") or {}
            grade = posture.get("grade")
            score = posture.get("posture")
            posture_display = (
                f"{GRADE_STYLES.get(str(grade), str(grade))} {score:.0f}"
                if grade is not None and score is not None
                else "—"
            )

            # Drift = change in posture vs the previous assessment.
            drift = a.get("drift_score")
            drift_display = f"{drift:+.2f}" if isinstance(drift, (int, float)) else "—"

            table.add_row(
                str(a.get("id", "")),
                ", ".join(a.get("domain") or []),
                STATUS_STYLES.get(status, status),
                posture_display,
                drift_display,
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
@click.argument("assessment_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_assessment(assessment_id: str, as_json: bool):
    """Show assessment details (defaults to the latest assessment).

    ASSESSMENT_ID: Assessment UUID (optional; the latest assessment is shown
    when omitted).

    \b
    Examples:
      hb assessments show            # latest assessment
      hb assessments show <id>
      hb assessments show <id> --json
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
        # Default to the latest assessment when no id is given.
        if not assessment_id:
            with console.status("Fetching latest assessment..."):
                latest = client.get_campaign(project_id)
            camp = latest.get("campaign", latest) if isinstance(latest, dict) else {}
            assessment_id = (camp or {}).get("id", "")
            if not assessment_id:
                console.print("[yellow]No assessments found.[/yellow]")
                console.print("[dim]Run 'hb test' to create one.[/dim]")
                return

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
    """Display assessment detail — richer than the list row.

    Adds what the list can't show per row: the posture *trajectory*
    (before → after) with a trend read, the drift, the coverage breadth, and
    a human-readable run duration.
    """
    status = str(data.get("status", "")).lower()
    activity = str(data.get("activity", "") or "")
    domain = ", ".join(data.get("domain") or []) or "—"

    # Posture trajectory. Snapshot dicts are {posture: score, grade}.
    before = data.get("posture_before") or {}
    after = data.get("posture_after") or {}
    grade_before = str(before.get("grade", "—"))
    grade_after = str(after.get("grade", "—"))
    score_before = before.get("posture")
    score_after = after.get("posture")
    gb = GRADE_STYLES.get(grade_before, grade_before)
    ga = GRADE_STYLES.get(grade_after, grade_after)
    sb = f"{score_before:.0f}" if isinstance(score_before, (int, float)) else "—"
    sa = f"{score_after:.0f}" if isinstance(score_after, (int, float)) else "—"

    # Trend from the score delta (higher posture = better security).
    trend = ""
    if isinstance(score_before, (int, float)) and isinstance(score_after, (int, float)):
        delta = score_after - score_before
        if delta > 0:
            trend = f"[green]▲ +{delta:.0f} improved[/green]"
        elif delta < 0:
            trend = f"[red]▼ {delta:.0f} regressed[/red]"
        else:
            trend = "[dim]→ no change[/dim]"

    drift = data.get("drift_score")
    drift_display = f"{drift:+.2f}" if isinstance(drift, (int, float)) else "—"

    # Coverage breadth from the discovery plan (count + testing levels).
    entries = (data.get("discovery_plan") or {}).get("entries") or []
    levels = sorted(
        {str(e.get("level", "")) for e in entries if isinstance(e, dict) and e.get("level")}
    )
    coverage = f"{len(entries)} test group(s)" + (
        f" · levels: {', '.join(levels)}" if levels else ""
    )

    # Timestamps are epoch seconds → render readable + compute duration.
    def _fmt(ts):
        try:
            return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        except (TypeError, ValueError):
            return None

    started_raw = data.get("started_at")
    completed_raw = data.get("completed_at")
    started = _fmt(started_raw)
    completed = _fmt(completed_raw)
    duration = ""
    try:
        if started_raw and completed_raw:
            secs = int(float(completed_raw) - float(started_raw))
            if secs >= 0:
                m, s = divmod(secs, 60)
                duration = f"{m}m {s}s" if m else f"{s}s"
    except (TypeError, ValueError):
        pass

    lines = [
        f"Status:   {STATUS_STYLES.get(status, status)}",
        f"Activity: {activity or '—'}",
        f"Domain:   [bold]{domain}[/bold]",
        f"Tests:    {data.get('test_count', '—')}",
        "",
        f"Posture:  {gb} {sb} → {ga} {sa}   {trend}".rstrip(),
        f"Drift:    {drift_display}",
        "",
        f"Coverage: {coverage}",
    ]
    if started:
        lines.append("")
        lines.append(f"[dim]Started:   {started}[/dim]")
    if completed:
        suffix = f"   ([dim]{duration}[/dim])" if duration else ""
        lines.append(f"[dim]Completed: {completed}[/dim]{suffix}")

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


@assessments_group.command("terminate")
@click.argument("assessment_id", required=False)
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def terminate_assessment(assessment_id: str, force: bool):
    """Terminate a running assessment (defaults to the latest).

    Stops the assessment and all of its running experiments.

    \b
    Examples:
      hb assessments terminate          # the current/latest assessment
      hb assessments terminate <id>
      hb assessments terminate --force
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
        # Default to the current/latest assessment when no id is given.
        status = ""
        if not assessment_id:
            with console.status("Fetching current assessment..."):
                response = client.get_campaign(project_id)
            camp = response.get("campaign", response) if isinstance(response, dict) else {}
            assessment_id = (camp or {}).get("id", "")
            status = (camp or {}).get("status", "")
            if not assessment_id:
                console.print("[yellow]No active assessment found.[/yellow]")
                return

        if status in ("completed", "broken"):
            console.print(f"[yellow]Assessment is already {status}.[/yellow]")
            return

        if not force:
            if not Confirm.ask(
                f"Terminate assessment [bold]{assessment_id}[/bold]? Running experiments will be stopped"
            ):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Terminating assessment..."):
            client.terminate_campaign(project_id, assessment_id)

        console.print("[green]Assessment terminated.[/green]")
        console.print(f"[dim]ID: {assessment_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


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
