"""Connect command — unified entry point for agent and platform onboarding."""

import click
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

SCAN_TIMEOUT = 180


def _print_next(suggestions: list):
    """Print Next: suggestions block."""
    console.print("\n[dim]Next:[/dim]")
    for cmd, desc in suggestions:
        console.print(f"  [bold]{cmd}[/bold]  {desc}")


def _derive_agent_name(endpoint: str) -> str:
    """Derive a project name from bot config hostname, or fall back to 'My Agent'."""
    if not endpoint:
        return "My Agent"
    try:
        path = Path(endpoint)
        raw = path.read_text() if path.is_file() else endpoint
        config = json.loads(raw)
        ep_url = config.get("chat_completion", {}).get("endpoint", "")
        if ep_url:
            hostname = urlparse(ep_url).hostname
            if hostname:
                return hostname
    except Exception:
        pass
    return "My Agent"


@click.command("connect")
@click.option("--endpoint", "-e", help="Agent config JSON or file path (agent path)")
@click.option(
    "--vendor", "-v",
    type=click.Choice(["microsoft"]),
    help="Cloud vendor to scan (platform path)",
)
@click.option("--name", "-n", help="Project name (optional, auto-generated)")
@click.option("--prompt", "-p", type=click.Path(exists=True), help="System prompt file (agent path)")
@click.option("--repo", "-r", type=click.Path(exists=True), help="Repository path (agent path)")
@click.option("--openapi", "-o", type=click.Path(exists=True), help="OpenAPI spec file (agent path)")
@click.option("--serve", "-s", is_flag=True, help="Launch repo agent locally (agent path, requires --repo)")
@click.option("--tenant", help="Azure tenant ID (platform path, bypasses browser)")
@click.option("--client-id", "client_id", help="Service principal client ID (platform path)")
@click.option("--client-secret", "client_secret", help="Service principal secret (platform path)")
@click.option("--context", "-c", help="Extra context for the judge (e.g. 'Authenticated as Alice, her PII is expected'). String or path to .txt file.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmations")
@click.option("--timeout", "-t", type=int, default=SCAN_TIMEOUT, help="Request timeout in seconds")
def connect_command(endpoint, vendor, name, prompt, repo, openapi, serve,
                    tenant, client_id, client_secret, context, yes, timeout):
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
    has_agent_flags = any([endpoint, prompt, repo, openapi, serve])
    has_platform_flags = any([vendor, tenant, client_id, client_secret])

    if has_agent_flags and has_platform_flags:
        console.print("[red]Cannot combine agent flags (--endpoint/--prompt/--repo/--openapi) with platform flags (--vendor/--tenant).[/red]")
        raise SystemExit(1)

    if has_platform_flags:
        _connect_platform(vendor, name, tenant, client_id, client_secret, yes, timeout)
    elif has_agent_flags:
        _connect_agent(endpoint, name, prompt, repo, openapi, serve, context, yes, timeout)
    else:
        console.print("[yellow]Specify a path:[/yellow]")
        console.print()
        console.print("  [bold]Agent:[/bold]      hb connect --endpoint ./bot-config.json")
        console.print("  [bold]Platform:[/bold]  hb connect --vendor microsoft")
        console.print()
        console.print("[dim]Use --endpoint to connect your AI agent, or --vendor to scan your cloud.[/dim]")
        raise SystemExit(1)


# -- Agent path ----------------------------------------------------------------


def _connect_agent(endpoint, name, prompt, repo, openapi, serve, context, yes, timeout):
    """Agent path: probe -> create project -> auto-test -> show results."""
    from .init import (
        _scan_with_progress, _display_scope, _display_dashboard,
        _load_integration, _detect_runtime, _start_serve, _cleanup_serve,
        _get_source_description, _SCAN_PHASES,
    )

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
        console.print("Use --endpoint, --prompt, --repo, or --openapi to specify a source.")
        raise SystemExit(1)

    # Default name from hostname if not provided
    if not name:
        name = _derive_agent_name(endpoint)

    console.print(f"\n[bold]Connecting agent:[/bold] {name}\n")

    _server = None
    _tunnel = None

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

            runtime_info = _detect_runtime(repo)

            if runtime_info and not serve and not endpoint and not yes:
                console.print()
                console.print(f"  [cyan]i[/cyan] Detected runnable agent: [bold]{runtime_info.framework.title()}[/bold] ({runtime_info.entry_point})")
                console.print(f"    Start command: [dim]{runtime_info.start_cmd.replace('{port}', str(runtime_info.port))}[/dim]")
                from rich.prompt import Confirm
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
                summary_parts = [spec_result.get("description", "API-based agent")]
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
                console.print("[yellow]Could not detect a runnable agent in the repository.[/yellow]")
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

            default_integration = response.get("default_integration")
            if default_integration:
                project_data["default_integration"] = default_integration

            result = client.post("projects", data=project_data)

        project_id = result.get("id")
        console.print(f"  [green]\u2713[/green] Project created: [bold]{name}[/bold] [dim]({project_id})[/dim]")

        # Auto-select the project
        client.set_project(project_id)
        console.print(f"  [green]\u2713[/green] Set as current project")

        # -- Risk Dashboard ----------------------------------------------------
        _display_dashboard(
            name=name,
            risk_profile=risk_profile,
            has_integration=bool(default_integration),
        )

        # -- Auto-test ---------------------------------------------------------
        _auto_test(client, project_id, default_integration, context)

        # -- Next suggestions --------------------------------------------------
        _print_next([
            ("hb findings", "Detailed breakdown"),
            ("hb test --deep", "Deeper analysis"),
            ("hb posture", "View posture score"),
            ("hb report", "Share with team"),
        ])

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    finally:
        _cleanup_serve(_tunnel, _server)


# -- Platform path -------------------------------------------------------------


def _connect_platform(vendor, name, tenant, client_id, client_secret, yes, timeout):
    """Platform path: scan -> assess -> auto-save -> show posture."""
    from .discover import (
        _get_connector, _display_device_code, _display_auth_error,
        _display_results, _display_evaluations, _display_persist_summary,
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
        console.print("[red]Service principal auth requires all three: --tenant, --client-id, --client-secret[/red]")
        raise SystemExit(1)

    console.print()
    console.print(Panel(
        "[bold]AI Service Discovery[/bold]\n\n"
        f"Vendor:  [bold]{vendor}[/bold]\n"
        "Mode:    [bold]connect[/bold] (scan + assess + save)\n\n"
        "This will:\n"
        "  1. Sign in to your cloud tenant\n"
        "  2. Scan for AI services [dim](read-only)[/dim]\n"
        "  3. Assess against 38 security signals\n"
        "  4. Save results to your AI inventory",
        border_style="blue",
    ))
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
                console.print("[yellow]Service principal auth not yet supported for this vendor.[/yellow]")
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
                for ev in evals if "service_name" in ev and "risk_level" in ev
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
            console.print("\n[yellow]Cannot persist:[/yellow] no nonce returned (Redis may be unavailable).")

        # -- Next suggestions --------------------------------------------------
        _print_next([
            ("hb inventory", "Browse all assets"),
            ("hb posture --org", "Full org posture (3 dimensions)"),
            ("hb report --org", "Org-wide report"),
            ("hb discover --report", "Export HTML report"),
        ])

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


# -- Auto-test helper ----------------------------------------------------------


def _auto_test(client, project_id, default_integration, context=None):
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

        console.print(f"\n[dim]Running first security test...[/dim]")

        # Build configuration with optional context (max 1500 chars)
        configuration = {}
        if context:
            ctx_path = Path(context)
            ctx_value = ctx_path.read_text().strip() if ctx_path.is_file() else context
            if len(ctx_value) > 1500:
                console.print(f"[red]Context too long ({len(ctx_value)} chars). Maximum is 1,500.[/red]")
                raise SystemExit(1)
            configuration["context"] = ctx_value

        # Create experiment with auto_start
        experiment_data = {
            "name": f"connect-{time.strftime('%Y%m%d-%H%M%S')}",
            "description": "Initial assessment from hb connect",
            "test_category": "humanbound/adversarial/owasp_agentic",
            "testing_level": "unit",
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

        console.print(f"  [green]\u2713[/green] Test started: [dim]{exp_id}[/dim]")
        console.print()
        console.print(f"  [dim]Watch progress:[/dim]  hb status {exp_id} -w")
        console.print(f"  [dim]View logs:[/dim]       hb logs {exp_id}")

    except Exception as e:
        console.print(f"\n[yellow]Auto-test failed:[/yellow] {e}")
        console.print("[dim]Run 'hb test' to try again.[/dim]")
