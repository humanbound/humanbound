"""Coverage command for viewing test coverage.

DEPRECATED: 'hb coverage' is deprecated in favour of 'hb posture --coverage'.
This module is kept for backward compatibility. Remove after v2.0.
"""

import json
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

# DEPRECATED: remove after v2.0 — replaced by 'hb posture --coverage'
_DEPRECATION_MSG = (
    "[yellow]Warning:[/yellow] 'hb coverage' is deprecated. "
    "Use [bold]hb posture --coverage[/bold] instead."
)


@click.command("coverage")
@click.option("--project", "-p", help="Project ID (uses current if not specified)")
@click.option("--gaps", is_flag=True, help="Include untested categories")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def coverage_command(project: str, gaps: bool, as_json: bool):
    """View test coverage for a project.

    DEPRECATED: Use 'hb posture --coverage' instead. This command will be
    removed in a future version.

    Shows how much of the attack surface has been tested, broken down
    by category and test family.

    \b
    Examples:
      hb coverage                    # Coverage summary
      hb coverage --gaps             # Show untested areas
      hb coverage --json             # JSON output
    """
    # DEPRECATED: remove after v2.0
    console.print(_DEPRECATION_MSG)
    console.print()

    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = project or client.project_id

    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' or --project to specify one.")
        raise SystemExit(1)

    try:
        with console.status("Fetching coverage data..."):
            response = client.get_coverage(project_id, include_gaps=gaps)

        if as_json:
            print(json.dumps(response, indent=2, default=str))
            return

        _display_coverage(response, gaps)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _display_coverage(response: dict, show_gaps: bool):
    """Display coverage data with visual breakdown."""
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

    console.print(Panel(
        f"{bar}  [{cov_color}]{overall:.0f}%[/{cov_color}]",
        title="Test Coverage",
        border_style=cov_color,
        padding=(1, 2),
    ))

    # Category breakdown
    categories = response.get("categories", response.get("by_category", []))
    if categories:
        console.print("\n[bold]Coverage by Category:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Category", width=25)
        table.add_column("Tests Run", justify="right", width=10)
        table.add_column("Pass", justify="right", width=8)
        table.add_column("Fail", justify="right", width=8)
        table.add_column("Pass Rate", justify="right", width=10)

        for cat in categories:
            name = cat.get("category", cat.get("name", ""))
            total = cat.get("total", cat.get("tests_run", 0))
            passed = cat.get("pass", cat.get("passed", 0))
            failed = cat.get("fail", cat.get("failed", 0))

            if total > 0:
                rate = (passed / total) * 100
                rate_color = "green" if rate >= 80 else ("yellow" if rate >= 50 else "red")
                rate_str = f"[{rate_color}]{rate:.0f}%[/{rate_color}]"
            else:
                rate_str = "[dim]-[/dim]"

            table.add_row(
                name,
                str(total),
                f"[green]{passed}[/green]",
                f"[red]{failed}[/red]" if failed > 0 else str(failed),
                rate_str,
            )

        console.print(table)

    # Test family breakdown
    families = response.get("by_family", response.get("families", {}))
    if families:
        console.print("\n[bold]By Test Family:[/bold]")
        for family, data in (families.items() if isinstance(families, dict) else []):
            pct = data.get("coverage", data.get("percentage", 0)) if isinstance(data, dict) else data
            color = "green" if pct >= 80 else ("yellow" if pct >= 50 else "red")
            console.print(f"  {family}: [{color}]{pct:.0f}%[/{color}]")

    # Gaps
    if show_gaps:
        gap_list = response.get("gaps", response.get("untested", []))
        if gap_list:
            console.print("\n[bold]Untested Categories:[/bold]\n")

            gap_table = Table(show_header=True, header_style="bold")
            gap_table.add_column("Category", width=25)
            gap_table.add_column("Priority", width=10)

            for gap in gap_list:
                if isinstance(gap, dict):
                    name = gap.get("category", gap.get("name", ""))
                    priority = str(gap.get("priority", ""))
                    priority_style = {
                        "1": "[red bold]P1[/red bold]",
                        "2": "[red]P2[/red]",
                        "3": "[yellow]P3[/yellow]",
                        "4": "[cyan]P4[/cyan]",
                        "5": "[dim]P5[/dim]",
                    }.get(priority, priority)
                else:
                    name = str(gap)
                    priority_style = ""

                gap_table.add_row(name, priority_style)

            console.print(gap_table)
        else:
            console.print("\n[green]Full coverage - no gaps detected.[/green]")
