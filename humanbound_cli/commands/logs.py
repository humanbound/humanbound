"""Logs command for retrieving and exporting experiment results."""

import click
from rich.console import Console
from rich.table import Table
import json
from datetime import datetime, timedelta
from pathlib import Path

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()
console_err = Console(stderr=True)


@click.group("logs", invoke_without_command=True)
@click.argument("experiment_id", required=False)
@click.option(
    "--format", "-f", "output_format",
    type=click.Choice(["table", "json", "html"]),
    default="table",
    help="Output format"
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output file path (prints to stdout if not specified)"
)
@click.option(
    "--verdict", "-v",
    type=click.Choice(["pass", "fail", "all"]),
    default="all",
    help="Filter by verdict"
)
@click.option(
    "--page", default=1, help="Page number (for table format)"
)
@click.option(
    "--size", default=50, help="Items per page (for table format)"
)
@click.option(
    "--all", "fetch_all", is_flag=True, help="Fetch all logs (for json format)"
)
@click.option(
    "--last", "last_n", type=int, help="Logs from last N experiments"
)
@click.option(
    "--category", "test_category", help="Filter by test category (substring match)"
)
@click.option(
    "--from", "from_date", help="Start date (ISO 8601, e.g. 2026-01-01)"
)
@click.option(
    "--until", "until_date", help="End date (ISO 8601)"
)
@click.option(
    "--days", type=int, help="Last N days (shortcut for --from)"
)
@click.option(
    "--assessment", "assessment_id", help="Logs from a specific assessment"
)
@click.option(
    "--finding", "finding_id", help="Logs linked to a specific finding"
)
@click.pass_context
def logs_group(ctx, experiment_id, output_format, output, verdict, page, size, fetch_all, last_n, test_category, from_date, until_date, days, assessment_id, finding_id):
    """Get logs from an experiment, assessment, finding, or across a project.

    \b
    Scopes (from narrowest to broadest):
      hb logs <experiment-id>           # Single experiment
      hb logs --assessment <id>         # All logs from an assessment
      hb logs --finding <id>            # Logs linked to a finding
      hb logs --last 5                  # Project: last N experiments
      hb logs --days 7                  # Project: last N days
      hb logs                           # Latest experiment

    \b
    Examples:
      hb logs abc123                             # Specific experiment
      hb logs abc123 --result fail               # Only failed
      hb logs --assessment def456                # Assessment logs
      hb logs --finding ghi789                   # Finding evidence
      hb logs --last 5 --format json -o logs.json
      hb logs --days 7 --category adversarial
    """
    if ctx.invoked_subcommand is not None:
        return

    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.project_id:
        console_err.print("[yellow]No project selected.[/yellow]")
        console_err.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    # Validation
    scope_flags = any([last_n, test_category, from_date, until_date, days])
    exclusive_count = sum(bool(x) for x in [experiment_id, assessment_id, finding_id, scope_flags])
    if exclusive_count > 1:
        console_err.print("[red]Use only one scope: experiment ID, --assessment, --finding, or project flags (--last, --from, etc.).[/red]")
        raise SystemExit(1)
    if days and from_date:
        console_err.print("[red]Cannot combine --days with --from.[/red]")
        raise SystemExit(1)

    # --days → --from
    if days:
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")

    try:
        # Assessment or finding scope → use consolidated endpoint with headers
        if assessment_id or finding_id:
            result_filter = verdict if verdict != "all" else None
            if assessment_id:
                endpoint = f"assessments/{assessment_id}/logs"
                if result_filter:
                    endpoint = f"assessments/{assessment_id}/logs/{result_filter}"
            else:
                endpoint = f"findings/{finding_id}/logs"
                if result_filter:
                    endpoint = f"findings/{finding_id}/logs/{result_filter}"

            params = {"page": page, "size": size}
            response = client.get(endpoint, params=params)
            logs = response.get("data", response) if isinstance(response, dict) else response

            if output_format == "json":
                import json as _json
                json_str = _json.dumps(response, indent=2, default=str)
                if output:
                    Path(output).write_text(json_str)
                    console_err.print(f"[green]JSON exported to:[/green] {output}")
                else:
                    print(json_str)
            else:
                _show_logs_table(logs if isinstance(logs, list) else [], verdict)
            return

        if scope_flags:
            _project_level_logs(
                client, output_format, output, verdict, page, size, fetch_all,
                last_n, test_category, from_date, until_date,
            )
        elif experiment_id:
            # Resolve partial experiment ID
            experiment_id = _resolve_experiment_id(client, experiment_id)

            if output_format == "html":
                _export_html(client, experiment_id, output)
            elif output_format == "json":
                _export_json(client, experiment_id, output, verdict, fetch_all, page, size)
            else:
                _show_table(client, experiment_id, verdict, page, size)
        else:
            # No args → most recent experiment (existing behavior)
            response = client.list_experiments(page=1, size=1)
            exps = response.get("data", [])
            if not exps:
                console_err.print("[yellow]No experiments found.[/yellow]")
                raise SystemExit(1)
            experiment_id = exps[0].get("id")
            console_err.print(f"[dim]Using most recent experiment: {experiment_id}[/dim]")

            if output_format == "html":
                _export_html(client, experiment_id, output)
            elif output_format == "json":
                _export_json(client, experiment_id, output, verdict, fetch_all, page, size)
            else:
                _show_table(client, experiment_id, verdict, page, size)

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Project-level logs
# ---------------------------------------------------------------------------

def _build_experiment_lookup(client):
    """Fetch all experiments and build {id: {name, test_category}} lookup."""
    lookup = {}
    current_page = 1
    while True:
        response = client.list_experiments(page=current_page, size=100)
        for exp in response.get("data", []):
            lookup[exp.get("id")] = {
                "name": exp.get("name", ""),
                "test_category": exp.get("test_category", ""),
            }
        if not response.get("has_next_page"):
            break
        current_page += 1
    return lookup


def _enrich_log(log, exp_lookup):
    """Add experiment_name and test_category to a log entry from lookup."""
    exp_id = log.get("experiment_id", "")
    info = exp_lookup.get(exp_id, {})
    log["experiment_name"] = info.get("name", "")
    log["test_category"] = info.get("test_category", "")
    return log


def _project_level_logs(client, output_format, output, verdict, page, size, fetch_all,
                        last_n, test_category, from_date, until_date):
    """Fetch and display project-level logs with scope filters."""
    result_filter = None if verdict == "all" else verdict

    # Build experiment lookup for enriching logs
    exp_lookup = _build_experiment_lookup(client)

    if output_format == "html":
        _project_export_html(client, output, result_filter, last_n, test_category, from_date, until_date, exp_lookup)
    elif output_format == "json":
        _project_export_json(client, output, result_filter, fetch_all, page, size, last_n, test_category, from_date, until_date, exp_lookup)
    else:
        _project_show_table(client, result_filter, page, size, last_n, test_category, from_date, until_date, exp_lookup)


def _project_show_table(client, result_filter, page, size, last_n, test_category, from_date, until_date, exp_lookup):
    """Show project-level logs in table format."""
    response = client.get_project_logs(
        page=page, size=size, result=result_filter,
        from_date=from_date, until_date=until_date,
        test_category=test_category, last=last_n,
    )
    logs = response.get("data", [])

    if not logs:
        console.print("[yellow]No logs found.[/yellow]")
        return

    table = Table(title=f"Project Logs (page {page})")
    table.add_column("Experiment", width=20)
    table.add_column("Test Category", width=20)
    table.add_column("Verdict", width=6)
    table.add_column("Severity", width=8)
    table.add_column("Category", width=15)
    table.add_column("Prompt", max_width=40)

    for log in logs:
        _enrich_log(log, exp_lookup)

        result_val = log.get("result", "")
        result_style = "[green]pass[/green]" if result_val == "pass" else "[red]fail[/red]"

        severity = log.get("severity", "")
        severity_style = {
            "critical": "[red bold]critical[/red bold]",
            "high": "[red]high[/red]",
            "medium": "[yellow]medium[/yellow]",
            "low": "[blue]low[/blue]",
        }.get(str(severity).lower(), str(severity))

        # Shorten test_category for display
        tc = log.get("test_category", "")
        tc_short = tc.split("/")[-1] if "/" in tc else tc

        table.add_row(
            (log.get("experiment_name", "") or "")[:20],
            tc_short[:20],
            result_style,
            severity_style if result_val == "fail" else "",
            log.get("fail_category") or log.get("gen_category") or "",
            (log.get("prompt", "") or "")[:40],
        )

    console.print(table)

    if response.get("has_next_page"):
        console.print(f"\n[dim]Showing {len(logs)} logs. Use --page to see more.[/dim]")


def _project_export_json(client, output, result_filter, fetch_all, page, size, last_n, test_category, from_date, until_date, exp_lookup):
    """Export project-level logs as JSON."""
    all_logs = []

    if fetch_all:
        current_page = 1
        while True:
            response = client.get_project_logs(
                page=current_page, size=100, result=result_filter,
                from_date=from_date, until_date=until_date,
                test_category=test_category, last=last_n,
            )
            logs = response.get("data", [])
            all_logs.extend(logs)
            if not response.get("has_next_page"):
                break
            current_page += 1
    else:
        response = client.get_project_logs(
            page=page, size=size, result=result_filter,
            from_date=from_date, until_date=until_date,
            test_category=test_category, last=last_n,
        )
        all_logs = response.get("data", [])

    # Enrich each log with experiment name and test_category
    for log in all_logs:
        _enrich_log(log, exp_lookup)

    export_data = {
        "project_id": client.project_id,
        "filters": {
            "last": last_n,
            "test_category": test_category,
            "from": from_date,
            "until": until_date,
            "result": result_filter,
        },
        "logs": all_logs,
        "total_logs": len(all_logs),
    }

    json_output = json.dumps(export_data, indent=2, default=str)

    if output:
        Path(output).write_text(json_output)
        console.print(f"[green]JSON exported to:[/green] {output}")
    else:
        print(json_output)


def _project_export_html(client, output, result_filter, last_n, test_category, from_date, until_date, exp_lookup):
    """Export project-level logs as HTML report."""
    with console.status("Generating HTML report...", spinner="dots"):
        # Fetch all matching logs
        all_logs = []
        current_page = 1
        while True:
            response = client.get_project_logs(
                page=current_page, size=100, result=result_filter,
                from_date=from_date, until_date=until_date,
                test_category=test_category, last=last_n,
            )
            all_logs.extend(response.get("data", []))
            if not response.get("has_next_page"):
                break
            current_page += 1

        # Enrich each log with experiment name and test_category
        for log in all_logs:
            _enrich_log(log, exp_lookup)

        # Build pseudo-experiment for the report template
        pseudo_experiment = {
            "id": f"project-{client.project_id[:8]}",
            "name": "Project Logs",
            "test_category": test_category or "Project-wide",
            "testing_level": "",
            "status": "completed",
            "results": {},
            "created_at": from_date or "",
        }

        from ..report import generate_html_report
        report_html = generate_html_report(pseudo_experiment, all_logs)

    filename = output or f"project_{client.project_id[:8]}_logs.html"
    Path(filename).write_text(report_html)
    console.print(f"[green]HTML report exported to:[/green] {filename}")


# ---------------------------------------------------------------------------
# Experiment-level helpers (unchanged)
# ---------------------------------------------------------------------------

def _resolve_experiment_id(client: HumanboundClient, partial_id: str) -> str:
    """Resolve a partial experiment ID to full ID."""
    if len(partial_id) >= 32:
        return partial_id

    # Search recent experiments for match
    response = client.list_experiments(page=1, size=50)
    for exp in response.get("data", []):
        if exp.get("id", "").startswith(partial_id):
            return exp.get("id")

    # Not found, return as-is and let API handle error
    return partial_id


def _show_logs_table(logs: list, verdict: str = "all"):
    """Show a list of logs in table format (for assessment/finding scoped queries)."""
    if not logs:
        console.print("[yellow]No logs found.[/yellow]")
        return

    if verdict != "all":
        logs = [l for l in logs if l.get("result") == verdict]

    table = Table(title=f"Logs ({len(logs)})")
    table.add_column("Verdict", width=6)
    table.add_column("Severity", width=8)
    table.add_column("Category", width=20)
    table.add_column("Explanation", max_width=50)

    for log in logs:
        result_val = log.get("result", "")
        result_style = "[green]pass[/green]" if result_val == "pass" else "[red]fail[/red]"
        cat = log.get("fail_category") or log.get("gen_category") or ""
        explanation = (log.get("explanation") or "")[:50]

        table.add_row(
            result_style,
            str(log.get("severity", "")),
            cat,
            explanation,
        )

    console.print(table)


def _show_table(client: HumanboundClient, experiment_id: str, verdict: str, page: int, size: int):
    """Show logs in table format."""
    result_filter = None if verdict == "all" else verdict

    response = client.get_experiment_logs(
        experiment_id,
        page=page,
        size=size,
        result=result_filter,
    )
    logs = response.get("data", [])

    if not logs:
        console.print("[yellow]No logs found.[/yellow]")
        return

    table = Table(title=f"Experiment Logs (page {page})")
    table.add_column("ID", style="dim")
    table.add_column("Verdict", width=6)
    table.add_column("Severity", width=8)
    table.add_column("Category", width=15)
    table.add_column("Prompt", max_width=50)

    for log in logs:
        result_val = log.get("result", "")
        result_style = "[green]pass[/green]" if result_val == "pass" else "[red]fail[/red]"

        severity = log.get("severity", "")
        severity_style = {
            "critical": "[red bold]critical[/red bold]",
            "high": "[red]high[/red]",
            "medium": "[yellow]medium[/yellow]",
            "low": "[blue]low[/blue]",
        }.get(str(severity).lower(), str(severity))

        table.add_row(
            log.get("id", ""),
            result_style,
            severity_style if result_val == "fail" else "",
            log.get("fail_category") or log.get("gen_category") or "",
            (log.get("prompt", "") or "")[:50],
        )

    console.print(table)

    total = response.get("total", 0)
    if response.get("has_next_page"):
        console.print(f"\n[dim]Showing {len(logs)} of {total}. Use --page to see more.[/dim]")


def _export_json(client: HumanboundClient, experiment_id: str, output: str, verdict: str, fetch_all: bool, page: int, size: int):
    """Export logs as JSON."""
    result_filter = None if verdict == "all" else verdict

    all_logs = []

    if fetch_all:
        # Fetch all pages
        current_page = 1
        while True:
            response = client.get_experiment_logs(
                experiment_id,
                page=current_page,
                size=100,
                result=result_filter,
            )
            logs = response.get("data", [])
            all_logs.extend(logs)

            if not response.get("has_next_page"):
                break
            current_page += 1
    else:
        response = client.get_experiment_logs(
            experiment_id,
            page=page,
            size=size,
            result=result_filter,
        )
        all_logs = response.get("data", [])

    # Get experiment info for context
    experiment = client.get_experiment(experiment_id)

    export_data = {
        "experiment": {
            "id": experiment.get("id"),
            "name": experiment.get("name"),
            "status": experiment.get("status"),
            "test_category": experiment.get("test_category"),
            "testing_level": experiment.get("testing_level"),
            "created_at": experiment.get("created_at"),
        },
        "results": experiment.get("results", {}),
        "logs": all_logs,
        "total_logs": len(all_logs),
    }

    json_output = json.dumps(export_data, indent=2, default=str)

    if output:
        Path(output).write_text(json_output)
        console.print(f"[green]JSON exported to:[/green] {output}")
    else:
        print(json_output)


def _export_html(client: HumanboundClient, experiment_id: str, output: str):
    """Export logs as HTML report."""
    with console.status("Generating HTML report...", spinner="dots"):
        experiment = client.get_experiment(experiment_id)

        # Fetch all logs
        all_logs = []
        page = 1
        while True:
            resp = client.get_experiment_logs(experiment_id, page=page, size=100)
            all_logs.extend(resp.get("data", []))
            if not resp.get("has_next_page"):
                break
            page += 1

        from ..report import generate_html_report
        report_html = generate_html_report(experiment, all_logs)

    filename = output or f"experiment_{experiment_id[:8]}_report.html"
    Path(filename).write_text(report_html)
    console.print(f"[green]HTML report exported to:[/green] {filename}")


# ---------------------------------------------------------------------------
# Upload subcommand
# ---------------------------------------------------------------------------

@logs_group.command("upload")
@click.argument("file", type=click.Path(exists=True))
@click.option("--tag", help="Tag for the dataset (used to reference in test runs)")
@click.option("--lang", help="Language of the conversations (e.g., english)")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def upload_command(file: str, tag: str, lang: str, force: bool):
    """Upload conversation logs for evaluation.

    FILE: Path to a JSON file containing conversations.

    \b
    Expected file format:
      [
        {
          "conversation": [
            {"u": "user message", "a": "bot response"},
            {"u": "follow up", "a": "bot reply"}
          ],
          "thread_id": "optional-id"
        },
        ...
      ]

    \b
    Examples:
      hb logs upload conversations.json
      hb logs upload conversations.json --tag prod-v2
      hb logs upload conversations.json --lang english
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = client.project_id
    if not project_id:
        console_err.print("[yellow]No project selected.[/yellow]")
        console_err.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    # Read and parse file
    file_path = Path(file)
    try:
        content = file_path.read_text()
        conversations = json.loads(content)
    except json.JSONDecodeError as e:
        console_err.print(f"[red]Invalid JSON file:[/red] {e}")
        raise SystemExit(1)

    if not isinstance(conversations, list):
        console_err.print("[red]File must contain a JSON array of conversations.[/red]")
        raise SystemExit(1)

    if not conversations:
        console_err.print("[yellow]File contains no conversations.[/yellow]")
        raise SystemExit(1)

    # Show summary
    console.print(f"  File: [bold]{file_path.name}[/bold]")
    console.print(f"  Conversations: [bold]{len(conversations)}[/bold]")
    if tag:
        console.print(f"  Tag: [bold]{tag}[/bold]")
    if lang:
        console.print(f"  Language: [bold]{lang}[/bold]")

    if not force:
        from rich.prompt import Confirm
        if not Confirm.ask(f"\nUpload {len(conversations)} conversations?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    try:
        with console.status(f"Uploading {len(conversations)} conversations..."):
            response = client.upload_conversations(project_id, conversations, tag=tag, lang=lang)

        console.print(f"\n[green]Upload complete.[/green]")

        dataset_id = response.get("dataset_id", response.get("id", ""))
        if dataset_id:
            console.print(f"  Dataset ID: [bold]{dataset_id}[/bold]")

        test_category_val = response.get("test_category", "")
        if test_category_val:
            console.print(f"  Test category: [bold]{test_category_val}[/bold]")
            console.print(f"\n[dim]Run evaluation with: hb test --category \"{test_category_val}\"[/dim]")

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
