"""Report generation command."""

import click
from pathlib import Path
from rich.console import Console

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.command("report")
@click.option("--org", is_flag=True, help="Generate org-level report (all projects + inventory)")
@click.option("--assessment", "assessment_id", help="Generate assessment/campaign report by ID")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON instead of HTML")
def report_command(org: bool, assessment_id: str, output: str, as_json: bool):
    """Generate a shareable security report.

    Default: project-level report for current project.
    Use --org for organisation-wide report (all projects + inventory).
    Use --assessment for a specific campaign/assessment report.

    \b
    Examples:
      hb report                          # Current project report
      hb report --org                    # Org-wide report
      hb report --assessment abc123      # Specific assessment
      hb report -o ./report.html         # Custom output path
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    try:
        if org:
            if not client.organisation_id:
                console.print("[yellow]No organisation selected.[/yellow]")
                console.print("Use 'hb switch <id>' to select an organisation.")
                raise SystemExit(1)

            default_output = f"org-report.{'json' if as_json else 'html'}"
            with console.status("Generating organisation report..."):
                response = client.get(
                    f"organisations/{client.organisation_id}/report",
                    include_project=False,
                    params={"format": "json"} if as_json else {},
                )

        elif assessment_id:
            if not client.project_id:
                console.print("[yellow]No project selected.[/yellow]")
                console.print("Use 'hb projects use <id>' to select a project.")
                raise SystemExit(1)

            default_output = f"assessment-{assessment_id[:8]}.{'json' if as_json else 'html'}"
            with console.status("Generating assessment report..."):
                response = client.get(
                    f"projects/{client.project_id}/assessments/{assessment_id}/report",
                    include_project=True,
                    params={"format": "json"} if as_json else {},
                )

        else:
            if not client.project_id:
                console.print("[yellow]No project selected.[/yellow]")
                console.print("Use 'hb projects use <id>' to select a project.")
                raise SystemExit(1)

            default_output = f"project-report.{'json' if as_json else 'html'}"
            with console.status("Generating project report..."):
                response = client.get(
                    f"projects/{client.project_id}/report",
                    include_project=True,
                    params={"format": "json"} if as_json else {},
                )

        # Write output
        filepath = output or default_output

        if as_json:
            import json
            content = json.dumps(response, indent=2, default=str)
        elif isinstance(response, str):
            content = response
        elif isinstance(response, dict) and response.get("html"):
            content = response["html"]
        elif isinstance(response, bytes):
            content = response.decode("utf-8")
        else:
            import json
            content = json.dumps(response, indent=2, default=str)

        Path(filepath).write_text(content)
        console.print(f"[green]Report saved to:[/green] {filepath}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
