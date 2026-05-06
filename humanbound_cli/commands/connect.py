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

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError
from .test import _load_integration, _resolve_context

console = Console()

SCAN_TIMEOUT = 180

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
@click.option("--endpoint", "-e", help="Agent config JSON or file path (agent path)")
@click.option(
    "--vendor",
    "-v",
    type=click.Choice(["microsoft"]),
    help="Cloud vendor to scan (platform path)",
)
@click.option("--name", "-n", help="Project name (optional, auto-generated)")
@click.option(
    "--prompt", "-p", type=click.Path(exists=True), help="System prompt file (agent path)"
)
@click.option("--repo", "-r", type=click.Path(exists=True), help="Repository path (agent path)")
@click.option(
    "--openapi", "-o", type=click.Path(exists=True), help="OpenAPI spec file (agent path)"
)
@click.option("--tenant", help="Azure tenant ID (platform path, bypasses browser)")
@click.option("--client-id", "client_id", help="Service principal client ID (platform path)")
@click.option("--client-secret", "client_secret", help="Service principal secret (platform path)")
@click.option(
    "--context",
    "-c",
    help="Extra context for the judge (e.g. 'Authenticated as Alice, her PII is expected'). String or path to .txt file.",
)
@click.option(
    "--level",
    "-l",
    type=click.Choice(["unit", "system", "acceptance"]),
    default=None,
    help="Testing depth: unit (quick), system (deep), acceptance (full). "
    "If omitted, the backend applies its default.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmations")
@click.option("--timeout", "-t", type=int, default=SCAN_TIMEOUT, help="Request timeout in seconds")
def connect_command(
    endpoint,
    vendor,
    name,
    prompt,
    repo,
    openapi,
    tenant,
    client_id,
    client_secret,
    context,
    level,
    yes,
    timeout,
):
    """Connect your AI agent or scan your cloud platform.

    Two paths, one command:

    \b
    Agent path (--endpoint):
      hb connect --endpoint ./bot-config.json
      Probes your agent, extracts scope, creates project, runs first test.

    \b
    Platform path (--vendor):
      hb connect --vendor microsoft
      Scans cloud for shadow AI, evaluates 39 signals, saves to inventory.

    \b
    Examples:
      hb connect --endpoint ./config.json
      hb connect --endpoint ./config.json --prompt ./system.txt
      hb connect --vendor microsoft
      hb connect --vendor microsoft --tenant abc-123 --client-id x --client-secret y
    """
    has_agent_flags = any([endpoint, prompt, repo, openapi])
    has_platform_flags = any([vendor, tenant, client_id, client_secret])

    if has_agent_flags and has_platform_flags:
        console.print(
            "[red]Cannot combine agent flags (--endpoint/--prompt/--repo/--openapi) with platform flags (--vendor/--tenant).[/red]"
        )
        raise SystemExit(1)

    if has_platform_flags:
        _connect_platform(vendor, name, tenant, client_id, client_secret, yes, timeout)
    elif has_agent_flags:
        _connect_agent(endpoint, name, prompt, repo, openapi, context, level, yes, timeout)
    else:
        console.print("[yellow]Specify a path:[/yellow]")
        console.print()
        console.print("  [bold]Agent:[/bold]      hb connect --endpoint ./bot-config.json")
        console.print("  [bold]Platform:[/bold]  hb connect --vendor microsoft")
        console.print()
        console.print(
            "[dim]Use --endpoint to connect your AI agent, or --vendor to scan your cloud.[/dim]"
        )
        raise SystemExit(1)


# -- Agent path ----------------------------------------------------------------


def _connect_agent(endpoint, name, prompt, repo, openapi, context, level, yes, timeout):
    """Agent path: dispatch to Platform flow (authenticated) or local flow (anonymous).

    Platform flow creates a project on humanbound.ai with full scope, risk profile,
    regulatory mapping, and auto-test. Local flow derives scope + lightweight
    compliance from the user's configured LLM provider and writes scope.yaml.
    """
    source_flags = [prompt, endpoint, repo, openapi]
    if not any(source_flags):
        console.print("[yellow]No extraction source provided.[/yellow]")
        console.print("Use --endpoint, --prompt, --repo, or --openapi to specify a source.")
        raise SystemExit(1)

    if not name:
        name = _derive_agent_name(endpoint) if endpoint else "local-agent"

    client = HumanboundClient()
    if client.is_authenticated() and client.organisation_id:
        _connect_agent_platform(
            client, endpoint, name, prompt, repo, openapi, context, level, yes, timeout
        )
    else:
        _connect_agent_local(endpoint, name, prompt, repo, openapi, context, level, yes, timeout)


def _connect_agent_platform(
    client, endpoint, name, prompt, repo, openapi, context, level, yes, timeout
):
    """Platform flow: POST /scan -> create project -> auto-test -> dashboard."""
    console.print(f"\n[bold]Connecting agent:[/bold] {name}\n")

    try:
        # -- Build sources array for POST /scan --------------------------------
        sources = []
        text_parts = []
        runtime_info = None

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
                console.print(f"  [green]\u2713[/green] OpenAPI spec: {len(operations)} operations")
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
        scope = response.get("scope", {})
        risk_profile = response.get("risk_profile", {})

        _display_scope(scope)

        # ---- capability scan (additive; per spec §6.1) ----
        if repo:
            from ..extractors.capabilities import scan_capabilities
            from ..extractors.capabilities.display import (
                print_detected_capabilities,
                prompt_empty_scan_choice,
            )

            scan_result = scan_capabilities(Path(repo))
            print_detected_capabilities(scan_result, console)

            if any(scan_result.capabilities.values()):
                scope["capabilities"] = scan_result.capabilities
            else:
                if yes:
                    pass
                else:
                    explicit = prompt_empty_scan_choice(console=console)
                    if explicit is not None:
                        scope["capabilities"] = explicit

        sources_meta = response.get("sources_metadata", {})
        if sources_meta:
            failed = [k for k, v in sources_meta.items() if v.get("status") == "failed"]
            if failed:
                console.print(f"\n[yellow]Warning: {', '.join(failed)} source(s) failed[/yellow]")
                for k in failed:
                    err = sources_meta[k].get("error", "unknown")
                    console.print(f"  [dim]{k}: {err}[/dim]")

        # -- If an active project already exists AND a repo scan was run,
        #    route updates through write_capabilities instead of creating a new project --
        existing_project_id = getattr(client, "project_id", None)
        if existing_project_id and repo:
            if "capabilities" in scope:
                from ..engine.capabilities_writer import write_capabilities

                console.print()
                write_capabilities(
                    client,
                    existing_project_id,
                    scope["capabilities"],
                    yes=yes,
                    console=console,
                )
            else:
                console.print("[dim]No capabilities to update for existing project.[/dim]")
            return

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

            default_integration = response.get("default_integration")
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
        _auto_test(client, project_id, default_integration, context, level)

        # -- Continuous monitoring recommendation ------------------------------
        _recommend_monitoring(risk_profile)

        # -- Next suggestions --------------------------------------------------
        _print_next(
            [
                ("hb findings", "Detailed breakdown"),
                ("hb test --deep", "Deeper analysis"),
                ("hb posture", "View posture score"),
                ("hb report", "Share with team"),
            ]
        )

    except NotAuthenticatedError:
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

    # ---- capability scan (additive; per spec §6.1) ----
    if repo:
        from ..extractors.capabilities import scan_capabilities
        from ..extractors.capabilities.display import (
            print_detected_capabilities,
            prompt_empty_scan_choice,
        )

        scan_result = scan_capabilities(Path(repo))
        print_detected_capabilities(scan_result, console)

        if any(scan_result.capabilities.values()):
            scope["capabilities"] = scan_result.capabilities
        else:
            if yes:
                # --yes accepts the default [1]: leave capabilities unset
                pass
            else:
                explicit = prompt_empty_scan_choice(console=console)
                if explicit is not None:
                    scope["capabilities"] = explicit

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
    if "capabilities" in scope:
        document["capabilities"] = scope["capabilities"]
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


# -- Platform path -------------------------------------------------------------


def _connect_platform(vendor, name, tenant, client_id, client_secret, yes, timeout):
    """Platform path: scan -> assess -> auto-save -> show posture."""
    from .discover import (
        _display_auth_error,
        _display_device_code,
        _display_evaluations,
        _display_persist_summary,
        _display_results,
        _get_connector,
    )

    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    # Default vendor
    if not vendor:
        if any([tenant, client_id, client_secret]):
            vendor = "microsoft"
        else:
            console.print("[red]--vendor is required for platform path.[/red]")
            console.print("[dim]Example: hb connect --vendor microsoft[/dim]")
            raise SystemExit(1)

    # Validate service principal flags (all-or-none)
    sp_flags = [tenant, client_id, client_secret]
    if any(sp_flags) and not all(sp_flags):
        console.print(
            "[red]Service principal auth requires all three: --tenant, --client-id, --client-secret[/red]"
        )
        raise SystemExit(1)

    console.print()
    console.print(
        Panel(
            "[bold]AI Service Discovery[/bold]\n\n"
            f"Vendor:  [bold]{vendor}[/bold]\n"
            "Mode:    [bold]connect[/bold] (scan + assess + save)\n\n"
            "This will:\n"
            "  1. Sign in to your cloud tenant\n"
            "  2. Scan for AI services [dim](read-only)[/dim]\n"
            "  3. Assess against 38 security signals\n"
            "  4. Save results to your AI inventory",
            border_style="blue",
        )
    )
    console.print()

    if not yes:
        if not click.confirm("Proceed with discovery?", default=True):
            console.print("[dim]Cancelled.[/dim]")
            return

    console.print()

    try:
        # -- Authenticate ------------------------------------------------------
        connector = _get_connector(vendor, verbose=False)

        if all(sp_flags):
            # Service principal auth (non-interactive)
            console.print("[dim]Authenticating with service principal...[/dim]")
            try:
                connector.authenticate_sp(
                    tenant_id=tenant,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            except AttributeError:
                console.print(
                    "[yellow]Service principal auth not yet supported for this vendor.[/yellow]"
                )
                console.print("[dim]Use browser auth instead: hb connect --vendor microsoft[/dim]")
                raise SystemExit(1)
            except PermissionError as e:
                console.print(f"[red]Authentication failed:[/red] {e}")
                raise SystemExit(1)
            console.print("[green]Authenticated via service principal.[/green]\n")
        else:
            # Browser device-code flow
            try:
                connector.authenticate(callback=_display_device_code)
            except PermissionError as e:
                _display_auth_error(str(e))
                raise SystemExit(1)
            console.print("[green]Signed in successfully.[/green]\n")

        # -- Scan --------------------------------------------------------------
        with console.status("[bold blue]Scanning for AI services..."):
            services, metadata = connector.discover()

        if not services:
            status = metadata.get("status", "unknown")
            if status == "failed":
                console.print("[red]Discovery failed.[/red] Could not query any APIs.")
            else:
                console.print("[yellow]No AI services found.[/yellow]")
            return

        console.print(f"Found [bold]{len(services)}[/bold] AI services. Analysing...\n")

        # -- Analyse -----------------------------------------------------------
        org_id = client.organisation_id
        payload = {
            "vendor": vendor,
            "services": services,
            "sources_metadata": {
                "status": metadata.get("status", "unknown"),
                "apis_queried": metadata.get("apis_queried", []),
                "apis_failed": metadata.get("apis_failed", []),
                "permissions_missing": metadata.get("permissions_missing", []),
            },
            "topology": metadata.get("topology", {}),
        }

        with console.status("[bold blue]Analysing discovered services..."):
            analysis = client.post(
                f"organisations/{org_id}/analyse",
                data=payload,
                include_org=False,
                timeout=timeout,
            )

        # -- Overlay evaluator risk onto services for consistent display -------
        evals = analysis.get("evaluations", [])
        if evals:
            eval_risk_map = {
                ev["service_name"]: ev["risk_level"]
                for ev in evals
                if "service_name" in ev and "risk_level" in ev
            }
            for svc in analysis.get("services", []):
                eval_rl = eval_risk_map.get(svc.get("name"))
                if eval_rl:
                    svc["risk"] = eval_rl

            new_by_risk = {}
            for svc in analysis.get("services", []):
                r = svc.get("risk", "unknown")
                new_by_risk[r] = new_by_risk.get(r, 0) + 1
            if "summary" in analysis:
                analysis["summary"]["by_risk"] = new_by_risk

        # -- Display -----------------------------------------------------------
        _display_results(analysis, metadata)

        evaluations = analysis.get("evaluations", [])
        posture_estimate = analysis.get("posture_estimate")
        if evaluations:
            _display_evaluations(evaluations, posture_estimate)

        # -- Auto-save (always persist in connect mode) ------------------------
        nonce = analysis.get("nonce")
        if nonce:
            with console.status("[bold blue]Saving to inventory..."):
                persist_result = client.persist_discovery(nonce)
            _display_persist_summary(persist_result)
        else:
            console.print(
                "\n[yellow]Cannot persist:[/yellow] server did not return a session token."
            )

        # -- Next suggestions --------------------------------------------------
        _print_next(
            [
                ("hb inventory", "Browse all assets"),
                ("hb posture --org", "Full org posture (3 dimensions)"),
                ("hb report --org", "Org-wide report"),
                ("hb discover --report", "Export HTML report"),
            ]
        )

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


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


def _auto_test(client, project_id, default_integration, context=None, level=None):
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

        # Create experiment with auto_start. test_category is intentionally
        # omitted so the backend applies its default; testing_level is only
        # included when the caller specified one.
        experiment_data = {
            "name": f"connect-{time.strftime('%Y%m%d-%H%M%S')}",
            "description": "Initial assessment from hb connect",
            "provider_id": provider_id,
            "auto_start": True,
            "configuration": configuration,
        }
        if level:
            experiment_data["testing_level"] = level

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
