# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Experiment commands."""

import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

console = Console()


@click.group("experiments", invoke_without_command=True)
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
@click.pass_context
def experiments_group(ctx, page: int, size: int):
    """Experiment management commands. Run without subcommand to list experiments."""
    if ctx.invoked_subcommand is not None:
        return
    _list_experiments(page, size)


@experiments_group.command("list")
@click.option("--page", default=1, help="Page number")
@click.option("--size", default=20, help="Items per page")
def list_experiments_cmd(page: int, size: int):
    """List experiments in the current project."""
    _list_experiments(page, size)


def _list_experiments(page: int, size: int):
    """List experiments in the current project."""
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        response = client.list_experiments(page=page, size=size)
        experiments = response.get("data", [])

        if not experiments:
            console.print("[yellow]No experiments found.[/yellow]")
            return

        table = Table(title="Experiments")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Status")
        table.add_column("Test Category")
        table.add_column("Created")

        for exp in experiments:
            status = exp.get("status", "Unknown")
            status_style = {
                "Finished": "[green]Finished[/green]",
                "Running": "[yellow]Running[/yellow]",
                "Failed": "[red]Failed[/red]",
                "Generating": "[cyan]Generating[/cyan]",
                "Generated": "[blue]Generated[/blue]",
            }.get(status, status)

            table.add_row(
                exp.get("id", ""),
                exp.get("name", "Unknown"),
                status_style,
                exp.get("test_category", "").split("/")[-1],
                exp.get("created_at", "")[:10],
            )

        console.print(table)

        if response.get("has_next_page"):
            console.print(f"\n[dim]Page {page} of more. Use --page to navigate.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@experiments_group.command("show")
@click.argument("experiment_id")
def show_experiment(experiment_id: str):
    """Show experiment details.

    EXPERIMENT_ID: Experiment UUID.
    """
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        raise SystemExit(1)

    try:
        exp = client.get_experiment(experiment_id)

        status = exp.get("status", "Unknown")
        status_color = {
            "Finished": "green",
            "Running": "yellow",
            "Failed": "red",
        }.get(status, "white")

        console.print(
            Panel(
                f"[bold]{exp.get('name')}[/bold]\n"
                f"[dim]ID: {exp.get('id')}[/dim]\n\n"
                f"Status: [{status_color}]{status}[/{status_color}]\n"
                f"Test Category: {exp.get('test_category')}\n"
                f"Language: {exp.get('lang', 'en')}\n"
                f"Testing Level: {exp.get('testing_level', 'unit')}",
                title="Experiment Details",
            )
        )

        results = exp.get("results", {})
        if results and results.get("insights"):
            insights = results.get("insights", [])
            error_insights = [i for i in insights if i.get("result") == "error"]

            if status == "Failed" and error_insights:
                console.print("\n[bold red]Failure Details:[/bold red]")
                for insight in error_insights:
                    console.print(f"  {insight.get('explanation', 'Unknown error')}")
            else:
                console.print("\n[bold]Results:[/bold]")
                stats = results.get("stats", {})
                if stats:
                    console.print(f"  Total logs: {stats.get('total', 0)}")
                    console.print(f"  Pass: {stats.get('pass', 0)}")
                    console.print(f"  Fail: {stats.get('fail', 0)}")

                if insights:
                    console.print(f"\n  Insights: {len(insights)} findings")
                    for i, insight in enumerate(insights[:3], 1):
                        console.print(f"    {i}. {insight.get('explanation', '')[:80]}...")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@experiments_group.command("status")
@click.argument("experiment_id", required=False)
@click.option("--watch", "-w", is_flag=True, help="Watch status until completion")
@click.option("--interval", default=10, help="Polling interval in seconds (with --watch)")
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show status of all project experiments (polls every 60s)",
)
def experiment_status(experiment_id: str, watch: bool, interval: int, show_all: bool):
    """Check experiment status.

    EXPERIMENT_ID: Experiment UUID (optional with --all).

    \b
    Examples:
      hb experiments status <id>           # One-shot status
      hb experiments status <id> --watch   # Poll single experiment
      hb experiments status --all          # Dashboard of all experiments (polls 60s)
    """
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        raise SystemExit(1)

    if show_all:
        _poll_all_experiments(client)
        return

    if not experiment_id:
        console.print("[red]Provide an experiment ID or use --all.[/red]")
        raise SystemExit(1)

    try:
        if not watch:
            status = client.get_experiment_status(experiment_id)
            _print_status(status)
            if status.get("status") == "Failed":
                _show_failure_details(client, experiment_id)
            return

        # Watch mode
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Watching experiment...", total=None)

            while True:
                status = client.get_experiment_status(experiment_id)
                current_status = status.get("status", "Unknown")

                progress.update(task, description=f"Status: {current_status}")

                if current_status in TERMINAL_STATUSES:
                    break

                time.sleep(interval)

        _print_status(status)

        if current_status == "Finished":
            console.print("\n[green]Experiment completed successfully![/green]")
        else:
            console.print(f"\n[red]Experiment ended with status: {current_status}[/red]")
            _show_failure_details(client, experiment_id)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching.[/yellow]")


ACTIVE_STATUSES = ["Running", "Generating", "Generated", "Pending"]


def _poll_all_experiments(client: HumanboundClient):
    """Poll all project experiments every 60s until none are active."""
    try:
        cycle = 0
        while True:
            # Fetch all experiments (up to 200)
            all_exps = []
            page = 1
            while True:
                response = client.list_experiments(page=page, size=100)
                all_exps.extend(response.get("data", []))
                if not response.get("has_next_page"):
                    break
                page += 1

            if not all_exps:
                console.print("[yellow]No experiments found.[/yellow]")
                return

            active = [e for e in all_exps if e.get("status") in ACTIVE_STATUSES]
            finished = [e for e in all_exps if e.get("status") == "Finished"]
            failed = [e for e in all_exps if e.get("status") == "Failed"]

            # Clear screen on subsequent cycles
            if cycle > 0:
                console.clear()

            timestamp = time.strftime("%H:%M:%S")
            console.print(f"[bold]Project Experiments[/bold]  [dim]{timestamp}[/dim]\n")
            console.print(
                f"  Total: {len(all_exps)}  "
                f"[green]Finished: {len(finished)}[/green]  "
                f"[yellow]Active: {len(active)}[/yellow]  "
                f"[red]Failed: {len(failed)}[/red]\n"
            )

            table = Table()
            table.add_column("Name", style="bold", max_width=35)
            table.add_column("Status", width=12)
            table.add_column("Category", width=20)
            table.add_column("ID", style="dim")

            for exp in all_exps:
                status = exp.get("status", "Unknown")
                status_style = {
                    "Finished": "[green]Finished[/green]",
                    "Running": "[yellow]Running[/yellow]",
                    "Failed": "[red]Failed[/red]",
                    "Generating": "[cyan]Generating[/cyan]",
                    "Generated": "[blue]Generated[/blue]",
                    "Pending": "[dim]Pending[/dim]",
                    "Terminated": "[red]Terminated[/red]",
                }.get(status, status)

                cat = exp.get("test_category", "")
                if "/" in cat:
                    cat = cat.split("/")[-1]

                table.add_row(
                    exp.get("name", ""),
                    status_style,
                    cat,
                    exp.get("id", ""),
                )

            console.print(table)

            if not active:
                console.print("\n[green]All experiments completed.[/green]")
                return

            console.print(f"\n[dim]{len(active)} active — polling every 60s (Ctrl+C to stop)[/dim]")
            time.sleep(60)
            cycle += 1

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped polling.[/yellow]")


def _print_status(status: dict):
    """Print experiment status."""
    current_status = status.get("status", "Unknown")
    status_color = {
        "Finished": "green",
        "Running": "yellow",
        "Failed": "red",
        "Generating": "cyan",
        "Generated": "blue",
    }.get(current_status, "white")

    console.print(f"Status: [{status_color}]{current_status}[/{status_color}]")


TERMINAL_STATUSES = ["Finished", "Failed"]


def _show_failure_details(client: HumanboundClient, experiment_id: str):
    """Fetch and display failure details for a failed experiment."""
    try:
        exp = client.get_experiment(experiment_id)
        results = exp.get("results", {})
        insights = results.get("insights", [])
        error_insights = [i for i in insights if i.get("result") == "error"]

        if error_insights:
            console.print("\n[bold red]Failure Details:[/bold red]")
            for insight in error_insights:
                console.print(f"  {insight.get('explanation', 'Unknown error')}")
        elif insights:
            console.print("\n[bold red]Failure Details:[/bold red]")
            for insight in insights[:3]:
                explanation = insight.get("explanation", "")
                if explanation:
                    console.print(f"  {explanation}")
    except Exception:
        pass  # Don't fail the status display if we can't fetch details


@experiments_group.command("wait")
@click.argument("experiment_id")
@click.option("--timeout", default=120, help="Max wait time in minutes (default: 120)")
def experiment_wait(experiment_id: str, timeout: int):
    """Wait for an experiment to complete.

    Polls experiment status with progressive backoff:
    starts at every 30s, increases to every 5 minutes.

    Returns exit code 0 on Finished, 1 on Failed.

    EXPERIMENT_ID: Experiment UUID.
    """
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        raise SystemExit(1)

    try:
        start_time = time.time()
        timeout_seconds = timeout * 60
        poll_interval = 30  # start at 30s
        max_interval = 300  # cap at 5 minutes

        console.print(f"Waiting for experiment {experiment_id} (timeout: {timeout}m)\n")

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                console.print(f"\n[red]Timeout after {timeout} minutes.[/red]")
                raise SystemExit(1)

            status_response = client.get_experiment_status(experiment_id)
            current_status = status_response.get("status", "Unknown")

            minutes_elapsed = int(elapsed / 60)
            seconds_elapsed = int(elapsed % 60)
            console.print(
                f"  [{minutes_elapsed:02d}:{seconds_elapsed:02d}] Status: {current_status}"
                f"  (next check in {poll_interval}s)"
            )

            if current_status in TERMINAL_STATUSES:
                console.print()
                _print_status(status_response)

                if current_status == "Finished":
                    console.print("[green]Experiment completed successfully![/green]")
                    return
                else:
                    console.print(f"[red]Experiment ended: {current_status}[/red]")
                    _show_failure_details(client, experiment_id)
                    raise SystemExit(1)

            time.sleep(poll_interval)

            # Progressive backoff: 30s -> 60s -> 120s -> 300s
            poll_interval = min(poll_interval * 2, max_interval)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped waiting. Experiment continues in background.[/yellow]")
        console.print(f"Resume with: hb experiments wait {experiment_id}")
        raise SystemExit(0)


@experiments_group.command("terminate")
@click.argument("experiment_id")
def terminate_experiment(experiment_id: str):
    """Terminate a running experiment.

    EXPERIMENT_ID: Experiment UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        experiment_id = _resolve_experiment_id(client, experiment_id)

        # Verify experiment is running
        exp = client.get_experiment(experiment_id)
        status = exp.get("status", "")
        if status in TERMINAL_STATUSES:
            console.print(f"[yellow]Experiment is already {status}.[/yellow]")
            return

        with console.status("Terminating experiment..."):
            client.terminate_experiment(experiment_id)

        console.print("[green]Experiment terminated.[/green]")
        console.print(f"[dim]ID: {experiment_id}[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@experiments_group.command("delete")
@click.argument("experiment_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete_experiment(experiment_id: str, force: bool):
    """Delete an experiment.

    EXPERIMENT_ID: Experiment UUID (or partial ID).
    """
    client = HumanboundClient()

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        experiment_id = _resolve_experiment_id(client, experiment_id)

        exp = client.get_experiment(experiment_id)
        exp_name = exp.get("name", experiment_id)

        if not force:
            if not Confirm.ask(f"Delete experiment [bold]{exp_name}[/bold]? This cannot be undone"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Deleting experiment..."):
            client.delete_experiment(experiment_id)

        console.print("[green]Experiment deleted.[/green]")
        console.print(f"[dim]{exp_name} ({experiment_id})[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _resolve_experiment_id(client: HumanboundClient, partial_id: str) -> str:
    """Resolve a partial experiment ID to full ID."""
    if len(partial_id) >= 32:
        return partial_id

    response = client.list_experiments(page=1, size=50)
    for exp in response.get("data", []):
        if exp.get("id", "").startswith(partial_id):
            return exp.get("id")

    return partial_id


@experiments_group.command("report")
@click.argument("experiment_id")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--no-open", is_flag=True, help="Save without opening browser")
def experiment_report(experiment_id: str, output: str, no_open: bool):
    """Generate report for a specific experiment.

    Includes methodology context, metrics, vulnerabilities, and test logs.

    \b
    Examples:
      hb experiments report abc123
      hb experiments report abc123 -o report.html
    """
    from ._report_helper import download_and_open

    client = HumanboundClient()
    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow] Run 'hb projects use <id>'")
        raise SystemExit(1)

    eid = _resolve_experiment_id(client, experiment_id)
    download_and_open(
        client,
        f"experiments/{eid}/report",
        f"experiment-{eid[:8]}-report.html",
        output=output,
        no_open=no_open,
        include_project=True,
    )
