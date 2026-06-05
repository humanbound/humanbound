# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Connect command — unified entry point for agent and platform onboarding."""

import json
import random
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import click
from rich.console import Console
from rich.panel import Panel

from .. import telemetry
from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError
from .test import _load_integration, _resolve_context

console = Console()

SCAN_TIMEOUT = 180
DEFAULT_TEST_CATEGORY = "humanbound/adversarial/owasp_agentic"


# -- Scan progress UI ----------------------------------------------------------

_SCAN_PHASES = {
    "endpoint": [
        "Connecting to your bot...",
        "Chatting with your bot...",
        "Exploring capabilities...",
        "Wrapping up conversation...",
    ],
    "text": [
        "Reading your prompt...",
    ],
    "agentic": [
        "Analysing agent tools...",
    ],
    "reflect": [
        "Extracting scope...",
        "Classifying intents...",
        "Assessing risk profile...",
        "Finalising analysis...",
    ],
}

_PLAYFUL_MESSAGES = [
    "Kicking the tires...",
    "Poking around...",
    "Asking nicely...",
    "Pretending to be a user...",
    "Checking under the hood...",
    "Shaking the tree...",
    "Looking for breadcrumbs...",
    "Testing the waters...",
    "Playing twenty questions...",
    "Seeing what sticks...",
    "Connecting the dots...",
    "Reading between the lines...",
    "Following the clues...",
    "Pulling on threads...",
    "Mapping the terrain...",
    "Snooping around...",
    "Warming up the neurons...",
    "Brewing some insights...",
]


def _scan_with_progress(client: HumanboundClient, sources: list, timeout: int, phases: list):
    """Run POST /scan with rotating status messages."""
    result: dict = {}
    error: Exception | None = None

    def do_scan():
        nonlocal result, error
        try:
            result = client.post(
                "scan",
                data={"sources": sources},
                include_project=False,
                timeout=timeout,
            )
        except Exception as e:
            error = e

    thread = threading.Thread(target=do_scan)
    scan_start = time.time()
    thread.start()

    playful = _PLAYFUL_MESSAGES.copy()
    random.shuffle(playful)

    phase_idx = 0
    playful_idx = 0
    rotate_interval = 4

    with console.status("") as status:
        while thread.is_alive():
            elapsed = time.time() - scan_start
            phase = phases[phase_idx % len(phases)] if phases else "Scanning..."
            fun = playful[playful_idx % len(playful)]
            status.update(
                f"[bold]{phase}[/bold] [dim]({elapsed:.0f}s)[/dim]\n"
                f"  [dim italic]{fun}[/dim italic]"
            )
            thread.join(timeout=rotate_interval)
            playful_idx += 1
            if playful_idx % 2 == 0:
                phase_idx += 1

    if error:
        raise error

    return result


def _display_scope(scope: dict):
    """Render scope: business context + permitted/restricted intents."""
    business_scope = scope.get("overall_business_scope", "")
    intents = scope.get("intents", {})
    permitted = intents.get("permitted", [])
    restricted = intents.get("restricted", [])

    parts = []
    if business_scope:
        parts.append(business_scope[:500] + ("..." if len(business_scope) > 500 else ""))

    if permitted and isinstance(permitted, list):
        parts.append("")
        parts.append("[bold green]Permitted:[/bold green]")
        for intent in permitted[:10]:
            parts.append(f"  [green]•[/green] {str(intent)[:80]}")
        if len(permitted) > 10:
            parts.append(f"  [dim]... and {len(permitted) - 10} more[/dim]")

    if restricted and isinstance(restricted, list):
        parts.append("")
        parts.append("[bold red]Restricted:[/bold red]")
        for intent in restricted[:10]:
            parts.append(f"  [red]•[/red] {str(intent)[:80]}")
        if len(restricted) > 10:
            parts.append(f"  [dim]... and {len(restricted) - 10} more[/dim]")

    if not permitted and not restricted:
        parts.append("")
        parts.append("[dim]No intents extracted — the LLM may need more context.[/dim]")
        parts.append("[dim]Try adding --prompt with a system prompt file for better results.[/dim]")

    console.print(
        Panel(
            "\n".join(parts),
            title="Scope",
            border_style="blue",
        )
    )


def _risk_bar(level: str) -> str:
    fill_map = {"LOW": 4, "MEDIUM": 8, "HIGH": 12}
    color_map = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
    filled = fill_map.get(level, 8)
    color = color_map.get(level, "white")
    return f"[{color}]{'█' * filled}[/{color}][dim]{'░' * (12 - filled)}[/dim]"


def _display_dashboard(name: str, risk_profile: dict, has_integration: bool, has_telemetry: bool):
    """Compact risk dashboard rendered after a successful Platform scan."""
    risk_level = risk_profile.get("risk_level", "?")
    industry = risk_profile.get("industry", "unknown")
    risk_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}.get(risk_level, "white")

    lines = []
    lines.append(
        f"  Risk     {_risk_bar(risk_level)}  "
        f"[{risk_color}][bold]{risk_level}[/bold][/{risk_color}] · {industry}"
    )

    pii = risk_profile.get("handles_pii", False)
    fin = risk_profile.get("handles_financial_data", False)
    health = risk_profile.get("handles_health_data", False)
    pii_i = "[yellow]⚠ PII[/yellow]" if pii else "[dim]○ PII[/dim]"
    fin_i = "[yellow]⚠ Financial[/yellow]" if fin else "[dim]○ Financial[/dim]"
    hea_i = "[yellow]⚠ Health[/yellow]" if health else "[dim]○ Health[/dim]"
    lines.append(f"  Data     {pii_i}   {fin_i}   {hea_i}")

    integ = "[green]✓ configured[/green]" if has_integration else "[dim]✗ none[/dim]"
    tele = "[green]✓ enabled[/green]" if has_telemetry else "[dim]✗ disabled[/dim]"
    lines.append(f"  Integ    {integ}        Telemetry  {tele}")

    regs = risk_profile.get("applicable_regulations", [])
    if regs:
        reg_str = "  ".join(f"[cyan]{r.upper()}[/cyan]" for r in regs)
        lines.append(f"  Regs     {reg_str}")

    rationale = risk_profile.get("risk_rationale", "")
    if rationale:
        if len(rationale) > 120:
            rationale = rationale[:117] + "..."
        lines.append("")
        lines.append(f"  [dim italic]{rationale}[/dim italic]")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold]{name}[/bold]",
            border_style=risk_color,
        )
    )


def _get_source_description(prompt: str, endpoint: str, repo: str, openapi: str) -> str:
    """Short human description of which --flag sources were used."""
    sources = []
    if prompt:
        sources.append(f"prompt ({Path(prompt).name})")
    if endpoint:
        path = Path(endpoint)
        if path.is_file():
            sources.append(f"endpoint ({path.name})")
        else:
            sources.append("endpoint (inline)")
    if repo:
        sources.append(f"repo ({Path(repo).name})")
    if openapi:
        sources.append(f"openapi ({Path(openapi).name})")
    return ", ".join(sources)


def _resolve_init_mode(
    endpoint: str | None,
    prompt: str | None,
    repo: str | None,
    openapi: str | None,
) -> str:
    """Derive the `init` telemetry mode from the CLI flags."""
    if endpoint:
        return "endpoint"
    if prompt:
        return "text"
    if repo or openapi:
        return "agentic"
    return "none"


def _fire_init_event(
    mode: str,
    success: bool,
    duration_ms: int,
    *,
    no_test: bool = False,
    test_category: str = DEFAULT_TEST_CATEGORY,
    scope_provided: bool = False,
) -> None:
    """Emit the `init` telemetry event. Safe to call from try/finally."""
    telemetry.capture(
        "init",
        {
            "mode": mode,
            "success": success,
            "duration_ms": duration_ms,
            "no_test": no_test,
            "test_category": test_category,
            "scope_provided": scope_provided,
        },
    )


def _print_next(suggestions: list):
    """Print Next: suggestions block."""
    console.print("\n[dim]Next:[/dim]")
    for cmd, desc in suggestions:
        console.print(f"  [bold]{cmd}[/bold]  {desc}")


_NAME_WORDS = [
    "amber",
    "atlas",
    "blaze",
    "cedar",
    "coral",
    "delta",
    "dune",
    "ember",
    "flint",
    "frost",
    "glyph",
    "grove",
    "haven",
    "ivory",
    "jade",
    "lunar",
    "maple",
    "nexus",
    "onyx",
    "pearl",
    "pulse",
    "quartz",
    "ridge",
    "sage",
    "slate",
    "spark",
    "steel",
    "storm",
    "surge",
    "terra",
    "tide",
    "vault",
    "venom",
    "vigor",
    "wave",
    "zinc",
]


def _derive_agent_name(endpoint: str) -> str:
    """Derive a short project name: {agent}-{word}-{hex4}."""
    import random

    suffix = f"{random.choice(_NAME_WORDS)}-{random.randbytes(2).hex()}"
    if not endpoint:
        return f"agent.{suffix}"
    try:
        path = Path(endpoint)
        raw = path.read_text() if path.is_file() else endpoint
        config = json.loads(raw)
        ep_url = config.get("chat_completion", {}).get("endpoint", "")
        if ep_url:
            hostname = urlparse(ep_url).hostname
            if hostname:
                # Extract first subdomain segment as agent name
                agent = hostname.split(".")[0]
                return f"{agent}.{suffix}"
    except Exception:
        pass
    return f"agent.{suffix}"


@click.command("connect")
@click.option("--endpoint", "-e", help="Agent config JSON or file path")
@click.option("--name", "-n", help="Project name (optional, auto-generated)")
@click.option("--prompt", "-p", type=click.Path(exists=True), help="System prompt file")
@click.option("--repo", "-r", type=click.Path(exists=True), help="Repository path")
@click.option("--openapi", "-o", type=click.Path(exists=True), help="OpenAPI spec file")
@click.option(
    "--context",
    "-c",
    help="Extra context for the judge (e.g. 'Authenticated as Alice, her PII is expected'). String or path to .txt file.",
)
@click.option(
    "--level",
    "-l",
    type=click.Choice(["unit", "system", "acceptance"]),
    default="unit",
    help="Testing depth: unit (quick), system (deep), acceptance (full)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmations")
@click.option("--timeout", "-t", type=int, default=SCAN_TIMEOUT, help="Request timeout in seconds")
@click.option(
    "--no-test",
    is_flag=True,
    default=False,
    help="Skip the auto-test step after project creation.",
)
@click.option(
    "--test-category",
    default=None,
    help="Test category to run (e.g. humanbound/adversarial/owasp_agentic, humanbound/behavioral/qa)",
)
@click.option(
    "--scope",
    "scope_path",
    type=click.Path(exists=True),
    help="Pre-made scope file (YAML/JSON with permitted/restricted intents)",
)
def connect_command(
    endpoint,
    name,
    prompt,
    repo,
    openapi,
    context,
    level,
    yes,
    timeout,
    no_test,
    test_category,
    scope_path,
):
    """Connect your AI agent.

    Probes your agent, extracts scope, creates a project, and runs the first test.

    \b
    Examples:
      hb connect --endpoint ./config.json
      hb connect --endpoint ./config.json --prompt ./system.txt
    """
    import time

    start = time.monotonic()
    mode = _resolve_init_mode(endpoint, prompt, repo, openapi)
    success = False

    try:
        has_agent_flags = any([endpoint, prompt, repo, openapi, scope_path])

        if has_agent_flags:
            _connect_agent(
                endpoint,
                name,
                prompt,
                repo,
                openapi,
                context,
                level,
                yes,
                timeout,
                no_test=no_test,
                test_category_arg=test_category,
                scope_path=scope_path,
            )
        else:
            console.print("[yellow]Specify a source:[/yellow]")
            console.print()
            console.print("  hb connect --endpoint ./bot-config.json")
            console.print()
            console.print("[dim]Use --endpoint, --prompt, --repo, --openapi, or --scope.[/dim]")
            raise SystemExit(1)

        success = True
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        _fire_init_event(
            mode=mode,
            success=success,
            duration_ms=duration_ms,
            no_test=no_test,
            test_category=test_category or DEFAULT_TEST_CATEGORY,
            scope_provided=bool(scope_path),
        )


# -- Agent path ----------------------------------------------------------------


def _connect_agent(
    endpoint,
    name,
    prompt,
    repo,
    openapi,
    context,
    level,
    yes,
    timeout,
    no_test=False,
    test_category_arg=None,
    scope_path=None,
):
    """Agent path: dispatch to Platform flow (authenticated) or local flow (anonymous).

    Platform flow creates a project on humanbound.ai with full scope, risk profile,
    regulatory mapping, and auto-test. Local flow derives scope + lightweight
    compliance from the user's configured LLM provider and writes scope.yaml.
    """
    source_flags = [prompt, endpoint, repo, openapi, scope_path]
    if not any(source_flags):
        console.print("[yellow]No extraction source provided.[/yellow]")
        console.print(
            "Use --endpoint, --prompt, --repo, --openapi, or --scope to specify a source."
        )
        raise SystemExit(1)

    if not name:
        name = _derive_agent_name(endpoint) if endpoint else "local-agent"

    client = HumanboundClient()
    if client.is_authenticated() and client.organisation_id:
        _connect_agent_platform(
            client,
            endpoint,
            name,
            prompt,
            repo,
            openapi,
            context,
            level,
            yes,
            timeout,
            no_test=no_test,
            test_category_arg=test_category_arg,
            scope_path=scope_path,
        )
    else:
        _connect_agent_local(endpoint, name, prompt, repo, openapi, context, level, yes, timeout)


def _connect_agent_platform(
    client,
    endpoint,
    name,
    prompt,
    repo,
    openapi,
    context,
    level,
    yes,
    timeout,
    no_test=False,
    test_category_arg=None,
    scope_path=None,
):
    """Platform flow: POST /scan -> create project -> auto-test -> dashboard."""
    resolved_category = test_category_arg or DEFAULT_TEST_CATEGORY
    if no_test and test_category_arg:
        console.print("[yellow]! --test-category is ignored when --no-test is set.[/yellow]")
        console.print(f"[dim]  To run later: hb test --test-category {test_category_arg}[/dim]")

    # Warn about redundant scope-source flags when --scope is set.
    if scope_path and (prompt or repo or openapi):
        ignored = [
            f"--{flag}"
            for flag, val in (("prompt", prompt), ("repo", repo), ("openapi", openapi))
            if val
        ]
        console.print(
            f"[yellow]! {'/'.join(ignored)} ignored when --scope is set "
            f"(scope comes from the file).[/yellow]"
        )

    console.print(f"\n[bold]Connecting agent:[/bold] {name}\n")

    try:
        sources = []
        user_scope = None  # Set only when --scope is used
        local_integration = None  # Set when --endpoint is used with --scope

        if scope_path:
            # --scope path: load file, serialize to a single text source.
            try:
                user_scope = _load_scope_file(scope_path)
            except (FileNotFoundError, ValueError) as e:
                console.print(f"[red]Error:[/red] {e}")
                raise SystemExit(1)

            console.print(
                f"  [green]\u2713[/green] Loaded scope: [dim]{Path(scope_path).name}[/dim]"
            )
            sources.append(
                {"source": "text", "data": {"text": _serialize_scope_to_text(user_scope)}}
            )

            # If --endpoint is also passed, keep its config for default_integration
            # but DO NOT include it as a /scan source (no agent probing).
            if endpoint:
                local_integration = _load_integration(endpoint)
                chat_ep = local_integration.get("chat_completion", {}).get("endpoint", "")
                console.print(
                    f"  [green]\u2713[/green] Endpoint integration: [dim]{chat_ep or '(from config)'}[/dim]"
                )
        else:
            # -- Build sources array for POST /scan --------------------------------
            text_parts = []

            # --prompt -> text source
            if prompt:
                console.print(f"  [green]\u2713[/green] Loaded prompt: [dim]{prompt}[/dim]")
                prompt_text = Path(prompt).read_text()
                text_parts.append(prompt_text)

            # --repo -> agentic or text source
            if repo:
                from ..extractors.repo import RepoScanner

                scanner = RepoScanner(repo)
                with console.status("[dim]Scanning repository...[/dim]"):
                    scan_result = scanner.scan()

                if scan_result:
                    files = scan_result.get("files", [])
                    if scan_result.get("tools"):
                        console.print(
                            f"  [green]\u2713[/green] Repository: {len(files)} files, {len(scan_result['tools'])} tools (source: agentic)"
                        )
                        sources.append(
                            {
                                "source": "agentic",
                                "data": {
                                    "system_prompt": scan_result.get("system_prompt", ""),
                                    "tools": scan_result.get("tools", []),
                                },
                            }
                        )
                    else:
                        console.print(f"  [green]\u2713[/green] Repository: {len(files)} files")
                        combined = scan_result.get("system_prompt", "")
                        if scan_result.get("readme"):
                            combined += f"\n\nREADME:\n{scan_result['readme']}"
                        if combined.strip():
                            text_parts.append(combined)
                else:
                    console.print("  [yellow]![/yellow] Repository: no relevant files found")

            # --openapi -> text source
            if openapi:
                from ..extractors.openapi import OpenAPIParser

                parser = OpenAPIParser(openapi)
                with console.status("[dim]Parsing specification...[/dim]"):
                    spec_result = parser.parse()

                if spec_result:
                    operations = spec_result.get("operations", [])
                    console.print(
                        f"  [green]\u2713[/green] OpenAPI spec: {len(operations)} operations"
                    )
                    summary_parts = [spec_result.get("description", "API-based agent")]
                    for op in operations:
                        summary_parts.append(
                            f"- {op.get('method', 'GET')} {op.get('path', '')}: {op.get('summary', '')}"
                        )
                    text_parts.append("\n".join(summary_parts))
                else:
                    console.print("  [yellow]![/yellow] OpenAPI spec: could not parse")

            # --endpoint -> endpoint source (API probing)
            if endpoint:
                bot_config = _load_integration(endpoint)
                chat_ep = bot_config.get("chat_completion", {}).get("endpoint", "")
                console.print(
                    f"  [green]\u2713[/green] Endpoint source: [dim]{chat_ep or '(from config)'}[/dim]"
                )
                sources.append({"source": "endpoint", "data": bot_config})

            # Merge accumulated text parts into a single text source
            if text_parts:
                merged_text = "\n\n---\n\n".join(text_parts)
                sources.append({"source": "text", "data": {"text": merged_text}})

        if not sources:
            console.print("[red]No valid sources could be built from provided flags.[/red]")
            raise SystemExit(1)

        # -- Call POST /scan ---------------------------------------------------
        source_types = [s["source"] for s in sources]
        console.print()

        phases = []
        for st in source_types:
            phases.extend(_SCAN_PHASES.get(st, []))
        phases.extend(_SCAN_PHASES["reflect"])

        scan_start = time.time()
        response = _scan_with_progress(client, sources, timeout, phases)
        scan_duration = time.time() - scan_start

        console.print(f"  [green]\u2713[/green] Scan complete [dim]({scan_duration:.1f}s)[/dim]\n")

        # -- Display results ---------------------------------------------------
        analyzed_scope = response.get("scope", {})
        risk_profile = response.get("risk_profile", {})

        if user_scope:
            # --scope path: diff, propose, merge.
            additions = _diff_scope(user_scope, analyzed_scope)
            accept = _confirm_scope_additions(additions, auto_yes=yes)
            scope = _merge_scope(
                user_scope, additions if accept else {"permitted": [], "restricted": []}
            )
        else:
            scope = analyzed_scope

        _display_scope(scope)

        sources_meta = response.get("sources_metadata", {})
        if sources_meta:
            failed = [k for k, v in sources_meta.items() if v.get("status") == "failed"]
            if failed:
                console.print(f"\n[yellow]Warning: {', '.join(failed)} source(s) failed[/yellow]")
                for k in failed:
                    err = sources_meta[k].get("error", "unknown")
                    console.print(f"  [dim]{k}: {err}[/dim]")

        # -- Create project (auto-confirm) -------------------------------------
        if not yes:
            from rich.prompt import Confirm

            if not Confirm.ask("\nCreate project with this scope?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        description = f"Project created via 'hb connect' from {_get_source_description(prompt, endpoint, repo, openapi)}"
        with console.status("[dim]Creating project...[/dim]"):
            project_data = {
                "name": name,
                "description": description,
                "scope": scope,
            }

            # When --scope + --endpoint, integration comes from the local load
            # since we deliberately didn't send endpoint as a /scan source.
            default_integration = local_integration or response.get("default_integration")
            if default_integration:
                project_data["default_integration"] = default_integration

            result = client.post("projects", data=project_data)

        project_id = result.get("id")
        client.set_project(project_id)

        console.print()
        console.print(f"  [green bold]Project created: {name}[/green bold]")
        console.print(f"  [dim]{project_id}[/dim]")
        console.print()

        # -- Risk Dashboard ----------------------------------------------------
        has_telemetry = bool(default_integration and default_integration.get("telemetry"))
        _display_dashboard(
            name=name,
            risk_profile=risk_profile,
            has_integration=bool(default_integration),
            has_telemetry=has_telemetry,
        )

        # -- Auto-test ---------------------------------------------------------
        if no_test:
            console.print()
            console.print("[dim]Skipping auto-test (--no-test).[/dim]")
        else:
            _auto_test(
                client,
                project_id,
                default_integration,
                context,
                level,
                test_category=resolved_category,
            )

        # -- Continuous monitoring recommendation ------------------------------
        _recommend_monitoring(risk_profile)

        # -- Next suggestions --------------------------------------------------
        next_suggestions = []
        if no_test:
            if test_category_arg:
                next_suggestions.append(
                    (f"hb test --test-category {test_category_arg}", "Run the first security test")
                )
            else:
                next_suggestions.append(("hb test", "Run the first security test"))
        next_suggestions.extend(
            [
                ("hb findings", "Detailed breakdown"),
                ("hb test --deep", "Deeper analysis"),
                ("hb posture", "View posture score"),
                ("hb report", "Share with team"),
            ]
        )
        _print_next(next_suggestions)

    except NotAuthenticatedError:
        telemetry.fire_gated_command_hit()
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


# -- Agent path (local) --------------------------------------------------------


def _connect_agent_local(endpoint, name, prompt, repo, openapi, context, level, yes, timeout):
    """Local flow: use the user's LLM to derive scope + lightweight compliance.

    Writes ./scope.yaml in the current directory. Does not create a project,
    does not call the Platform. Prints a note after completion pointing at
    `hb login` for regulatory compliance + persistence + team features.
    """
    from ..engine.llm import get_llm_pinger
    from ..engine.local_runner import _resolve_provider
    from ..engine.scope import resolve as resolve_scope

    console.print("\n[dim](not authenticated — running local scope extraction)[/dim]")
    console.print(f"[bold]Connecting agent:[/bold] {name}\n")

    try:
        provider = _resolve_provider()
        llm = get_llm_pinger(provider)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    integration = None
    if endpoint:
        try:
            integration = _load_integration(endpoint)
            chat_ep = integration.get("chat_completion", {}).get("endpoint", "")
            console.print(
                f"  [green]✓[/green] Endpoint source: [dim]{chat_ep or '(from config)'}[/dim]"
            )
        except Exception as e:
            console.print(f"  [yellow]![/yellow] Endpoint could not be loaded: {e}")

    if repo:
        console.print(f"  [green]✓[/green] Scanning repository: [dim]{repo}[/dim]")
    if prompt:
        console.print(f"  [green]✓[/green] Loading prompt: [dim]{Path(prompt).name}[/dim]")
    if openapi:
        console.print(f"  [green]✓[/green] Parsing OpenAPI: [dim]{Path(openapi).name}[/dim]")

    console.print()

    with console.status("[dim]Extracting scope via local LLM...[/dim]"):
        try:
            scope = resolve_scope(
                repo_path=repo,
                prompt_path=prompt,
                scope_path=None,
                integration=integration,
                llm_pinger=llm,
            )
        except Exception as e:
            console.print(f"[red]Scope extraction failed:[/red] {e}")
            raise SystemExit(1)

    # Lightweight compliance overlay — detect domain, apply template + EU AI Act
    from ..engine.compliance import (
        apply_eu_ai_act_only,
        apply_template,
        detect_domain,
        domain_label,
    )

    domain = detect_domain(scope)
    if domain:
        console.print(f"  [green]✓[/green] Detected domain: [bold]{domain_label(domain)}[/bold]")
        scope = apply_template(scope, domain, include_eu_ai_act=True)
        console.print(
            "  [green]✓[/green] Applied compliance overlay ([dim]domain template + EU AI Act[/dim])"
        )
    else:
        scope = apply_eu_ai_act_only(scope)
        console.print(
            "  [dim]No domain-specific template matched — EU AI Act overlay applied.[/dim]"
        )

    console.print()
    _display_scope(scope)

    output_path = Path.cwd() / "scope.yaml"
    try:
        _write_scope_yaml(scope, output_path)
        console.print(f"\n  [green]✓[/green] Wrote [bold]{output_path.name}[/bold]")
    except Exception as e:
        console.print(f"\n  [yellow]Could not write scope.yaml:[/yellow] {e}")

    _print_platform_note()

    _print_next(
        [
            (f"hb test --scope {output_path.name}", "Run a security test with this scope"),
            ("hb login", "Sign in for regulatory compliance + team features"),
        ]
    )


def _load_scope_file(path: str) -> dict:
    """Parse + validate a user-supplied scope YAML/JSON file.

    Returns a dict with keys: business_scope, permitted, restricted, more_info.
    Raises FileNotFoundError if missing, ValueError with a message naming the
    offending key on shape violations.
    """
    import yaml

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"--scope file not found: {path}")

    raw = file_path.read_text()
    ext = file_path.suffix.lower()
    try:
        if ext == ".json":
            data = json.loads(raw)
        elif ext in (".yaml", ".yml"):
            data = yaml.safe_load(raw)
        else:
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError:
                data = json.loads(raw)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ValueError(f"--scope: could not parse {path}: {e}")

    if not isinstance(data, dict):
        raise ValueError(f"--scope: top-level must be a mapping; got {type(data).__name__}")

    business_scope = data.get("business_scope")
    if not isinstance(business_scope, str) or not business_scope.strip():
        raise ValueError("--scope: 'business_scope' must be a non-empty string")

    permitted = data.get("permitted")
    if not isinstance(permitted, list) or not permitted:
        raise ValueError("--scope: 'permitted' must be a non-empty list")
    if not all(isinstance(p, str) and p.strip() for p in permitted):
        raise ValueError("--scope: 'permitted' must contain non-empty strings")

    restricted = data.get("restricted")
    if not isinstance(restricted, list) or not restricted:
        raise ValueError("--scope: 'restricted' must be a non-empty list")
    if not all(isinstance(r, str) and r.strip() for r in restricted):
        raise ValueError("--scope: 'restricted' must contain non-empty strings")

    more_info = data.get("more_info", "")
    if more_info is None:
        more_info = ""
    if not isinstance(more_info, str):
        raise ValueError("--scope: 'more_info' must be a string when present")

    return {
        "business_scope": business_scope,
        "permitted": permitted,
        "restricted": restricted,
        "more_info": more_info,
    }


def _serialize_scope_to_text(scope: dict) -> str:
    """Render a parsed scope dict into the text blob sent as a /scan 'text' source."""
    lines = [f"Business scope: {scope['business_scope']}", ""]
    lines.append("Permitted intents:")
    for p in scope["permitted"]:
        lines.append(f"- {p}")
    lines.append("")
    lines.append("Restricted intents:")
    for r in scope["restricted"]:
        lines.append(f"- {r}")
    more_info = scope.get("more_info", "").strip()
    if more_info:
        lines.append("")
        lines.append(f"Additional context: {more_info}")
    return "\n".join(lines)


def _diff_scope(user_scope: dict, analyzed_scope: dict) -> dict:
    """Return additive proposals — items in analyzed but not in user.

    Comparison is case-insensitive after trimming whitespace.
    Never proposes removals; user's intents are always preserved.
    """

    def _norm(s: str) -> str:
        return s.strip().lower()

    user_permitted_norm = {_norm(p) for p in user_scope.get("permitted", [])}
    user_restricted_norm = {_norm(r) for r in user_scope.get("restricted", [])}

    intents = analyzed_scope.get("intents", {}) if isinstance(analyzed_scope, dict) else {}
    analyzed_permitted = intents.get("permitted", []) or []
    analyzed_restricted = intents.get("restricted", []) or []

    return {
        "permitted": [p for p in analyzed_permitted if _norm(p) not in user_permitted_norm],
        "restricted": [r for r in analyzed_restricted if _norm(r) not in user_restricted_norm],
    }


def _merge_scope(user_scope: dict, additions: dict) -> dict:
    """Return a scope dict in /scan response shape, merging accepted additions."""
    return {
        "overall_business_scope": user_scope["business_scope"],
        "intents": {
            "permitted": list(user_scope["permitted"]) + list(additions.get("permitted", [])),
            "restricted": list(user_scope["restricted"]) + list(additions.get("restricted", [])),
        },
        "more_info": user_scope.get("more_info", ""),
    }


def _confirm_scope_additions(additions: dict, auto_yes: bool) -> bool:
    """Render the proposal panel and prompt for Y/N. Returns True to accept additions."""
    permitted = additions.get("permitted", [])
    restricted = additions.get("restricted", [])

    if not permitted and not restricted:
        console.print()
        console.print("[dim]Your scope looks complete — no additions proposed.[/dim]")
        return False

    parts = ["We analysed your scope and noticed these additional intents:", ""]
    if permitted:
        parts.append("[bold green]Permitted (proposed):[/bold green]")
        for p in permitted:
            parts.append(f"  [green]+[/green] {p}")
    if restricted:
        if permitted:
            parts.append("")
        parts.append("[bold red]Restricted (proposed):[/bold red]")
        for r in restricted:
            parts.append(f"  [red]+[/red] {r}")

    console.print()
    console.print(
        Panel(
            "\n".join(parts),
            title="Scope analysis",
            border_style="blue",
        )
    )

    if auto_yes:
        return True

    from rich.prompt import Confirm

    return Confirm.ask("\nAccept these additions?", default=True)


def _write_scope_yaml(scope: dict, path: Path):
    """Serialize scope dict to a .yaml file in the canonical template shape."""
    try:
        import yaml
    except ImportError:
        path.write_text(json.dumps(scope, indent=2))
        return

    intents = scope.get("intents", {})
    document = {
        "business_scope": scope.get("overall_business_scope", ""),
        "permitted": intents.get("permitted", []),
        "restricted": intents.get("restricted", []),
        "more_info": scope.get("more_info", ""),
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False, default_flow_style=False))


def _print_platform_note():
    """Note shown after local scope extraction summarising the Platform features.

    Kept factual and community-neutral — this is an OSS CLI, not a sales page.
    """
    lines = [
        "Scope & policies saved locally.",
        "",
        "Regulatory mapping (FCA, EU AI Act, HIPAA, IDD, CRA 2015), threat",
        "prioritisation with citations, and persistent project history are",
        "available when signed in with [bold]hb login[/bold].",
    ]
    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Local result[/bold]",
            border_style="cyan",
        )
    )


# -- Monitoring recommendation -------------------------------------------------

# Regulations that require or strongly recommend continuous AI monitoring
_CONTINUOUS_MONITORING_REGS = {
    "DORA": "Art. 25 — continuous ICT testing including AI services",
    "PCI-DSS": "Req. 11.3 — continuous monitoring and periodic pen testing",
    "HIPAA": "§164.308 — ongoing risk analysis and security management",
    "SOX": "§404 — continuous assessment of internal controls",
    "NIST AI RMF": "MEASURE — ongoing monitoring of AI system performance",
    "EU AI ACT": "Art. 72 — post-market monitoring for high-risk AI",
}


def _recommend_monitoring(risk_profile: dict):
    """Show continuous monitoring recommendation based on risk level and regulations."""
    risk_level = risk_profile.get("risk_level", "LOW")
    regulations = [r.upper() for r in risk_profile.get("applicable_regulations", [])]

    # Find matching compliance requirements
    matching = []
    for reg in regulations:
        for key, description in _CONTINUOUS_MONITORING_REGS.items():
            if key.upper().replace(" ", "") in reg.replace(" ", "").replace("-", ""):
                matching.append((key, description))

    if risk_level in ("HIGH", "MEDIUM") or matching:
        console.print()
        console.print(
            Panel(
                _build_monitoring_message(risk_level, matching),
                title="[bold]Continuous Monitoring[/bold]",
                border_style="yellow" if risk_level == "HIGH" else "blue",
                padding=(1, 2),
            )
        )


def _build_monitoring_message(risk_level: str, matching_regs: list) -> str:
    lines = []
    if risk_level == "HIGH":
        lines.append("[yellow bold]Your agent operates in a high-risk domain.[/yellow bold]")
    else:
        lines.append("[blue]Continuous monitoring is recommended for this agent.[/blue]")

    if matching_regs:
        lines.append("")
        lines.append("[dim]Applicable compliance requirements:[/dim]")
        for reg, desc in matching_regs:
            lines.append(f"  [cyan]{reg}[/cyan]  [dim]{desc}[/dim]")

    lines.append("")
    lines.append("Enable daily automated security testing:")
    lines.append("  [bold green]hb monitor --resume[/bold green]")
    lines.append("")
    lines.append(
        "[dim]Track assessments at:[/dim]  [underline]https://app.humanbound.ai[/underline]"
    )

    return "\n".join(lines)


# -- Auto-test helper ----------------------------------------------------------


def _auto_test(
    client,
    project_id,
    default_integration,
    context=None,
    level="unit",
    test_category=DEFAULT_TEST_CATEGORY,
):
    """Run first test automatically and show results inline."""
    if not default_integration:
        console.print("\n[dim]No agent integration configured -- skipping auto-test.[/dim]")
        console.print("[dim]Run 'hb test -e ./bot-config.json' to test manually.[/dim]")
        return

    exp_id = None

    try:
        # Find provider
        with console.status("[dim]Finding provider...[/dim]"):
            providers = client.list_providers()

        if not providers:
            console.print("\n[yellow]No providers configured -- skipping auto-test.[/yellow]")
            console.print("[dim]Run 'hb providers add' then 'hb test' to test manually.[/dim]")
            return

        provider = next((p for p in providers if p.get("is_default")), providers[0])
        provider_id = provider.get("id")

        console.print("\n[dim]Running first security test...[/dim]")

        # Build configuration with integration + optional context
        configuration = {"integration": default_integration}
        if context:
            ctx_value = _resolve_context(context)
            if len(ctx_value) > 1500:
                console.print(
                    f"[red]Context too long ({len(ctx_value)} chars). Maximum is 1,500.[/red]"
                )
                raise SystemExit(1)
            configuration["context"] = ctx_value

        # Create experiment with auto_start
        experiment_data = {
            "name": f"connect-{time.strftime('%Y%m%d-%H%M%S')}",
            "description": "Initial assessment from hb connect",
            "test_category": test_category,
            "testing_level": level,
            "provider_id": provider_id,
            "auto_start": True,
            "configuration": configuration,
        }

        with console.status("[dim]Creating experiment...[/dim]"):
            response = client.post("experiments", data=experiment_data, include_project=True)

        exp_id = response.get("id")
        if not exp_id:
            console.print("[yellow]Could not start test.[/yellow]")
            return

        import random

        _chill_messages = [
            "☕ Go grab a coffee — we've got it from here. Email incoming when done.",
            "🍺 Red team deployed — treat yourself to a beer, email coming soon.",
            "🌿 Our agents are on it — go touch grass, we'll email you the results.",
            "🥊 The bots are fighting — grab a snack and check your inbox later.",
            "🔓 Hacking in progress — no really, go do something fun. Email on the way.",
            "🚀 We're poking your agent now — go stretch, results hit your inbox shortly.",
            "🧘 Time for a break — we'll ping you by email once we're through.",
            "🎯 Sit back and relax — we'll email you when results are ready.",
        ]
        console.print(f"  [green]\u2713[/green] Test started: [dim]{exp_id}[/dim]")
        console.print()
        console.print(f"  {random.choice(_chill_messages)}")
        console.print()
        console.print("  [dim]Watch progress:[/dim]  hb projects status -w")
        console.print(f"  [dim]Experiment:[/dim]      hb status {exp_id} -w")
        console.print(f"  [dim]View logs:[/dim]       hb logs {exp_id}")

    except Exception as e:
        import traceback

        console.print(f"\n[yellow]Auto-test failed:[/yellow] {e}")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        console.print("[dim]Run 'hb test' to try again.[/dim]")
