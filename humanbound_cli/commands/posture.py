"""Posture command for viewing security posture score."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn

from ..client import HumanboundClient
from ..engine import get_runner
from ..engine.platform_runner import PlatformTestRunner
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.command("posture")
@click.option("--project", "-p", help="Project ID (uses current if not specified)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--trends", is_flag=True, help="Show posture history over time")
@click.option("--org", is_flag=True, help="Show org-level posture (3 dimensions)")
@click.option("--coverage", is_flag=True, help="Include test coverage breakdown")
def posture_command(
    project: str, as_json: bool, trends: bool, org: bool, coverage: bool
):
    """View security posture score for a project.

    The posture score is a composite metric (0-100) reflecting:
    - Finding score: Based on open vulnerabilities
    - Confidence score: Time since last test
    - Coverage score: Attack categories tested
    - Drift score: Response pattern changes

    \b
    Examples:
      hb posture                    # Show current project posture
      hb posture --project abc123   # Show specific project
      hb posture --trends           # Show posture history
      hb posture --org              # Org-level posture (3 dimensions)
      hb posture --coverage         # Include test coverage
      hb posture --json             # Output as JSON
    """
    # --- Runner selection ---
    runner = get_runner()
    is_platform = isinstance(runner, PlatformTestRunner)

    if not is_platform:
        # Local mode
        if trends:
            console.print("[yellow]Posture history requires login.[/yellow]")
            console.print("Track score trends, finding lifecycle, and regressions across scans.\n")
            console.print("  hb login (free, 3 scans/month)")
            raise SystemExit(0)
        if org:
            console.print("[yellow]Organisation posture requires login.[/yellow]")
            console.print("  hb login")
            raise SystemExit(0)
        _local_posture(as_json)
        return

    # Platform mode
    client = runner.client

    # Org-level posture does not require a project
    if org:
        try:
            org_id = client.organisation_id
            if not org_id:
                console.print("[yellow]No organisation selected.[/yellow]")
                console.print("Use 'hb switch <id>' to select an organisation.")
                raise SystemExit(1)

            with console.status("Calculating organisation posture..."):
                response = client.get(
                    f"organisations/{org_id}/posture", include_project=False
                )

            if as_json:
                import json

                print(json.dumps(response, indent=2, default=str))
                return

            _display_org_posture(response)
            return
        except NotAuthenticatedError:
            console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
            raise SystemExit(1)
        except APIError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)

    project_id = project or client.project_id

    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' or --project to specify one.")
        raise SystemExit(1)

    try:
        if trends:
            with console.status("Fetching posture trends..."):
                response = client.get_posture_trends(project_id)

            if as_json:
                import json

                print(json.dumps(response, indent=2, default=str))
                return

            _display_trends(response)
            return

        # Get posture from API
        with console.status("Calculating posture..."):
            response = client.get(
                f"projects/{project_id}/posture", include_project=True
            )

        if as_json:
            import json

            print(json.dumps(response, indent=2, default=str))
            return

        _display_posture(response)

        if coverage:
            try:
                with console.status("Fetching coverage data..."):
                    cov_response = client.get_coverage(project_id, include_gaps=True)
                _display_coverage_section(cov_response)
            except APIError:
                console.print("[dim]Coverage data not available.[/dim]")

        _print_next(org=False, has_coverage=coverage)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        if "404" in str(e) or "not found" in str(e).lower():
            # Posture endpoint might not exist yet - calculate from experiments
            console.print("[yellow]Posture endpoint not available.[/yellow]")
            console.print("Calculating from recent experiments...")
            _calculate_fallback_posture(client, project_id)
        else:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)


def _local_posture(as_json: bool):
    """Read posture from latest local results. Full implementation in Phase 3."""
    from pathlib import Path
    import json

    results_dir = Path(".humanbound/results")
    if not results_dir.exists():
        console.print("[yellow]No local test results found.[/yellow]")
        console.print("Run a test first: hb test --endpoint ./config.json --repo . --wait")
        raise SystemExit(1)

    # Find latest experiment dir
    exp_dirs = sorted(results_dir.iterdir(), reverse=True) if results_dir.is_dir() else []
    if not exp_dirs:
        console.print("[yellow]No experiments found.[/yellow]")
        raise SystemExit(1)

    meta_file = exp_dirs[0] / "meta.json"
    if not meta_file.exists():
        console.print(f"[yellow]No results in {exp_dirs[0].name}.[/yellow]")
        raise SystemExit(1)

    meta = json.loads(meta_file.read_text())
    results = meta.get("results", {})
    posture_data = results.get("posture") or meta.get("posture") or {}

    if as_json:
        print(json.dumps(posture_data, indent=2, default=str))
        return

    # Map local format (posture key) to display format (overall_score key)
    if "posture" in posture_data and "overall_score" not in posture_data:
        posture_data["overall_score"] = posture_data["posture"]

    if not posture_data:
        console.print("[yellow]No posture data in latest experiment.[/yellow]")
        return

    _display_posture(posture_data)

    # Local-specific next steps
    console.print()
    console.print("[dim]Next:[/dim]")
    console.print("  [dim]hb logs                View conversation details[/dim]")
    console.print("  [dim]hb report -o report.html  Generate report[/dim]")
    console.print("  [dim]hb guardrails          Export firewall rules[/dim]")
    console.print("  [dim]hb login               Track posture over time[/dim]")


def _display_posture(posture: dict):
    """Display posture score with visual breakdown."""
    score = posture.get("overall_score", 0)
    grade = posture.get("grade", _score_to_grade(score))

    # Color based on score
    if score >= 80:
        score_color = "green"
        emoji = "✓"
    elif score >= 60:
        score_color = "yellow"
        emoji = "⚠"
    else:
        score_color = "red"
        emoji = "✗"

    # Main score panel
    console.print(
        Panel(
            f"[bold {score_color}]{emoji} {score}/100[/bold {score_color}]  [dim]Grade: {grade}[/dim]",
            title="Security Posture",
            border_style=score_color,
            padding=(1, 4),
        )
    )

    # Breakdown table
    finding_metrics = posture.get("finding_metrics", {})
    coverage_metrics = posture.get("coverage_metrics", {})
    resilience_metrics = posture.get("resilience_metrics", {})

    if finding_metrics or coverage_metrics or resilience_metrics:
        console.print("\n[bold]Score Breakdown:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Component", width=15)
        table.add_column("Score", width=10, justify="right")
        table.add_column("Weight", width=10, justify="right")
        table.add_column("Bar", width=30)

        components = [
            ("Findings", finding_metrics.get("score", 0), "40%"),
            ("Confidence", finding_metrics.get("avg_confidence", 0), "25%"),
            ("Coverage", coverage_metrics.get("score", 0), "20%"),
            ("Resilience", resilience_metrics.get("score", 0), "15%"),
        ]

        for name, comp_score, weight in components:
            bar = _score_bar(comp_score)
            color = (
                "green"
                if comp_score >= 80
                else ("yellow" if comp_score >= 60 else "red")
            )
            table.add_row(
                name,
                f"[{color}]{comp_score:.0f}[/{color}]",
                weight,
                bar,
            )

        console.print(table)

    # Recommendations
    recommendations = posture.get("recommendations", [])
    if recommendations:
        console.print("\n[bold]Recommendations:[/bold]")
        for i, rec in enumerate(recommendations[:3], 1):
            console.print(f"  {i}. {rec}")

    # Last tested
    last_tested = posture.get("last_tested")
    if last_tested:
        console.print(f"\n[dim]Last tested: {last_tested}[/dim]")


def _score_bar(score: float, width: int = 20) -> str:
    """Create a visual score bar."""
    filled = int(score / 100 * width)
    empty = width - filled

    if score >= 80:
        color = "green"
    elif score >= 60:
        color = "yellow"
    else:
        color = "red"

    return f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/dim]"


def _score_to_grade(score: float) -> str:
    """Convert numeric score to letter grade."""
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


def _display_trends(response):
    """Display posture trend history."""
    trends = response.get("data", response) if isinstance(response, dict) else response

    if isinstance(trends, dict):
        snapshots = trends.get("snapshots", trends.get("data", []))
    else:
        snapshots = trends

    if not snapshots:
        console.print("[yellow]No posture history available yet.[/yellow]")
        console.print("Run some experiments to build trend data.")
        return

    table = Table(title="Posture History")
    table.add_column("Date", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Grade", justify="center")
    table.add_column("Change", justify="center")

    prev_score = None
    for snapshot in snapshots:
        score = snapshot.get("score", 0)
        grade = snapshot.get("grade", _score_to_grade(score))
        date = str(snapshot.get("created_at", snapshot.get("date", "")))[:10]

        # Color score
        if score >= 80:
            score_color = "green"
        elif score >= 60:
            score_color = "yellow"
        else:
            score_color = "red"

        # Trend direction
        if prev_score is not None:
            diff = score - prev_score
            if diff > 0:
                change = f"[green]+{diff:.0f}[/green]"
            elif diff < 0:
                change = f"[red]{diff:.0f}[/red]"
            else:
                change = "[dim]-[/dim]"
        else:
            change = "[dim]-[/dim]"

        table.add_row(
            date,
            f"[{score_color}]{score:.0f}[/{score_color}]",
            grade,
            change,
        )

        prev_score = score

    console.print(table)


def _calculate_fallback_posture(client: HumanboundClient, project_id: str):
    """Calculate posture from experiment data when endpoint is unavailable."""
    try:
        # Get recent experiments
        original_project = client.project_id
        client.set_project(project_id)

        response = client.list_experiments(page=1, size=10)
        experiments = response.get("data", [])

        if not experiments:
            console.print("[yellow]No experiments found. Run 'hb test' first.[/yellow]")
            return

        # Calculate simple posture from most recent experiment
        latest = experiments[0]
        results = latest.get("results", {})
        stats = results.get("stats", {})

        total = stats.get("total", 0)
        passed = stats.get("pass", 0)
        failed = stats.get("fail", 0)

        if total > 0:
            pass_rate = (passed / total) * 100
        else:
            pass_rate = 0

        # Simple score based on pass rate
        score = min(100, pass_rate)

        posture = {
            "overall_score": score,
            "grade": _score_to_grade(score),
            "finding_metrics": {"score": pass_rate},
            "coverage_metrics": {"score": 70},
            "resilience_metrics": {"score": 85},
            "recommendations": [],
            "last_tested": latest.get("created_at", "")[:10],
        }

        if pass_rate < 80:
            posture["recommendations"].append("Address failing security tests")
        if len(experiments) < 3:
            posture["recommendations"].append("Run more comprehensive tests")

        _display_posture(posture)

        # Restore original project
        if original_project:
            client.set_project(original_project)

    except Exception as e:
        console.print(f"[red]Error calculating posture:[/red] {e}")


def _display_org_posture(response: dict):
    """Display org-level posture with 3 dimensions."""
    score = response.get("score", 0)
    grade = response.get("grade", _score_to_grade(score))

    # Color based on score
    if score >= 80:
        score_color = "green"
        emoji = "✓"
    elif score >= 60:
        score_color = "yellow"
        emoji = "⚠"
    else:
        score_color = "red"
        emoji = "✗"

    # Main score panel
    console.print(
        Panel(
            f"[bold {score_color}]{emoji} {score}/100[/bold {score_color}]  [dim]Grade: {grade}[/dim]",
            title="Organisation Posture",
            border_style=score_color,
            padding=(1, 4),
        )
    )

    # Dimension breakdown
    dimensions = response.get("dimensions", {})
    if dimensions:
        console.print("\n[bold]Dimensions:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Dimension", width=20)
        table.add_column("Score", width=10, justify="right")
        table.add_column("Bar", width=30)

        dimension_labels = {
            "agent_security": "Agent Security",
            "shadow_ai": "Shadow AI",
            "quality": "Quality",
        }

        for key, label in dimension_labels.items():
            dim_data = dimensions.get(key, {})
            dim_score = (
                dim_data.get("score", 0) if isinstance(dim_data, dict) else dim_data
            )
            bar = _score_bar(dim_score)
            color = (
                "green" if dim_score >= 80 else ("yellow" if dim_score >= 60 else "red")
            )
            table.add_row(
                label,
                f"[{color}]{dim_score:.0f}[/{color}]",
                bar,
            )

        console.print(table)

    _print_next(org=True)


def _display_coverage_section(response: dict):
    """Display coverage as a section below posture."""
    overall = response.get("overall_coverage", response.get("coverage_percentage", 0))

    # Color based on coverage
    if overall >= 80:
        cov_color = "green"
    elif overall >= 50:
        cov_color = "yellow"
    else:
        cov_color = "red"

    # Overall coverage bar
    bar_width = 30
    filled = int(overall / 100 * bar_width)
    empty = bar_width - filled
    bar = f"[{cov_color}]{'█' * filled}[/{cov_color}][dim]{'░' * empty}[/dim]"

    console.print(
        f"\n[bold]Test Coverage:[/bold]  {bar}  [{cov_color}]{overall:.0f}%[/{cov_color}]"
    )

    # Category breakdown
    categories = response.get("categories", response.get("by_category", []))
    if categories:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Category", width=25)
        table.add_column("Tests", justify="right", width=8)
        table.add_column("Pass Rate", justify="right", width=10)

        for cat in categories:
            name = cat.get("category", cat.get("name", ""))
            total = cat.get("total", cat.get("tests_run", 0))
            passed = cat.get("pass", cat.get("passed", 0))

            if total > 0:
                rate = (passed / total) * 100
                rate_color = (
                    "green" if rate >= 80 else ("yellow" if rate >= 50 else "red")
                )
                rate_str = f"[{rate_color}]{rate:.0f}%[/{rate_color}]"
            else:
                rate_str = "[dim]-[/dim]"

            table.add_row(name, str(total), rate_str)

        console.print(table)

    # Gaps
    gap_list = response.get("gaps", response.get("untested", []))
    if gap_list:
        console.print(f"\n[yellow]Gaps ({len(gap_list)} untested):[/yellow]")
        for gap in gap_list[:5]:
            name = (
                gap.get("category", gap.get("name", str(gap)))
                if isinstance(gap, dict)
                else str(gap)
            )
            console.print(f"  - {name}")
        if len(gap_list) > 5:
            console.print(f"  [dim]... and {len(gap_list) - 5} more[/dim]")


def _print_next(org: bool = False, has_coverage: bool = False):
    """Print contextual next-step suggestions."""
    console.print()
    suggestions = []
    if org:
        suggestions.append("hb posture -p <id>      View project-level posture")
        suggestions.append("hb findings             Review open findings")
        suggestions.append("hb report --org         Generate org posture report")
    else:
        if not has_coverage:
            suggestions.append(
                "hb posture --coverage   Include test coverage breakdown"
            )
        suggestions.append("hb posture --trends     View posture over time")
        suggestions.append("hb posture --org        View org-level posture")
        suggestions.append("hb test                 Run tests to improve posture")

    console.print("[dim]Next:[/dim]")
    for s in suggestions:
        console.print(f"  [dim]{s}[/dim]")
