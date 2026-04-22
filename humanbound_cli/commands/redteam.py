# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Collaborative red team command — interactive human-AI adversarial testing."""

import click
import requests as requests_lib
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

console = Console()
console_err = Console(stderr=True)

COLLABORATIVE_TEST_CATEGORY = "humanbound/adversarial/collaborative_red_team"


def _require_auth_and_project():
    """Return an authenticated client with a project selected."""
    client = HumanboundClient()
    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    if not client.project_id:
        console_err.print("[yellow]No project selected.[/yellow]")
        console_err.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)
    return client


@click.group("redteam", invoke_without_command=True)
@click.option("--experiment", "-e", "experiment_id", help="Existing experiment ID to resume")
@click.option("--name", "-n", help="Name for new experiment (default: auto-generated)")
@click.option("--endpoint", help="Agent integration config — JSON string or path to JSON file")
@click.pass_context
def redteam_group(ctx, experiment_id, name, endpoint):
    """Interactive collaborative red team testing.

    Start a new session or resume an existing one. The platform analyzes
    your agent's security state, you co-plan attack strategies, and the
    platform executes them while you direct pivots.

    \b
    Examples:
      hb redteam                              # New experiment, interactive
      hb redteam -e abc123                    # Resume existing experiment
      hb redteam --name "Auth bypass test"    # Named experiment
      hb redteam analyze -e abc123            # Analyze only
    """
    if ctx.invoked_subcommand is not None:
        ctx.ensure_object(dict)
        ctx.obj["experiment_id"] = experiment_id
        return

    # Interactive mode — full session loop
    client = _require_auth_and_project()

    try:
        # Create or resume experiment
        if experiment_id:
            exp = client.get_experiment(experiment_id)
            console.print(f"\n[bold]Resuming:[/bold] {exp.get('name', experiment_id)}")
        else:
            import time

            exp_name = name or f"redteam-{time.strftime('%Y%m%d-%H%M%S')}"
            configuration = {"scope": _get_project_scope(client)}

            if endpoint:
                from .test import _load_integration

                configuration["integration"] = _load_integration(endpoint)

            # Resolve provider (same as hb test)
            providers = client.list_providers()
            if not providers:
                console_err.print("[red]No providers configured.[/red]")
                console_err.print("Use 'hb providers add' to configure a model provider first.")
                raise SystemExit(1)
            provider = next((p for p in providers if p.get("is_default")), providers[0])
            provider_id = provider.get("id")

            try:
                exp = client.post(
                    "experiments",
                    data={
                        "name": exp_name,
                        "description": "Collaborative red team session",
                        "test_category": COLLABORATIVE_TEST_CATEGORY,
                        "testing_level": "unit",
                        "configuration": configuration,
                        "auto_start": False,
                        "provider_id": provider_id,
                    },
                    include_project=True,
                )

                experiment_id = exp.get("id")
                console.print(f"\n[green]Experiment created:[/green] {experiment_id}")

            except APIError as e:
                if "409" in str(e.status_code if hasattr(e, "status_code") else e):
                    # Find the active experiment and offer to resume
                    response = client.list_experiments(page=1, size=50)
                    active = next(
                        (
                            x
                            for x in response.get("data", [])
                            if "collaborative_red_team" in x.get("test_category", "")
                            and x.get("status") in ("Running", "Dataset Generated", "Created")
                        ),
                        None,
                    )
                    if active:
                        console.print(
                            f"\n[yellow]Active session found:[/yellow] {active.get('name')} ({active.get('id')})"
                        )
                        if Confirm.ask("Resume this session?", default=True):
                            experiment_id = active.get("id")
                        else:
                            return
                    else:
                        raise
                else:
                    raise

        # Run interactive loop
        _interactive_loop(client, experiment_id)

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Session paused.[/yellow]")
        if experiment_id:
            console.print(f"Resume with: hb redteam -e {experiment_id}")


@redteam_group.command("analyze")
@click.option("--experiment", "-e", "experiment_id", required=True, help="Experiment ID")
def analyze_command(experiment_id):
    """Analyze the project's attack surface."""
    client = _require_auth_and_project()

    with console.status("Analyzing attack surface..."):
        analysis = client.post(
            f"experiments/{experiment_id}/actions/analyze",
            data={},
            include_project=True,
            timeout=120,
        )

    _display_analysis(analysis)


@redteam_group.command("sessions")
@click.option("--experiment", "-e", "experiment_id", required=True, help="Experiment ID")
def sessions_command(experiment_id):
    """List active sessions in the experiment."""
    client = _require_auth_and_project()

    exp = client.get_experiment(experiment_id)
    state = exp.get("orchestrator_state", {})
    sessions = state.get("active_sessions", {})

    if not sessions:
        console.print("[yellow]No active sessions.[/yellow]")
        return

    table = Table(title="Active Sessions")
    table.add_column("Session ID", style="dim")
    table.add_column("User")
    table.add_column("Status")
    table.add_column("Turns")
    table.add_column("Strategy Goal", max_width=40)

    for sid, s in sessions.items():
        table.add_row(
            sid,
            s.get("user_id", ""),
            s.get("status", ""),
            str(s.get("turn_count", 0)),
            s.get("strategy", {}).get("goal", "")[:40],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def _interactive_loop(client, experiment_id):
    """Run the interactive red team session.

    Guided flow — the REPL suggests the natural next step and auto-chains
    start→execute so the user doesn't have to type two commands.
    """

    active_session = None

    # Step 1: Always start with analysis
    console.print()
    with console.status("Analyzing attack surface..."):
        try:
            analysis = client.post(
                f"experiments/{experiment_id}/actions/analyze",
                data={},
                include_project=True,
                timeout=120,
            )
            _display_analysis(analysis)
        except APIError as e:
            console_err.print(f"[red]Analysis failed:[/red] {e}")

    # Main loop
    while True:
        try:
            # Show context-aware prompt with shortcut hints
            if not active_session:
                console.print(
                    "\n[dim]Commands:[/dim] "
                    "[cyan]\\[a]ttack[/cyan]  "
                    "[cyan]\\[c]omplete[/cyan]  "
                    "[cyan]\\[q]uit[/cyan]"
                )
                cmd = Prompt.ask("[bold]redteam[/bold]", default="attack").strip().lower()
            else:
                console.print(
                    "\n[dim]Commands:[/dim] "
                    "[cyan]\\[g]o[/cyan] [dim](more turns)[/dim]  "
                    "[cyan]\\[p]ivot[/cyan]  "
                    "[cyan]\\[j]udge[/cyan]  "
                    "[cyan]\\[a]ttack[/cyan] [dim](new)[/dim]  "
                    "[cyan]\\[q]uit[/cyan]"
                )
                cmd = Prompt.ask("[bold]redteam[/bold]", default="go").strip().lower()

            # Normalize aliases — single letter shortcuts
            ALIASES = {
                "q": "quit",
                "exit": "quit",
                "a": "attack",
                "attack": "attack",
                "start": "attack",
                "new": "attack",
                "g": "go",
                "go": "go",
                "run": "go",
                "execute": "go",
                "e": "go",
                "p": "pivot",
                "pivot": "pivot",
                "direct": "pivot",
                "d": "pivot",
                "j": "judge",
                "judge": "judge",
                "eval": "judge",
                "c": "complete",
                "complete": "complete",
                "finish": "complete",
                "done": "complete",
                "analyze": "analyze",
                "analyse": "analyze",
                "analysis": "analyze",
            }
            cmd = ALIASES.get(cmd, cmd)

            # --- QUIT ---
            if cmd == "quit":
                console.print("[yellow]Session paused.[/yellow]")
                console.print(f"Resume with: [bold]hb redteam -e {experiment_id}[/bold]")
                break

            # --- ANALYZE ---
            elif cmd == "analyze":
                with console.status("Analyzing..."):
                    analysis = client.post(
                        f"experiments/{experiment_id}/actions/analyze",
                        data={},
                        include_project=True,
                        timeout=120,
                    )
                _display_analysis(analysis)

            # --- ATTACK (start + auto-execute) ---
            elif cmd == "attack":
                if active_session:
                    if not Confirm.ask("You have an active session. Start a new one?"):
                        continue

                goal = Prompt.ask(
                    "[bold]Attack goal[/bold] [dim](Enter for platform suggestion)[/dim]",
                    default="",
                )
                data = {}
                if goal:
                    method = Prompt.ask("[dim]Method[/dim]", default="")
                    data["strategy"] = {"goal": goal, "method": method, "examples": []}

                with console.status("Starting attack session..."):
                    result = client.post(
                        f"experiments/{experiment_id}/actions/start",
                        data=data,
                        include_project=True,
                    )

                active_session = result.get("session_id")
                strategy_goal = result.get("strategy", {}).get("goal", "")
                console.print("\n[green]Session started[/green]")
                console.print(f"  Strategy: [bold]{strategy_goal}[/bold]")

                # Auto-execute first burst
                console.print()
                with console.status("Executing first attack burst..."):
                    checkpoint = client.post(
                        f"experiments/{experiment_id}/actions/execute",
                        data={"session_id": active_session, "burst_turns": 5},
                        include_project=True,
                        timeout=300,
                    )

                _display_checkpoint(checkpoint)

            # --- GO (execute more turns) ---
            elif cmd == "go":
                if not active_session:
                    console.print("[yellow]No active session. Use 'attack' to start one.[/yellow]")
                    continue

                with console.status("Executing turns..."):
                    checkpoint = client.post(
                        f"experiments/{experiment_id}/actions/execute",
                        data={"session_id": active_session, "burst_turns": 5},
                        include_project=True,
                        timeout=300,
                    )

                _display_checkpoint(checkpoint)

            # --- PIVOT (direct strategy change) ---
            elif cmd == "pivot":
                if not active_session:
                    console.print("[yellow]No active session.[/yellow]")
                    continue

                guidance = Prompt.ask("[bold]Your pivot strategy[/bold]")
                if not guidance:
                    continue

                with console.status("Processing pivot..."):
                    strategy = client.post(
                        f"experiments/{experiment_id}/actions/direct",
                        data={"session_id": active_session, "input": guidance},
                        include_project=True,
                        timeout=120,
                    )

                console.print("[green]Strategy pivoted:[/green]")
                console.print(f"  Goal: {strategy.get('goal', '')}")
                console.print(f"  Method: {strategy.get('method', '')}")

                # Auto-execute after pivot
                console.print()
                with console.status("Executing with new strategy..."):
                    checkpoint = client.post(
                        f"experiments/{experiment_id}/actions/execute",
                        data={"session_id": active_session, "burst_turns": 5},
                        include_project=True,
                        timeout=300,
                    )

                _display_checkpoint(checkpoint)

            # --- JUDGE ---
            elif cmd == "judge":
                if not active_session:
                    console.print("[yellow]No active session.[/yellow]")
                    continue

                with console.status("Judging session..."):
                    verdict = client.post(
                        f"experiments/{experiment_id}/actions/judge",
                        data={"session_id": active_session},
                        include_project=True,
                        timeout=60,
                    )

                _display_verdict(verdict)
                active_session = None

            # --- COMPLETE ---
            elif cmd == "complete":
                if not Confirm.ask("Finalize experiment and trigger posture calculation?"):
                    continue

                with console.status("Completing experiment..."):
                    result = client.post(
                        f"experiments/{experiment_id}/actions/complete",
                        data={},
                        include_project=True,
                    )

                console.print("[green]Experiment completed.[/green]")
                auto_judged = result.get("auto_judged_sessions", [])
                if auto_judged:
                    console.print(f"  Auto-judged {len(auto_judged)} remaining sessions.")
                break

            else:
                console.print(f"[dim]Unknown command: {cmd}[/dim]")

        except APIError as e:
            console_err.print(f"[red]Error:[/red] {e}")
        except (requests_lib.exceptions.Timeout, requests_lib.exceptions.ConnectionError):
            console_err.print(
                "[red]Connection error:[/red] Request timed out. The server may be busy — try again."
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Type 'quit' to pause or 'complete' to finalize.[/dim]")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _display_analysis(analysis):
    """Display attack surface analysis."""
    console.print("\n[bold]Attack Surface Analysis[/bold]\n")
    console.print(f"  {analysis.get('summary', 'No summary available.')}\n")

    weak = analysis.get("weak_spots", [])
    if weak:
        console.print("[bold]Weak Spots:[/bold]")
        for w in weak:
            sev = w.get("severity", "unknown").upper()
            sev_color = {
                "CRITICAL": "red bold",
                "HIGH": "red",
                "MEDIUM": "yellow",
                "LOW": "blue",
            }.get(sev, "white")
            console.print(
                f"  [{sev_color}]{sev}[/{sev_color}] {w.get('area', '')} — {w.get('reason', '')}"
            )

    gaps = analysis.get("coverage_gaps", [])
    if gaps:
        console.print("\n[bold]Coverage Gaps:[/bold]")
        for g in gaps:
            console.print(f"  {g.get('area', '')} — {g.get('reason', '')}")

    recs = analysis.get("recommended_strategies", [])
    if recs:
        console.print("\n[bold]Recommended Strategies:[/bold]")
        for i, r in enumerate(recs, 1):
            console.print(f"  {i}. [cyan]{r.get('goal', '')}[/cyan]")
            console.print(f"     {r.get('method', '')}")


def _display_checkpoint(checkpoint):
    """Display conversation snippet + checkpoint assessment."""
    # Show recent conversation turns
    conversation = checkpoint.get("conversation", [])
    total_turns = checkpoint.get("total_turns", len(conversation))

    if conversation:
        if total_turns > len(conversation):
            console.print(f"\n[dim]... ({total_turns - len(conversation)} earlier turns)[/dim]")

        for i, turn in enumerate(conversation):
            turn_num = total_turns - len(conversation) + i + 1
            # Attack message (truncated)
            msg = turn.get("u", "")
            if len(msg) > 150:
                msg = msg[:150] + "..."
            console.print(f"\n  [bold]Turn {turn_num}[/bold]")
            console.print(f"  [blue]Attack:[/blue] {msg}")

            # Bot response (truncated)
            resp = turn.get("a", "")
            if len(resp) > 200:
                resp = resp[:200] + "..."
            console.print(f"  [yellow]Bot:[/yellow]    {resp}")

    # Checkpoint panel
    trigger = checkpoint.get("trigger", "unknown")
    trigger_color = {
        "hard_refusal": "red",
        "partial_compliance": "yellow",
        "burst_complete": "blue",
        "max_session_turns": "orange3",
    }.get(trigger, "white")

    trigger_label = {
        "hard_refusal": "Hard Refusal",
        "partial_compliance": "Partial Compliance",
        "burst_complete": "Burst Complete",
        "max_session_turns": "Max Turns Reached",
    }.get(trigger, trigger)

    console.print(
        Panel(
            f"[{trigger_color}]{trigger_label}[/{trigger_color}] at turn {checkpoint.get('turn', '?')}\n\n"
            f"{checkpoint.get('summary', 'No summary.')}",
            title="Checkpoint",
            border_style=trigger_color,
        )
    )

    pivots = checkpoint.get("suggested_pivots", [])
    if pivots:
        console.print("[bold]Suggested pivots:[/bold]")
        for p in pivots:
            console.print(f"  [cyan]{p}[/cyan]")


def _display_verdict(verdict):
    """Display session verdict."""
    result = verdict.get("result", "error")
    result_color = "green" if result == "pass" else "red" if result == "fail" else "yellow"

    console.print(
        Panel(
            f"[bold]Result:[/bold] [{result_color}]{result.upper()}[/{result_color}]\n"
            f"[bold]Turns:[/bold] {verdict.get('turns', 0)}\n"
            f"[bold]Severity:[/bold] {verdict.get('severity', 0)}\n"
            f"[bold]Category:[/bold] {verdict.get('category', 'N/A')}\n\n"
            f"{verdict.get('explanation', '')}",
            title="Session Verdict",
            border_style=result_color,
        )
    )


def _get_project_scope(client):
    """Get the project scope for experiment configuration."""
    try:
        project = client.get(f"projects/{client.project_id}", include_project=True)
        return project.get("scope", {})
    except Exception:
        return {}
