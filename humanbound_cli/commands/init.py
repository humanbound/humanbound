"""Project initialization commands — thin client for POST /scan.

DEPRECATED: 'hb init' is deprecated in favour of 'hb connect --endpoint'.
This module is kept for backward compatibility. Remove after v2.0.
"""

import click
import time
import random
import threading
import warnings
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm
from pathlib import Path
import json

from ..client import HumanboundClient
from ..config import LONG_TIMEOUT
from ..exceptions import NotAuthenticatedError, APIError, ServeError, TunnelError

SCAN_TIMEOUT = 180

console = Console()

# DEPRECATED: remove after v2.0 — replaced by 'hb connect --endpoint'
_DEPRECATION_MSG = (
    "[yellow]Warning:[/yellow] 'hb init' is deprecated. "
    "Use [bold]hb connect --endpoint[/bold] instead."
)

# Phase headers shown during scan (based on source types)
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

# Playful sub-messages that rotate below the phase header
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


@click.command("init")
@click.option("--name", "-n", required=True, help="Project name")
@click.option("--prompt", "-p", type=click.Path(exists=True), help="Path to system prompt file (maps to 'text' source)")
@click.option("--endpoint", "-e", help="Bot integration config — JSON string or path to JSON file (maps to 'endpoint' source). Same shape as experiment configuration.integration: {streaming, thread_auth, thread_init, chat_completion}")
@click.option("--repo", "-r", type=click.Path(exists=True), help="Path to repository to scan (maps to 'agentic' or 'text' source)")
@click.option("--openapi", "-o", type=click.Path(exists=True), help="Path to OpenAPI spec file (maps to 'text' source)")
@click.option("--serve", "-s", is_flag=True, help="Launch repo bot locally and probe live (requires --repo)")
@click.option("--description", "-d", help="Project description")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm project creation and set as current project (no interactive prompts)")
@click.option("--timeout", "-t", type=int, default=SCAN_TIMEOUT, show_default=True, help="Scan request timeout in seconds")
def init_project(name: str, prompt: str, endpoint: str, repo: str, openapi: str, serve: bool, description: str, yes: bool, timeout: int):
    """Initialize a new project with automatic scope extraction.

    DEPRECATED: Use 'hb connect --endpoint' instead. This command will be
    removed in a future version.

    Calls POST /scan with one or more sources, displays the extracted scope
    and risk profile, then creates the project.

    \b
    Sources (at least one required):
      --prompt, -p     System prompt file         -> 'text' source
      --endpoint, -e   Bot API config (JSON/file) -> 'endpoint' source (API probing)
      --repo, -r       Repository path            -> 'agentic' or 'text' source
      --openapi, -o    OpenAPI spec file           -> 'text' source

    \b
    Live probing:
      --serve, -s      Launch the bot from --repo, tunnel it, and probe live.
                       Combines static analysis (agentic source) with live
                       endpoint probing for the richest scope extraction.

    The --endpoint flag accepts the same JSON shape as experiment
    configuration.integration (inline or file path):

    \b
    {
      "streaming": false,
      "thread_auth": {"endpoint": "", "headers": {}, "payload": {}},
      "thread_init": {"endpoint": "...", "headers": {...}, "payload": {}},
      "chat_completion": {"endpoint": "...", "headers": {...}, "payload": {"content": "$PROMPT"}}
    }

    Examples:

    \b
    hb init -n "My Bot" --prompt ./system_prompt.txt
    hb init -n "My Bot" --endpoint ./bot-config.json
    hb init -n "My Bot" --repo ./my-bot --serve
    hb init -n "My Bot" --prompt ./system.txt --endpoint ./bot-config.json
    hb init -n "My Bot" --endpoint ./config.json -y
    """
    # DEPRECATED: remove after v2.0
    console.print(_DEPRECATION_MSG)
    console.print()

    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    # Validate --serve requires --repo
    if serve and not repo:
        console.print("[red]--serve requires --repo.[/red] Provide a repository path.")
        raise SystemExit(1)

    # Count extraction sources
    source_flags = [prompt, endpoint, repo, openapi]
    if not any(source_flags):
        console.print("[yellow]No extraction source provided.[/yellow]")
        console.print("Use --prompt, --endpoint, --repo, or --openapi to specify a source.")
        raise SystemExit(1)

    console.print(f"\n[bold]Initializing project:[/bold] {name}\n")

    # Track serve resources for cleanup
    _server = None
    _tunnel = None

    try:
        # -- Build sources array for POST /scan --------------------------------
        sources = []
        text_parts = []  # accumulate text sources to merge
        runtime_info = None  # populated if a runnable bot is detected

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
                    console.print(f"  [green]\u2713[/green] Repository: {len(files)} files, {len(scan_result['tools'])} tools (source: agentic)")
                    sources.append({
                        "source": "agentic",
                        "data": {
                            "system_prompt": scan_result.get("system_prompt", ""),
                            "tools": scan_result.get("tools", []),
                        }
                    })
                else:
                    console.print(f"  [green]\u2713[/green] Repository: {len(files)} files")
                    combined = scan_result.get("system_prompt", "")
                    if scan_result.get("readme"):
                        combined += f"\n\nREADME:\n{scan_result['readme']}"
                    if combined.strip():
                        text_parts.append(combined)
            else:
                console.print(f"  [yellow]![/yellow] Repository: no relevant files found")

            # -- Runtime detection (for --serve or interactive prompt) ----------
            runtime_info = _detect_runtime(repo)

            if runtime_info and not serve and not endpoint and not yes:
                # Interactive: offer to launch for live probing
                console.print()
                console.print(f"  [cyan]i[/cyan] Detected runnable bot: [bold]{runtime_info.framework.title()}[/bold] ({runtime_info.entry_point})")
                console.print(f"    Start command: [dim]{runtime_info.start_cmd.replace('{port}', str(runtime_info.port))}[/dim]")
                if Confirm.ask("    Launch it for live probing?", default=False):
                    serve = True

        # --openapi -> text source
        if openapi:
            from ..extractors.openapi import OpenAPIParser

            parser = OpenAPIParser(openapi)
            with console.status("[dim]Parsing specification...[/dim]"):
                spec_result = parser.parse()

            if spec_result:
                operations = spec_result.get("operations", [])
                console.print(f"  [green]\u2713[/green] OpenAPI spec: {len(operations)} operations")

                summary_parts = [spec_result.get("description", "API-based bot")]
                for op in operations:
                    summary_parts.append(
                        f"- {op.get('method', 'GET')} {op.get('path', '')}: {op.get('summary', '')}"
                    )
                text_parts.append("\n".join(summary_parts))
            else:
                console.print(f"  [yellow]![/yellow] OpenAPI spec: could not parse")

        # --endpoint -> endpoint source (API probing)
        if endpoint:
            bot_config = _load_integration(endpoint)
            chat_ep = bot_config.get("chat_completion", {}).get("endpoint", "")
            console.print(f"  [green]\u2713[/green] Endpoint source: [dim]{chat_ep or '(from config)'}[/dim]")
            sources.append({"source": "endpoint", "data": bot_config})

        # -- Serve lifecycle: start server + tunnel ----------------------------
        if serve and repo:
            if not runtime_info:
                console.print("[yellow]Could not detect a runnable bot in the repository.[/yellow]")
                console.print("[dim]Continuing with static analysis only.[/dim]")
            else:
                _server, _tunnel, serve_source = _start_serve(
                    client, repo, runtime_info, yes
                )
                if serve_source:
                    sources.append(serve_source)

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

        # Build rotating status messages based on source types
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
        capabilities = response.get("capabilities", {})

        _display_scope(scope)

        # Show sources metadata warnings
        sources_meta = response.get("sources_metadata", {})
        if sources_meta:
            failed = [k for k, v in sources_meta.items() if v.get("status") == "failed"]
            if failed:
                console.print(f"\n[yellow]Warning: {', '.join(failed)} source(s) failed[/yellow]")
                for k in failed:
                    err = sources_meta[k].get("error", "unknown")
                    console.print(f"  [dim]{k}: {err}[/dim]")

        # -- Confirm and create project ----------------------------------------
        if not yes:
            if not Confirm.ask("\nCreate project with this scope?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        with console.status("[dim]Creating project...[/dim]"):
            project_data = {
                "name": name,
                "description": description or f"Project created via CLI from {_get_source_description(prompt, endpoint, repo, openapi)}",
                "scope": scope,
            }

            default_integration = response.get("default_integration")
            if default_integration:
                project_data["default_integration"] = default_integration

            result = client.post("projects", data=project_data)

        project_id = result.get("id")
        console.print(f"  [green]\u2713[/green] Project created: [bold]{name}[/bold] [dim]({project_id})[/dim]")

        # Auto-select the project
        client.set_project(project_id)
        console.print(f"  [green]\u2713[/green] Set as current project")

        # -- Risk Dashboard (compact single panel) -----------------------------
        _display_dashboard(
            name=name,
            risk_profile=risk_profile,
            capabilities=capabilities,
            recommendations=response.get("recommendations", []),
            has_integration=bool(default_integration),
        )

        # -- Next steps --------------------------------------------------------
        if yes:
            return

        console.print("\n[bold]What's next?[/bold]\n")
        console.print("  [bold]1.[/bold] [green]Quick reconnaissance[/green] [dim](recommended)[/dim]")
        console.print("      Run a quick adversarial test to get an initial posture score.\n")
        console.print("  [bold]2.[/bold] Full discovery")
        console.print("      Launch the full ASCAM discovery phase — deeper reconnaissance + campaign.\n")
        console.print("  [bold]3.[/bold] Done for now")
        console.print("      Come back anytime with [bold]hb test[/bold].\n")

        choice = click.prompt("Choose", type=click.Choice(["1", "2", "3"]), default="3")

        if choice == "1":
            _run_quick_scan(client, project_id, default_integration)
        elif choice == "2":
            _start_discovery(client, project_id)
        else:
            console.print(f"\n[dim]Run 'hb test' when you're ready.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    finally:
        # Clean up serve resources
        _cleanup_serve(_tunnel, _server)


# -- Scan with rotating progress -----------------------------------------------


def _scan_with_progress(client: HumanboundClient, sources: list, timeout: int, phases: list):
    """Run POST /scan with rotating status messages (Claude-style)."""
    result = {}
    error = None

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

    # Shuffle playful messages for variety
    playful = _PLAYFUL_MESSAGES.copy()
    random.shuffle(playful)

    phase_idx = 0
    playful_idx = 0
    rotate_interval = 4  # seconds between message rotation

    with console.status("") as status:
        while thread.is_alive():
            elapsed = time.time() - scan_start
            elapsed_str = f"{elapsed:.0f}s"
            phase = phases[phase_idx % len(phases)] if phases else "Scanning..."
            fun = playful[playful_idx % len(playful)]
            status.update(
                f"[bold]{phase}[/bold] [dim]({elapsed_str})[/dim]\n"
                f"  [dim italic]{fun}[/dim italic]"
            )
            thread.join(timeout=rotate_interval)
            playful_idx += 1
            # Advance phase every 2 rotations (~8s)
            if playful_idx % 2 == 0:
                phase_idx += 1

    if error:
        raise error

    return result


# -- Post-creation actions ------------------------------------------------------


def _run_quick_scan(client: HumanboundClient, project_id: str, default_integration: dict = None):
    """Create and start a unit-level owasp_multi_turn experiment."""
    console.print()

    if not default_integration:
        console.print("[yellow]No bot integration configured on this project.[/yellow]")
        console.print("[dim]Run 'hb test -e ./bot-config.json' to test manually.[/dim]")
        return

    try:
        # Find a provider
        with console.status("[dim]Finding provider...[/dim]"):
            providers = client.get("providers")

        if not providers or (isinstance(providers, list) and len(providers) == 0):
            console.print("[yellow]No providers configured.[/yellow]")
            console.print("[dim]Run 'hb providers add' to configure a model provider first.[/dim]")
            return

        provider_list = providers if isinstance(providers, list) else providers.get("data", [])
        if not provider_list:
            console.print("[yellow]No providers available.[/yellow]")
            return

        provider = next((p for p in provider_list if p.get("is_default")), provider_list[0])
        provider_id = provider.get("id") or provider.get("provider_id")

        experiment_data = {
            "name": f"init-posture-{time.strftime('%Y%m%d-%H%M%S')}",
            "description": "Initial posture estimation from project init",
            "test_category": "humanbound/adversarial/owasp_multi_turn",
            "testing_level": "unit",
            "provider_id": provider_id,
            "auto_start": True,
            "configuration": {},  # will use default_integration from project
        }

        with console.status("[dim]Creating experiment...[/dim]"):
            response = client.post("experiments", data=experiment_data, include_project=True)

        exp_id = response.get("id")
        if exp_id:
            console.print(f"  [green]\u2713[/green] Reconnaissance started: [dim]{exp_id}[/dim]")
            console.print(f"\n[dim]We'll let you know when it's done.[/dim]")
            console.print(f"[dim]Check status: hb experiments status {exp_id}[/dim]")
            console.print(f"[dim]View posture: hb posture[/dim]")
        else:
            console.print(f"[yellow]Experiment created but no ID returned.[/yellow]")

    except APIError as e:
        console.print(f"[red]Could not start experiment:[/red] {e}")
        console.print("[dim]Run 'hb test' to try again.[/dim]")


def _start_discovery(client: HumanboundClient, project_id: str):
    """Start the ASCAM discovery phase."""
    console.print()

    try:
        with console.status("[dim]Starting discovery phase...[/dim]"):
            response = client.post(
                f"projects/{project_id}/discovery/start",
                data={"trigger": "manual"},
                include_project=True,
                timeout=LONG_TIMEOUT,
            )

        console.print(f"  [green]\u2713[/green] Discovery phase started")
        console.print(f"\n[dim]This runs reconnaissance + initial campaign.[/dim]")
        console.print(f"[dim]Check status: hb posture[/dim]")

    except APIError as e:
        console.print(f"[red]Could not start discovery:[/red] {e}")
        console.print("[dim]Run 'hb test' to start tests manually.[/dim]")


# -- Serve helpers --------------------------------------------------------------


def _detect_runtime(repo_path: str):
    """Try to detect a runnable bot in the repository. Returns RuntimeInfo or None."""
    try:
        from ..serve.runtime_detector import RuntimeDetector
        detector = RuntimeDetector(repo_path)
        return detector.detect()
    except Exception:
        return None


def _start_serve(client, repo_path: str, runtime_info, yes: bool):
    """Start local server + tunnel, return (server, tunnel, endpoint_source) or (None, None, None).

    Shows cost warning before proceeding. On failure, prints warning and
    returns None — the caller continues with static-only analysis.
    """
    from ..serve.local_server import LocalServer
    from ..serve.tunnel_client import TunnelClient
    from ..serve.config_builder import build_bot_config

    # Cost warning (mandatory unless --yes)
    if not yes:
        console.print()
        console.print(Panel(
            "Your bot's LLM provider will be called during probing.\n"
            "The discovery conversation uses ~7 turns.\n"
            "Typical cost: $0.01-$0.10 depending on your model.\n\n"
            "Make sure your bot's API key (e.g. OPENAI_API_KEY) is set\n"
            "in your environment or in a .env file in the repository.",
            title="Cost Warning",
            border_style="yellow",
        ))
        if not Confirm.ask("Continue with live probing?", default=True):
            console.print("[dim]Skipping live probing.[/dim]")
            return None, None, None

    # Warn about missing .env if .env.example exists
    if runtime_info.env_file:
        env_path = Path(repo_path) / ".env"
        if not env_path.is_file():
            console.print(f"  [yellow]![/yellow] Found {runtime_info.env_file} but no .env — your bot may need environment variables")

    # Install dependencies
    server = LocalServer(runtime_info, repo_path)

    if runtime_info.install_cmd:
        do_install = yes or Confirm.ask(
            f"  Install dependencies? [dim]({runtime_info.install_cmd})[/dim]",
            default=True,
        )
        if do_install:
            try:
                with console.status(f"[dim]Installing dependencies...[/dim]"):
                    server.install_deps()
                console.print(f"  [green]\u2713[/green] Dependencies installed")
            except ServeError as e:
                console.print(f"[yellow]Dependency install failed:[/yellow] {e}")
                console.print("[dim]Continuing with static analysis only.[/dim]")
                return None, None, None

    # Start server
    try:
        with console.status(f"[dim]Starting {runtime_info.framework} server on port {server.port}...[/dim]"):
            server.start()
        console.print(f"  [green]\u2713[/green] Server started on port {server.port}")
    except ServeError as e:
        console.print(f"[yellow]Server failed to start:[/yellow] {e}")
        console.print("[dim]Continuing with static analysis only.[/dim]")
        return None, None, None

    # Connect tunnel
    tunnel = None
    try:
        tunnel = TunnelClient(
            local_port=server.port,
            api_token=client._api_token,
        )
        with console.status("[dim]Connecting tunnel...[/dim]"):
            public_url = tunnel.connect()
        console.print(f"  [green]\u2713[/green] Tunnel: [dim]{public_url}[/dim]")
    except (TunnelError, Exception) as e:
        console.print(f"[yellow]Tunnel connection failed:[/yellow] {e}")
        console.print("[dim]Continuing with static analysis only.[/dim]")
        server.stop()
        return None, None, None

    # Build endpoint source
    bot_config = build_bot_config(public_url, runtime_info)
    chat_ep = bot_config.get("chat_completion", {}).get("endpoint", "")
    console.print(f"  [green]\u2713[/green] Endpoint source: [dim]{chat_ep}[/dim]")

    return server, tunnel, {"source": "endpoint", "data": bot_config}


def _cleanup_serve(tunnel, server):
    """Safely disconnect tunnel and stop server."""
    if tunnel:
        try:
            tunnel.disconnect()
        except Exception:
            pass
    if server:
        try:
            server.stop()
        except Exception:
            pass


# -- Helpers --------------------------------------------------------------------


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
        return json.loads(value)
    except json.JSONDecodeError:
        console.print(f"[red]--endpoint must be a JSON string or path to a JSON file.[/red]")
        console.print("[dim]Example: --endpoint ./bot-config.json[/dim]")
        console.print('[dim]Example: --endpoint \'{"streaming": false, "chat_completion": {"endpoint": "...", "headers": {}, "payload": {"content": "$PROMPT"}}}\'[/dim]')
        raise SystemExit(1)


def _display_scope(scope: dict):
    """Display scope: business scope + permitted/restricted policies."""
    business_scope = scope.get("overall_business_scope", "")
    intents = scope.get("intents", {})
    permitted = intents.get("permitted", [])
    restricted = intents.get("restricted", [])

    # Build scope content
    parts = []
    if business_scope:
        parts.append(business_scope[:500] + ("..." if len(business_scope) > 500 else ""))

    if permitted and isinstance(permitted, list):
        parts.append("")
        parts.append("[bold green]Permitted:[/bold green]")
        for intent in permitted[:10]:
            parts.append(f"  [green]\u2022[/green] {str(intent)[:80]}")
        if len(permitted) > 10:
            parts.append(f"  [dim]... and {len(permitted) - 10} more[/dim]")

    if restricted and isinstance(restricted, list):
        parts.append("")
        parts.append("[bold red]Restricted:[/bold red]")
        for intent in restricted[:10]:
            parts.append(f"  [red]\u2022[/red] {str(intent)[:80]}")
        if len(restricted) > 10:
            parts.append(f"  [dim]... and {len(restricted) - 10} more[/dim]")

    if not permitted and not restricted:
        parts.append("")
        parts.append("[dim]No intents extracted — the LLM may need more context.[/dim]")
        parts.append("[dim]Try adding --prompt with a system prompt file for better results.[/dim]")

    console.print(Panel(
        "\n".join(parts),
        title="Scope",
        border_style="blue",
    ))


def _risk_bar(level: str) -> str:
    """Build a colored risk gauge bar."""
    fill_map = {"LOW": 4, "MEDIUM": 8, "HIGH": 12}
    color_map = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
    total = 12
    filled = fill_map.get(level, 8)
    color = color_map.get(level, "white")
    bar = f"[{color}]{'\u2588' * filled}[/{color}][dim]{'\u2591' * (total - filled)}[/dim]"
    return bar


def _threat_bar(priority: str) -> str:
    """Build a colored threat severity bar."""
    if priority == "high":
        return "[red]\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588[/red]"
    elif priority == "medium":
        return "[yellow]\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588[/yellow][dim]\u2591\u2591\u2591\u2591[/dim]"
    else:
        return "[dim]\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591[/dim]"


def _display_dashboard(
    name: str,
    risk_profile: dict,
    capabilities: dict,
    recommendations: list,
    has_integration: bool,
):
    """Compact single-panel risk dashboard with visual indicators."""
    risk_level = risk_profile.get("risk_level", "?")
    industry = risk_profile.get("industry", "unknown")
    risk_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}.get(risk_level, "white")

    lines = []

    # -- Risk gauge --
    bar = _risk_bar(risk_level)
    lines.append(f"  Risk     {bar}  [{risk_color}][bold]{risk_level}[/bold][/{risk_color}] \u00b7 {industry}")
    lines.append("")

    # -- Data sensitivity --
    pii = risk_profile.get("handles_pii", False)
    fin = risk_profile.get("handles_financial_data", False)
    health = risk_profile.get("handles_health_data", False)

    pii_icon = "[yellow]\u26a0 PII[/yellow]" if pii else "[dim]\u25cb PII[/dim]"
    fin_icon = "[yellow]\u26a0 Financial[/yellow]" if fin else "[dim]\u25cb Financial[/dim]"
    health_icon = "[yellow]\u26a0 Health[/yellow]" if health else "[dim]\u25cb Health[/dim]"
    lines.append(f"  Data     {pii_icon}   {fin_icon}   {health_icon}")

    # -- Capabilities --
    cap_defs = [
        ("has_memory", "Memory"),
        ("has_tools", "Tools"),
        ("has_rag", "RAG"),
        ("has_external_apis", "APIs"),
    ]
    cap_parts = []
    for key, label in cap_defs:
        if capabilities.get(key):
            cap_parts.append(f"[green]\u2713 {label}[/green]")
        else:
            cap_parts.append(f"[dim]\u2717 {label}[/dim]")
    lines.append(f"  Caps     {'   '.join(cap_parts)}")

    # -- Integration + Posture --
    integ = "[green]\u2713 configured[/green]" if has_integration else "[dim]\u2717 none[/dim]"
    lines.append(f"  Integ    {integ}        Posture  [dim]not yet scored[/dim]")

    # -- Regulations --
    regulations = risk_profile.get("applicable_regulations", [])
    if regulations:
        reg_str = "  ".join(f"[cyan]{r.upper()}[/cyan]" for r in regulations)
        lines.append(f"  Regs     {reg_str}")

    # -- Threats --
    if recommendations:
        lines.append("")
        lines.append("  [bold]Threats[/bold]")
        for rec in recommendations[:6]:
            cat = rec.get("threat_category", "").replace("_", " ").title()
            prio = rec.get("priority", "medium")
            bar = _threat_bar(prio)
            lines.append(f"    {bar}  {cat}")

    # -- Rationale --
    rationale = risk_profile.get("risk_rationale", "")
    if rationale:
        lines.append("")
        # Truncate long rationales
        if len(rationale) > 120:
            rationale = rationale[:117] + "..."
        lines.append(f"  [dim italic]{rationale}[/dim italic]")

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]{name}[/bold]",
        border_style=risk_color,
    ))


def _get_source_description(prompt: str, endpoint: str, repo: str, openapi: str) -> str:
    """Get a description of the sources used."""
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
