# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Test command for running security experiments."""

import json
import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import time

from ..client import HumanboundClient
from ..engine import get_runner, TestConfig, TestResult, Posture
from ..engine.runner import TestRunner
from ..engine.platform_runner import PlatformTestRunner
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

# Default test category
DEFAULT_TEST_CATEGORY = "humanbound/adversarial/owasp_agentic"

# Testing levels (must match backend TestingLevel enum)
# unit (~20 min), system (~45 min), acceptance (~90 min)
TESTING_LEVELS = ["unit", "system", "acceptance"]

# ISO 639-1 language codes to full name mapping
LANG_CODE_MAP = {
    "af": "afrikaans", "am": "amharic", "ar": "arabic", "az": "azerbaijani",
    "be": "belarusian", "bg": "bulgarian", "bn": "bengali", "bs": "bosnian",
    "ca": "catalan", "cs": "czech", "cy": "welsh", "da": "danish",
    "de": "german", "el": "greek", "en": "english", "es": "spanish",
    "et": "estonian", "eu": "basque", "fa": "persian", "fi": "finnish",
    "fr": "french", "ga": "irish", "gl": "galician", "gu": "gujarati",
    "he": "hebrew", "hi": "hindi", "hr": "croatian", "hu": "hungarian",
    "hy": "armenian", "id": "indonesian", "is": "icelandic", "it": "italian",
    "ja": "japanese", "ka": "georgian", "kk": "kazakh", "km": "khmer",
    "kn": "kannada", "ko": "korean", "lb": "luxembourgish", "lo": "lao",
    "lt": "lithuanian", "lv": "latvian", "mk": "macedonian", "ml": "malayalam",
    "mn": "mongolian", "mr": "marathi", "ms": "malay", "mt": "maltese",
    "my": "burmese", "nb": "norwegian", "ne": "nepali", "nl": "dutch",
    "no": "norwegian", "pa": "punjabi", "pl": "polish", "pt": "portuguese",
    "ro": "romanian", "ru": "russian", "si": "sinhala", "sk": "slovak",
    "sl": "slovenian", "sq": "albanian", "sr": "serbian", "sv": "swedish",
    "sw": "swahili", "ta": "tamil", "te": "telugu", "th": "thai",
    "tl": "tagalog", "tr": "turkish", "uk": "ukrainian", "ur": "urdu",
    "uz": "uzbek", "vi": "vietnamese", "zh": "chinese",
}


def _load_integration(value: str) -> dict:
    """Load integration config from JSON string or file path."""
    path = Path(value)
    if path.is_file():
        try:
            config = json.loads(path.read_text())
            console.print(f"  [green]\u2713[/green] Loaded config: [dim]{path}[/dim]")
            return config
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON in {path}:[/red] {e}")
            raise SystemExit(1)

    try:
        return json.loads(value.strip())
    except json.JSONDecodeError:
        console.print(f"[red]--endpoint must be a JSON string or path to a JSON file.[/red]")
        console.print("[dim]Example: --endpoint ./bot-config.json[/dim]")
        console.print('[dim]Example: --endpoint \'{"streaming": false, "chat_completion": {"endpoint": "...", "headers": {}, "payload": {"content": "$PROMPT"}}}\'[/dim]')
        raise SystemExit(1)


def _print_next(suggestions: list):
    """Print Next: suggestions block."""
    console.print("\n[dim]Next:[/dim]")
    for cmd, desc in suggestions:
        console.print(f"  [bold]{cmd}[/bold]  {desc}")


@click.command("test")
@click.option(
    "--test-category", "-t",
    default=DEFAULT_TEST_CATEGORY,
    help="Test category to run (e.g. humanbound/adversarial/owasp_agentic, humanbound/behavioral/qa)"
)
@click.option(
    "--testing-level", "-l",
    type=click.Choice(TESTING_LEVELS, case_sensitive=False),
    default="unit",
    help="Testing depth level"
)
@click.option(
    "--name", "-n",
    help="Experiment name (auto-generated if not provided)"
)
@click.option(
    "--description", "-d",
    default="",
    help="Experiment description"
)
@click.option(
    "--lang",
    default="english",
    help="Language for test prompts (default: english). Accepts codes (en, de, es) or full names."
)
@click.option(
    "--provider-id",
    help="Provider ID to use (default: first available or default provider)"
)
@click.option(
    "--endpoint", "-e",
    help="Agent integration config — JSON string or path to JSON file. "
         "Same shape as 'hb connect --endpoint'. Overrides the project's default integration."
)
@click.option(
    "--category",
    default=None,
    help="Shorthand alias for --test-category (e.g. humanbound/behavioral/qa)"
)
@click.option(
    "--deep",
    is_flag=True,
    default=False,
    help="Shortcut for --testing-level system (deeper analysis)"
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Shortcut for --testing-level acceptance (full analysis)"
)
@click.option(
    "--quick", "-q",
    is_flag=True,
    default=False,
    help="Quick scan: top 4 OWASP categories, ~5 minutes"
)
@click.option(
    "--no-auto-start",
    is_flag=True,
    default=False,
    help="Create experiment without auto-starting (manual mode)"
)
@click.option(
    "--wait", "-w",
    is_flag=True,
    help="Wait for experiment to complete"
)
@click.option(
    "--fail-on",
    type=click.Choice(["critical", "high", "medium", "low", "any"]),
    help="Exit with error if findings of this severity or higher are found"
)
@click.option(
    "--context", "-c",
    help="Extra context for the judge (e.g. 'Authenticated as Alice, her PII is expected'). String or path to .txt file."
)
@click.option(
    "--local",
    is_flag=True,
    default=False,
    help="Force local engine execution (even when logged in)"
)
@click.option(
    "--repo", "-r",
    type=click.Path(exists=True),
    help="Repository path for scope discovery (scans for system prompt + tools)"
)
@click.option(
    "--prompt", "-p",
    type=click.Path(exists=True),
    help="System prompt file for scope extraction"
)
@click.option(
    "--scope", "-s",
    "scope_path",
    type=click.Path(exists=True),
    help="Explicit scope file (YAML/JSON with permitted/restricted intents)"
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Debug mode: single-threaded, full sequential output (turns, scores, verdicts)"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Verbose mode: live dashboard with per-category progress"
)
def test_command(test_category: str, testing_level: str, name: str, description: str,
                 lang: str, provider_id: str, endpoint: str,
                 category: str, deep: bool, full: bool, quick: bool,
                 no_auto_start: bool,
                 wait: bool, fail_on: str, context: str, local: bool,
                 repo: str, prompt: str, scope_path: str,
                 debug: bool, verbose: bool):
    """Run security tests against your agent.

    \b
    Local mode (no login required):
      hb test --endpoint ./config.json --repo . --wait
      hb test --endpoint ./config.json --prompt ./system.txt --wait
      hb test --endpoint ./config.json --scope ./scope.yaml --wait

    \b
    Platform mode (requires login + project):
      hb test                                     # Uses project's default integration
      hb test -e ./bot-config.json                # Override with config file
      hb test --wait --fail-on=high               # CI/CD mode

    \b
    Options:
      hb test --deep                              # System-level test (~45 min)
      hb test --full                              # Acceptance-level test (~90 min)
      hb test --category humanbound/behavioral/qa # Behavioral/QA tests
    """
    # Resolve shorthand flags — explicit --testing-level / --test-category win
    if category and test_category == DEFAULT_TEST_CATEGORY:
        test_category = category
    if quick:
        testing_level = "unit"  # quick uses unit depth but fewer categories
    elif deep and testing_level == "unit":
        testing_level = "system"
    elif full and testing_level == "unit":
        testing_level = "acceptance"

    # Convert language code to full name if needed (e.g. "en" -> "english")
    lang = LANG_CODE_MAP.get(lang.lower(), lang)

    # Generate name if not provided
    if not name:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        category_short = test_category.split("/")[-1]
        name = f"cli-{category_short}-{timestamp}"

    # --- Runner selection (login is the only switch) ---
    try:
        runner = get_runner(force_local=local)
    except Exception:
        # Fallback: try platform if get_runner fails
        runner = None

    is_platform = isinstance(runner, PlatformTestRunner)

    # Platform mode: validate auth + project
    if is_platform:
        client = runner.client
        if not client.project_id:
            console.print("[yellow]No project selected.[/yellow]")
            console.print("Use 'hb projects use <id>' to select a project first.")
            raise SystemExit(1)
    elif runner is None:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        console.print("[dim]Local engine coming soon in the open-core release.[/dim]")
        raise SystemExit(1)

    console.print(f"\n[bold]Starting security test:[/bold] {name}\n")
    console.print(f"  Category: {test_category}")
    console.print(f"  Level: {testing_level}")
    console.print(f"  Language: {lang}")
    console.print()

    try:
        # Resolve provider (platform: from API, local: from env/config — handled by runner)
        if is_platform and not provider_id:
            client = runner.client
            with console.status("Finding provider..."):
                providers = client.list_providers()
            if not providers:
                console.print("[red]No providers configured.[/red]")
                console.print("Use 'hb providers add' to configure a model provider first.")
                raise SystemExit(1)
            provider = next((p for p in providers if p.get("is_default")), providers[0])
            provider_id = provider.get("id")
            console.print(f"  Provider: {provider.get('name', 'unknown').upper()} ({provider_id})")

        # Resolve endpoint integration
        integration = None
        if endpoint:
            integration = _load_integration(endpoint)
            has_telemetry = bool(integration.get("telemetry"))
        elif is_platform:
            try:
                client = runner.client
                project = client.get(f"projects/{client.project_id}", include_project=True)
                default_integ = project.get("default_integration") or {}
                has_telemetry = bool(default_integ.get("telemetry"))
            except Exception:
                has_telemetry = False
        else:
            has_telemetry = False

        if has_telemetry:
            console.print(f"  Depth: [green]whitebox[/green] (telemetry enabled)")
        else:
            console.print(f"  Depth: [yellow]blackbox[/yellow]")

        # Context: string or path to .txt file (max 1500 chars)
        ctx_value = ""
        if context:
            ctx_path = Path(context)
            ctx_value = ctx_path.read_text().strip() if ctx_path.is_file() else context
            if len(ctx_value) > 1500:
                console.print(f"[red]Context too long ({len(ctx_value)} chars). Maximum is 1,500.[/red]")
                raise SystemExit(1)

        # Build TestConfig (canonical shape — same for both runners)
        config = TestConfig(
            test_category=test_category,
            testing_level=testing_level,
            lang=lang,
            name=name,
            description=description,
            provider_id=provider_id or "",
            endpoint=integration,
            context=ctx_value,
            auto_start=not no_auto_start,
            repo_path=repo,
            prompt_path=prompt,
            scope_path=scope_path,
            debug=debug,
            verbose=verbose,
        )

        # Start experiment via runner
        with console.status("Creating experiment..."):
            experiment_id = runner.start(config)

        if not experiment_id:
            console.print("[red]Failed to create experiment.[/red]")
            raise SystemExit(1)

        console.print(f"[green]\u2713[/green] Experiment created: {experiment_id}")
        if not no_auto_start:
            console.print(f"[green]\u2713[/green] Experiment started")

        # Estimate time
        time_estimates = {
            "unit": "~20 minutes",
            "system": "~45 minutes",
            "acceptance": "~90 minutes",
        }
        console.print(f"\n[dim]Estimated time: {time_estimates.get(testing_level, 'unknown')}[/dim]")

        # Local mode: --wait is implicit (engine runs in-process, exits with CLI)
        if not wait and not is_platform:
            wait = True
            console.print("[dim]Local mode: --wait is automatic (engine runs in-process)[/dim]")

        if not wait:
            import random
            _chill_messages = [
                "Go grab a coffee -- we've got it from here. Email incoming when done.",
                "Red team deployed -- treat yourself to a beer, email coming soon.",
                "Our agents are on it -- go touch grass, we'll email you the results.",
                "The bots are fighting -- grab a snack and check your inbox later.",
                "Hacking in progress -- no really, go do something fun. Email on the way.",
                "We're poking your agent now -- go stretch, results hit your inbox shortly.",
                "Time for a break -- we'll ping you by email once we're through.",
                "Sit back and relax -- we'll email you when results are ready.",
            ]
            console.print(Panel(
                f"Experiment ID: {experiment_id}\n\n"
                f"{random.choice(_chill_messages)}\n\n"
                f"[dim]Check status:[/dim] hb status {experiment_id}\n"
                f"[dim]Watch progress:[/dim] hb status {experiment_id} --watch\n"
                f"[dim]Get logs:[/dim] hb logs {experiment_id}",
                title="Experiment Running",
                border_style="blue"
            ))
            return

        # Wait mode - poll for completion
        if not is_platform:
            console.print("[dim]Ctrl+C will stop the test (engine runs in-process)[/dim]")

        if verbose and not is_platform:
            console.print("\n[bold]Watching test progress...[/bold]\n")
            final_status = _wait_verbose(runner, experiment_id)
        else:
            console.print("\n[bold]Waiting for completion...[/bold]\n")
            final_status = _wait_for_completion(runner, experiment_id)

        # Get final results via runner
        result = runner.get_result(experiment_id)
        posture = runner.get_posture(experiment_id)

        # Display results (same rendering, canonical shapes)
        _display_results(result, posture)

        # Next suggestions — vary by mode
        if is_platform:
            _print_next([
                ("hb findings", "Detailed breakdown"),
                ("hb test --deep", "Deeper analysis"),
                ("hb posture", "View posture score"),
                ("hb monitor", "Start continuous monitoring"),
            ])
        else:
            _print_next([
                ("hb logs", "View conversation details"),
                ("hb posture", "View posture score"),
                ("hb report -o report.html", "Generate report"),
                ("hb guardrails -o rules.yaml", "Export firewall rules"),
            ])

        # Check fail-on condition
        if fail_on:
            exit_code = _check_fail_on(result, fail_on)
            if exit_code != 0:
                console.print(f"\n[red]Failing due to --fail-on={fail_on} condition[/red]")
                raise SystemExit(exit_code)

        if final_status == "Failed":
            raise SystemExit(1)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        console.print("[dim]Or use local mode: hb test --endpoint ./config.json --wait[/dim]")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _wait_for_completion(runner: TestRunner, experiment_id: str) -> str:
    """Wait for experiment to complete with progress display."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.fields[logs]}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running...", total=None, logs="")

        while True:
            try:
                status = runner.get_status(experiment_id)

                progress.update(
                    task,
                    description=f"Status: {status.status}",
                    logs=f"{status.log_count} logs"
                )

                if status.status in ("Finished", "Failed", "Terminated"):
                    break

                time.sleep(10)

            except KeyboardInterrupt:
                from ..engine.local_runner import LocalTestRunner
                if isinstance(runner, LocalTestRunner):
                    console.print("\n[yellow]Interrupted. Stopping test (waiting for current conversation to finish)...[/yellow]")
                    runner.terminate(experiment_id)
                    run = runner._runs.get(experiment_id)
                    if run and run.thread:
                        try:
                            run.thread.join(timeout=30)
                        except KeyboardInterrupt:
                            pass  # second Ctrl+C during join — force exit
                    if run and run.logs:
                        # Save partial results to disk
                        from ..engine.presenter import run as presenter_run
                        run.results = presenter_run(None, run.logs, test_category=run.config.test_category)
                        run.status = "Failed"
                        run._save_results()
                        console.print(f"[dim]Partial results: {len(run.logs)} conversations saved[/dim]")
                        console.print(f"[dim]  hb logs         View completed conversations[/dim]")
                        console.print(f"[dim]  hb posture      View partial posture score[/dim]")
                        console.print(f"[dim]  hb report -o report.html  Generate report[/dim]")
                else:
                    console.print(f"\n[yellow]Detached. Experiment continues on platform.[/yellow]")
                    console.print(f"  Check status:  hb status {experiment_id}")
                    console.print(f"  View logs:     hb logs {experiment_id}")
                    console.print(f"  Stop it:       hb experiments terminate {experiment_id}")
                import os
                os._exit(0)

    return status.status


def _wait_verbose(runner, experiment_id: str) -> str:
    """Wait with Rich progress bar + final results table."""
    from rich.table import Table
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel as RichPanel
    from ..engine.local_runner import LocalTestRunner

    if not isinstance(runner, LocalTestRunner):
        return _wait_for_completion(runner, experiment_id)

    # Estimate total conversations for progress bar
    run = runner._runs.get(experiment_id)

    try:
        from rich.live import Live
        from rich.text import Text

        def _build_status_line():
            status = runner.get_status(experiment_id)
            run = runner._runs.get(experiment_id)

            passed = sum(1 for l in (run.logs if run else []) if l.get("result") == "pass")
            failed = sum(1 for l in (run.logs if run else []) if l.get("result") == "fail")
            total = status.log_count

            # Build progress bar manually
            bar_width = 40
            text = Text()
            text.append(f"  {status.status}", style="bold")
            text.append(f"  {total} conversations  ", style="dim")

            # Bar
            text.append("[")
            if total > 0:
                filled = min(bar_width, int(total / max(total, 1) * bar_width))
                text.append("=" * filled, style="green")
                text.append(" " * (bar_width - filled), style="dim")
            else:
                text.append("." * bar_width, style="dim")
            text.append("]  ")

            text.append(f"{passed} passed ", style="green")
            text.append(f"{failed} failed", style="red" if failed > 0 else "dim")

            # Show accumulative fail categories detected
            if run and run.logs:
                fail_cats = set()
                for l in run.logs:
                    if l.get("result") == "fail":
                        fc = l.get("fail_category", "")
                        if fc:
                            fail_cats.add(fc.split(",")[0].strip()[:20])
                if fail_cats:
                    text.append("  ")
                    text.append(", ".join(sorted(fail_cats)), style="red dim")

            return text, status

        with Live(console=console, refresh_per_second=0.5) as live:
            while True:
                text, status = _build_status_line()
                live.update(text)

                if status.status in ("Finished", "Failed", "Terminated"):
                    break

                time.sleep(3)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Stopping test (waiting for current conversation to finish)...[/yellow]")
        runner.terminate(experiment_id)
        run = runner._runs.get(experiment_id)
        if run and run.thread:
            try:
                run.thread.join(timeout=30)
            except KeyboardInterrupt:
                pass
        if run and run.logs:
            from ..engine.presenter import run as presenter_run
            run.results = presenter_run(None, run.logs, test_category=run.config.test_category)
            run.status = "Failed"
            run._save_results()
            console.print(f"[dim]Partial results: {len(run.logs)} conversations saved[/dim]")
            console.print(f"[dim]  hb logs         View completed conversations[/dim]")
            console.print(f"[dim]  hb posture      View partial posture score[/dim]")
        import os
        os._exit(0)

    # Final: show results table with all conversations
    run = runner._runs.get(experiment_id)
    if run and run.logs:
        table = Table(title=f"Conversations ({len(run.logs)} total)", show_header=True, expand=True)
        table.add_column("#", width=4, justify="right")
        table.add_column("Verdict", width=6)
        table.add_column("Severity", width=8)
        table.add_column("Category", width=22)
        table.add_column("Explanation", ratio=1)

        for i, log in enumerate(run.logs, 1):
            result_val = log.get("result", "")
            if result_val == "pass":
                result_style = "[green]pass[/green]"
            elif result_val == "fail":
                result_style = "[red]fail[/red]"
            else:
                result_style = "[yellow]err[/yellow]"

            severity = log.get("severity", 0)
            if isinstance(severity, (int, float)) and severity >= 76:
                sev_style = f"[red bold]{severity}[/red bold]"
            elif isinstance(severity, (int, float)) and severity >= 51:
                sev_style = f"[red]{severity}[/red]"
            elif isinstance(severity, (int, float)) and severity >= 26:
                sev_style = f"[yellow]{severity}[/yellow]"
            else:
                sev_style = f"[dim]{severity}[/dim]"

            cat = log.get("fail_category") or log.get("gen_category") or ""
            explanation = (log.get("explanation", "") or "")[:80]

            table.add_row(str(i), result_style, sev_style, cat[:22], explanation)

        console.print()
        console.print(table)

    return status.status


def _display_results(result: TestResult, posture: Posture):
    """Display experiment results with posture grade and findings summary.

    Uses canonical TestResult and Posture shapes — works identically
    for both platform and local runners.
    """
    status = result.status
    status_color = {
        "Finished": "green",
        "Running": "yellow",
        "Failed": "red",
    }.get(status, "white")

    stats = result.stats

    # Build results panel content
    panel_lines = [
        f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]\n",
        f"[bold]Results:[/bold]",
        f"  Total logs: {stats.get('total', 0)}",
        f"  [green]Pass:[/green] {stats.get('pass', 0)}",
        f"  [red]Fail:[/red] {stats.get('fail', 0)}",
    ]

    # Posture grade (available from both runners)
    if posture.grade is not None:
        grade_color = {
            "A": "green bold", "B": "green", "C": "yellow",
            "D": "red", "F": "red bold",
        }.get(posture.grade, "white")
        score_str = f" ({posture.overall_score:.0f}/100)" if posture.overall_score is not None else ""
        panel_lines.append("")
        panel_lines.append(f"[bold]Posture Grade:[/bold] [{grade_color}]{posture.grade}{score_str}[/{grade_color}]")

    # Open findings count (platform only — None locally)
    if posture.finding_count is not None:
        panel_lines.append(f"[bold]Open Findings:[/bold] {posture.finding_count}")

    # Previous posture delta (platform only — None locally)
    if posture.previous_grade and posture.previous_grade != posture.grade:
        prev_score_str = f" ({posture.previous_score:.0f})" if posture.previous_score is not None else ""
        panel_lines.append(f"[dim]Previously: {posture.previous_grade}{prev_score_str}[/dim]")

    console.print(Panel(
        "\n".join(panel_lines),
        title="Experiment Complete",
        border_style=status_color
    ))

    # Show insights if available
    insights = result.insights
    if insights:
        console.print(f"\n[bold]Top Findings ({len(insights)} total):[/bold]")
        for i, insight in enumerate(insights[:5], 1):
            severity = insight.get("severity", "unknown")
            severity_str = str(severity).lower() if isinstance(severity, str) else "unknown"
            severity_color = {
                "critical": "red bold",
                "high": "red",
                "medium": "yellow",
                "low": "blue",
            }.get(severity_str, "white")

            console.print(f"  {i}. [{severity_color}]{severity_str.upper()}[/{severity_color}]: {insight.get('explanation', '')[:80]}...")


def _check_fail_on(result: TestResult, fail_on: str) -> int:
    """Check if results meet fail-on condition.

    Returns:
        Exit code (0 = pass, 1 = fail).
    """
    insights = result.insights

    severity_levels = ["critical", "high", "medium", "low"]

    if fail_on == "any" and insights:
        return 1

    fail_on_index = severity_levels.index(fail_on) if fail_on in severity_levels else -1

    for insight in insights:
        severity = str(insight.get("severity", "")).lower()
        if severity in severity_levels:
            severity_index = severity_levels.index(severity)
            if severity_index <= fail_on_index:
                return 1

    return 0
