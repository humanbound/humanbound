"""Report generation command."""

import click
import json as _json
from pathlib import Path
from rich.console import Console

from ..client import HumanboundClient
from ..engine import get_runner
from ..engine.platform_runner import PlatformTestRunner
from ..exceptions import NotAuthenticatedError, APIError

console = Console()


@click.command("report")
@click.option("--org", is_flag=True, help="Generate org-level report (all projects + inventory)")
@click.option("--assessment", "assessment_id", help="Generate assessment/campaign report by ID")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON instead of HTML")
def report_command(org: bool, assessment_id: str, output: str, as_json: bool):
    """Generate a shareable security report.

    \b
    Local mode:
      hb report                          # Report from latest local test
      hb report -o report.html           # Custom output path
      hb report --json -o results.json   # JSON format

    \b
    Platform mode:
      hb report                          # Current project report
      hb report --org                    # Org-wide report
      hb report --assessment abc123      # Specific assessment
    """
    runner = get_runner()
    is_platform = isinstance(runner, PlatformTestRunner)

    if not is_platform:
        if org:
            console.print("[yellow]Organisation report requires login.[/yellow]")
            console.print("  hb login")
            raise SystemExit(0)
        if assessment_id:
            console.print("[yellow]Assessment report requires login.[/yellow]")
            console.print("  hb login")
            raise SystemExit(0)
        _local_report(output, as_json)
        return

    client = runner.client

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


def _local_report(output: str, as_json: bool):
    """Generate report from local test results."""
    results_dir = Path(".humanbound/results")
    if not results_dir.exists():
        console.print("[yellow]No local test results found.[/yellow]")
        console.print("Run a test first: hb test --endpoint ./config.json --repo . --wait")
        raise SystemExit(1)

    # Find latest experiment
    exp_dirs = sorted(results_dir.iterdir(), reverse=True)
    if not exp_dirs:
        console.print("[yellow]No experiments found.[/yellow]")
        raise SystemExit(1)

    exp_dir = exp_dirs[0]
    meta_file = exp_dir / "meta.json"
    logs_file = exp_dir / "logs.jsonl"

    if not meta_file.exists():
        console.print(f"[yellow]No results in {exp_dir.name}.[/yellow]")
        raise SystemExit(1)

    meta = _json.loads(meta_file.read_text())

    # Read logs
    logs = []
    if logs_file.exists():
        for line in logs_file.read_text().strip().split("\n"):
            if line.strip():
                logs.append(_json.loads(line))

    if as_json:
        export = {
            "experiment": meta,
            "logs": logs,
            "total_logs": len(logs),
        }
        content = _json.dumps(export, indent=2, default=str)
        filepath = output or f"report-{exp_dir.name}.json"
    else:
        # Build experiment dict matching what generate_html_report expects
        experiment = {
            "id": meta.get("id", exp_dir.name),
            "name": meta.get("name", "Local Experiment"),
            "status": meta.get("status", "Finished"),
            "test_category": meta.get("test_category", ""),
            "testing_level": meta.get("testing_level", ""),
            "lang": meta.get("lang", ""),
            "created_at": meta.get("created_at", ""),
            "results": {
                "stats": meta.get("stats", {}),
                "insights": meta.get("insights", []),
                "posture": meta.get("posture", {}),
                "exec_t": meta.get("exec_t", {}),
                "tests": {},
            },
        }

        from ..report import generate_html_report
        content = generate_html_report(experiment, logs)
        filepath = output or f"report-{exp_dir.name}.html"

    Path(filepath).write_text(content)
    console.print(f"[green]Report saved to:[/green] {filepath}")
