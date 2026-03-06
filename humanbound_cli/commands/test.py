"""Test command for running security experiments."""

import json
import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import time

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

# Default test category
DEFAULT_TEST_CATEGORY = "humanbound/adversarial/owasp_multi_turn"

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
    help="Test category to run (e.g. humanbound/adversarial/owasp_multi_turn, humanbound/behavioral/qa)"
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
    help="Bot integration config — JSON string or path to JSON file. "
         "Same shape as 'hb init --endpoint'. Overrides the project's default integration."
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
def test_command(test_category: str, testing_level: str, name: str, description: str,
                 lang: str, provider_id: str, endpoint: str,
                 category: str, deep: bool, full: bool,
                 no_auto_start: bool,
                 wait: bool, fail_on: str):
    """Run security tests on the current project.

    Creates and starts a new experiment. Uses the project's default
    integration (set during 'hb init --endpoint'). Override with -e.

    \b
    Examples:
      hb test                                     # Uses project's default integration
      hb test -e ./bot-config.json                # Override with config file
      hb test -t humanbound/adversarial/owasp_single_turn
      hb test --deep                              # System-level test
      hb test --full                              # Acceptance-level test
      hb test --category humanbound/behavioral/qa # Shorthand
      hb test --wait --fail-on=high               # CI/CD mode
      hb test --no-auto-start                     # Manual mode (create only)
    """
    # Resolve shorthand flags — explicit --testing-level / --test-category win
    if category and test_category == DEFAULT_TEST_CATEGORY:
        test_category = category
    if deep and testing_level == "unit":
        testing_level = "system"
    if full and testing_level == "unit":
        testing_level = "acceptance"

    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    # Convert language code to full name if needed (e.g. "en" -> "english")
    lang = LANG_CODE_MAP.get(lang.lower(), lang)

    # Generate name if not provided
    if not name:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        category_short = test_category.split("/")[-1]
        name = f"cli-{category_short}-{timestamp}"

    console.print(f"\n[bold]Starting security test:[/bold] {name}\n")
    console.print(f"  Category: {test_category}")
    console.print(f"  Level: {testing_level}")
    console.print(f"  Language: {lang}")
    console.print()

    try:
        # Resolve provider
        if not provider_id:
            with console.status("Finding provider..."):
                providers = client.list_providers()
            if not providers:
                console.print("[red]No providers configured.[/red]")
                console.print("Use 'hb providers add' to configure a model provider first.")
                raise SystemExit(1)
            # Use default provider or first available
            provider = next((p for p in providers if p.get("is_default")), providers[0])
            provider_id = provider.get("id")
            console.print(f"  Provider: {provider.get('name', 'unknown').upper()} ({provider_id})")

        # Build configuration
        configuration = {}
        if endpoint:
            integration = _load_integration(endpoint)
            configuration["integration"] = integration
        # When no --endpoint is provided, configuration stays {} and the
        # backend falls back to project.default_integration (set by hb init).

        # Create experiment
        experiment_data = {
            "name": name,
            "description": description,
            "test_category": test_category,
            "testing_level": testing_level,
            "lang": lang,
            "provider_id": provider_id,
            "configuration": configuration,
            "auto_start": not no_auto_start,
        }

        with console.status("Creating experiment..."):
            response = client.post(
                "experiments",
                data=experiment_data,
                include_project=True,
            )

        experiment_id = response.get("id")
        if not experiment_id:
            console.print(f"[red]No experiment ID in response:[/red] {response}")
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

        if not wait:
            console.print(Panel(
                f"Experiment ID: {experiment_id}\n\n"
                f"[dim]Check status:[/dim] hb status {experiment_id}\n"
                f"[dim]Watch progress:[/dim] hb status {experiment_id} --watch\n"
                f"[dim]Get logs:[/dim] hb logs {experiment_id}",
                title="Experiment Running",
                border_style="blue"
            ))
            return

        # Wait mode - poll for completion
        console.print("\n[bold]Waiting for completion...[/bold]\n")

        final_status = _wait_for_completion(client, experiment_id)

        # Get final results
        experiment = client.get_experiment(experiment_id)
        results = experiment.get("results", {})
        stats = results.get("stats", {})

        # Display results
        _display_results(experiment, results, stats, client=client)

        # Next suggestions
        _print_next([
            ("hb findings", "Detailed breakdown"),
            ("hb test --deep", "Deeper analysis"),
            ("hb posture", "View posture score"),
            ("hb monitor", "Start continuous monitoring"),
        ])

        # Check fail-on condition
        if fail_on:
            exit_code = _check_fail_on(results, fail_on)
            if exit_code != 0:
                console.print(f"\n[red]Failing due to --fail-on={fail_on} condition[/red]")
                raise SystemExit(exit_code)

        if final_status == "Failed":
            raise SystemExit(1)

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _wait_for_completion(client: HumanboundClient, experiment_id: str) -> str:
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
                status_response = client.get_experiment_status(experiment_id)
                current_status = status_response.get("status", "Unknown")

                # Get log count
                experiment = client.get_experiment(experiment_id)
                results = experiment.get("results", {})
                stats = results.get("stats", {})
                total_logs = stats.get("total", 0)

                progress.update(
                    task,
                    description=f"Status: {current_status}",
                    logs=f"{total_logs} logs"
                )

                if current_status in ("Finished", "Failed", "Terminated"):
                    break

                time.sleep(10)

            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Experiment continues in background.[/yellow]")
                console.print(f"Check status: hb status {experiment_id}")
                raise SystemExit(0)

    return current_status


def _display_results(experiment: dict, results: dict, stats: dict,
                     client: HumanboundClient = None):
    """Display experiment results with posture grade and findings summary."""
    status = experiment.get("status", "Unknown")
    status_color = {
        "Finished": "green",
        "Running": "yellow",
        "Failed": "red",
    }.get(status, "white")

    # Build results panel content
    panel_lines = [
        f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]\n",
        f"[bold]Results:[/bold]",
        f"  Total logs: {stats.get('total', 0)}",
        f"  [green]Pass:[/green] {stats.get('pass', 0)}",
        f"  [red]Fail:[/red] {stats.get('fail', 0)}",
    ]

    # Fetch posture grade and finding count if client is available
    posture_grade = None
    posture_score = None
    finding_count = None
    if client and client.project_id:
        try:
            posture = client.get(
                f"projects/{client.project_id}/posture",
                include_project=True,
            )
            posture_grade = posture.get("grade")
            posture_score = posture.get("overall_score")
        except Exception:
            pass

        try:
            findings_resp = client.list_findings(
                client.project_id, status="open", page=1, size=1,
            )
            # Paginated response: {"data": [...], "total": N, ...}
            finding_count = findings_resp.get("total", 0) if isinstance(findings_resp, dict) else None
        except Exception:
            pass

    if posture_grade is not None:
        grade_color = {
            "A": "green bold", "B": "green", "C": "yellow",
            "D": "red", "F": "red bold",
        }.get(posture_grade, "white")
        score_str = f" ({posture_score:.0f}/100)" if posture_score is not None else ""
        panel_lines.append("")
        panel_lines.append(f"[bold]Posture Grade:[/bold] [{grade_color}]{posture_grade}{score_str}[/{grade_color}]")

    if finding_count is not None:
        panel_lines.append(f"[bold]Open Findings:[/bold] {finding_count}")

    # Check for previous posture snapshot to show delta
    if client and client.project_id and posture_grade:
        try:
            trends = client.get_posture_trends(client.project_id)
            data_points = trends.get("data_points", []) if isinstance(trends, dict) else []
            if len(data_points) >= 2:
                prev = data_points[-2]
                prev_grade = prev.get("grade", "")
                prev_score = prev.get("score")
                if prev_grade and prev_grade != posture_grade:
                    prev_score_str = f" ({prev_score:.0f})" if prev_score is not None else ""
                    panel_lines.append(f"[dim]Previously: {prev_grade}{prev_score_str}[/dim]")
        except Exception:
            pass

    console.print(Panel(
        "\n".join(panel_lines),
        title="Experiment Complete",
        border_style=status_color
    ))

    # Show insights if available
    insights = results.get("insights", [])
    if insights:
        console.print(f"\n[bold]Top Findings ({len(insights)} total):[/bold]")
        for i, insight in enumerate(insights[:5], 1):
            severity = insight.get("severity", "unknown")
            severity_color = {
                "critical": "red bold",
                "high": "red",
                "medium": "yellow",
                "low": "blue",
            }.get(severity.lower(), "white")

            console.print(f"  {i}. [{severity_color}]{severity.upper()}[/{severity_color}]: {insight.get('explanation', '')[:80]}...")


def _check_fail_on(results: dict, fail_on: str) -> int:
    """Check if results meet fail-on condition.

    Returns:
        Exit code (0 = pass, 1 = fail).
    """
    insights = results.get("insights", [])

    severity_levels = ["critical", "high", "medium", "low"]

    if fail_on == "any" and insights:
        return 1

    fail_on_index = severity_levels.index(fail_on) if fail_on in severity_levels else -1

    for insight in insights:
        severity = insight.get("severity", "").lower()
        if severity in severity_levels:
            severity_index = severity_levels.index(severity)
            if severity_index <= fail_on_index:
                return 1

    return 0
