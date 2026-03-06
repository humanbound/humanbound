"""Discover command — AI service discovery across cloud platforms.

DEPRECATED: 'hb discover' is deprecated in favour of 'hb connect --vendor'.
This module is kept for backward compatibility. Remove after v2.0.
"""

import json
import os
import time
import webbrowser

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()

# DEPRECATED: remove after v2.0 — replaced by 'hb connect --vendor'
_DEPRECATION_MSG = (
    "[yellow]Warning:[/yellow] 'hb discover' is deprecated. "
    "Use [bold]hb connect --vendor[/bold] instead."
)

# Humanbound Discovery Service — multi-tenant app (owned by Humanbound)
HUMANBOUND_DISCOVERY_APP_ID = "c6e4dcce-fce4-45a5-bf40-c8459ee2e180"

SUPPORTED_VENDORS = ["microsoft"]

RISK_COLORS = {
    "critical": "red bold",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "dim",
    "unknown": "dim",
}

CATEGORY_LABELS = {
    "embedded_copilot": "Embedded Copilot",
    "standalone_ai": "Standalone AI",
    "ai_platform": "AI Platform",
    "ai_dev_tool": "AI Dev Tool",
    "ai_assistant": "AI Assistant",
    "copilot_studio_agent": "Copilot Studio Agent",
}

STATUS_LABELS = {
    "licensed": "Licensed",
    "active": "Active",
    "consented": "Consented",
    "detected": "Detected",
}

_RISK_SORT = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "unknown": 5}

SEVERITY_COLORS = {"critical": "red bold", "high": "red", "medium": "yellow"}
SEVERITY_ICONS = {"critical": "!!!", "high": "!!", "medium": "!"}


def _copy_to_clipboard(text: str) -> bool:
    """Try to copy text to clipboard. Returns True on success."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def _get_connector(vendor: str, verbose: bool = False):
    """Factory: get the right connector for the vendor."""
    client_id = os.getenv("HUMANBOUND_DISCOVERY_CLIENT_ID", HUMANBOUND_DISCOVERY_APP_ID)

    if vendor == "microsoft":
        from ..connectors.microsoft import MicrosoftConnector
        return MicrosoftConnector(client_id=client_id, verbose=verbose)

    raise click.ClickException(f"Unknown vendor: {vendor}. Supported: {', '.join(SUPPORTED_VENDORS)}")


@click.command("discover")
@click.option(
    "--vendor", "-v",
    type=click.Choice(SUPPORTED_VENDORS, case_sensitive=False),
    default="microsoft",
    help="Cloud platform to scan (default: microsoft)",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("-V", "--verbose", is_flag=True, help="Print raw API responses from each discovery layer")
@click.option("--save", is_flag=True, default=False,
              help="Persist results to inventory (creates findings and posture snapshots)")
@click.option("--report", "report_path", is_flag=False, flag_value="auto", default=None,
              help="Export results as branded HTML report")
def discover_command(vendor: str, as_json: bool, yes: bool, verbose: bool, save: bool, report_path: str):
    """Discover AI services in your cloud environment.

    DEPRECATED: Use 'hb connect --vendor' instead. This command will be
    removed in a future version.

    Signs you in via browser device-code flow, scans for AI services
    client-side, sends results to the Humanbound platform for full
    security analysis (38 evidence signals, 15 SAI threat classes),
    and displays an assessed inventory.

    Use --save to persist results to your AI inventory, creating
    findings and posture snapshots.

    \b
    Examples:
      hb discover                    # Browser auth, display only
      hb discover --save             # + persist to inventory
      hb discover --save --report    # + HTML report
      hb discover --report           # Browser mode + HTML report
      hb discover --json             # Raw JSON output
      hb discover -V                 # Print raw API responses
    """
    # DEPRECATED: remove after v2.0
    console.print(_DEPRECATION_MSG)
    console.print()

    # ── 1. Check platform auth FIRST ──────────────────────────────────
    from ..client import HumanboundClient

    try:
        client = HumanboundClient()
    except Exception:
        console.print("[red]Could not initialise Humanbound client.[/red]")
        console.print("Run [bold]hb auth login[/bold] first.")
        raise SystemExit(1)

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run [bold]hb auth login[/bold] first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[red]No organisation selected.[/red] Run [bold]hb orgs use <id>[/bold] first.")
        raise SystemExit(1)

    # ── 2. Briefing & consent ─────────────────────────────────────────
    connector = _get_connector(vendor, verbose=verbose)

    console.print()
    console.print(Panel(
        "[bold]AI Service Discovery[/bold]\n\n"
        f"Vendor:  [bold]{vendor}[/bold]\n"
        f"App:     Humanbound Discovery Service\n\n"
        "This will:\n"
        "  1. Open a browser window for you to sign in with your admin account\n"
        "  2. Query your tenant for AI services [dim](read-only)[/dim]\n"
        "  3. Send the inventory to Humanbound for risk assessment\n"
        "  4. Display the assessed results\n\n"
        "[bold]Permissions requested[/bold] [dim](delegated, read-only)[/dim]:\n"
        "  - Application.Read.All   — list registered apps\n"
        "  - AuditLog.Read.All      — read sign-in activity\n"
        "  - Reports.Read.All       — read usage reports\n"
        "  - User.ReadBasic.All     — resolve resource owner names\n\n"
        "[dim]Raw data is sent to the Humanbound platform for analysis.[/dim]",
        border_style="blue",
    ))
    console.print()

    if not yes:
        if not click.confirm("Proceed with discovery?", default=True):
            console.print("[dim]Cancelled.[/dim]")
            return

    console.print()

    # ── 3. Microsoft auth ─────────────────────────────────────────────
    try:
        connector.authenticate(callback=_display_device_code)
    except PermissionError as e:
        _display_auth_error(str(e))
        raise SystemExit(1)

    console.print("[green]Signed in successfully.[/green]\n")

    # ── 4. Collect raw inventory ──────────────────────────────────────
    with console.status("[bold blue]Scanning for AI services..."):
        services, metadata = connector.discover()

    # ── 4b. Verbose: print raw API responses ──────────────────────────
    if verbose:
        _display_raw_responses(connector._raw_responses, services, metadata)

    if not services:
        status = metadata.get("status", "unknown")
        if status == "failed":
            console.print("[red]Discovery failed.[/red] Could not query any APIs.")
        else:
            console.print("[yellow]No AI services found.[/yellow]")
        _display_metadata(metadata)
        return

    console.print(f"Found [bold]{len(services)}[/bold] AI services. Sending to platform for analysis...\n")

    # ── 5. Send to backend for analysis ───────────────────────────────
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

    org_id = client.organisation_id
    try:
        with console.status("[bold blue]Analysing discovered services..."):
            analysis = client.post(
                f"organisations/{org_id}/analyse",
                data=payload,
                include_org=False,
            )
    except Exception as e:
        console.print(f"[red]Analysis failed:[/red] {e}")
        console.print("\n[dim]Raw inventory was collected but could not be assessed.[/dim]")
        raise SystemExit(1)

    # ── 6. Display ────────────────────────────────────────────────────
    if as_json:
        output = analysis
        if save:
            nonce = analysis.get("nonce")
            if nonce:
                try:
                    persist_result = client.persist_discovery(nonce)
                    output["persistence"] = persist_result
                except Exception as e:
                    output["persistence"] = {"error": str(e)}
            else:
                output["persistence"] = {"error": "No nonce returned (Redis may be unavailable)"}
        print(json.dumps(output, indent=2, default=str))
        return

    # ── 6a. Overlay evaluator risk onto services for consistent display ─
    # Layer 1/2 assigns "high" to most AI categories by default.
    # The evaluator (38 signals, 15 threat classes) produces the actual
    # risk_level that feeds posture. Use it everywhere so the tables,
    # hero, and heatmap all agree.
    _evals = analysis.get("evaluations", [])
    if _evals:
        _eval_risk_map = {
            ev["service_name"]: ev["risk_level"]
            for ev in _evals if "service_name" in ev and "risk_level" in ev
        }
        for svc in analysis.get("services", []):
            eval_rl = _eval_risk_map.get(svc.get("name"))
            if eval_rl:
                svc["risk"] = eval_rl

        # Recompute summary by_risk to match overlaid risk levels
        new_by_risk = {}
        for svc in analysis.get("services", []):
            r = svc.get("risk", "unknown")
            new_by_risk[r] = new_by_risk.get(r, 0) + 1
        if "summary" in analysis:
            analysis["summary"]["by_risk"] = new_by_risk

    _display_results(analysis, metadata)

    # ── 6b. Display evaluations panel ─────────────────────────────────
    evaluations = analysis.get("evaluations", [])
    posture_estimate = analysis.get("posture_estimate")
    if evaluations:
        _display_evaluations(evaluations, posture_estimate)

    # ── 7. Persist (--save) ───────────────────────────────────────────
    persist_result = None
    if save:
        nonce = analysis.get("nonce")
        if not nonce:
            console.print("\n[yellow]Cannot persist:[/yellow] no nonce returned (Redis may be unavailable).")
        else:
            try:
                with console.status("[bold blue]Saving to inventory..."):
                    persist_result = client.persist_discovery(nonce)
                _display_persist_summary(persist_result)
            except Exception as e:
                console.print(f"\n[red]Persistence failed:[/red] {e}")

    if report_path is not None:
        _export_browser_discover_report(analysis, metadata, report_path, persist_result)


# ── Verbose / raw output ─────────────────────────────────────────────────

_LAYER_LABELS = {
    "servicePrincipals": ("Layer 1", "Service Principals", "graph.microsoft.com/v1.0/servicePrincipals"),
    "auditLogs/signIns": ("Layer 2", "Sign-in Logs", "graph.microsoft.com/v1.0/auditLogs/signIns"),
    "reports/copilotUsage": ("Layer 3", "Copilot Usage Report", "graph.microsoft.com/beta/reports/getMicrosoft365CopilotUsageUserDetail"),
    "subscribedSkus": ("Layer 4", "License Inventory", "graph.microsoft.com/v1.0/subscribedSkus"),
    "resourceGraph": ("Layer 5", "Azure Resource Graph", "management.azure.com — Resources query"),
    "powerPlatformResources": ("Layer 5b", "Copilot Studio Agents", "management.azure.com — PowerPlatformResources query"),
    "cognitiveServices/inspect": ("Layer 5+", "Azure OpenAI Deep Inspection", "deployments + raiPolicies per resource"),
    "botService/inspect": ("Layer 5+", "Bot Service Deep Inspection", "properties + channels per resource"),
    "modelCatalog": ("Layer 5+", "Model Lifecycle Catalog", "CognitiveServices models list per location"),
    "accessConnections": ("Layer 6", "Access Verification", "roleAssignments + servicePrincipals resolution"),
}

_LAYER_ORDER = [
    "servicePrincipals",
    "auditLogs/signIns",
    "reports/copilotUsage",
    "subscribedSkus",
    "resourceGraph",
    "powerPlatformResources",
    "cognitiveServices/inspect",
    "botService/inspect",
    "modelCatalog",
    "accessConnections",
]


def _display_raw_responses(raw_responses: dict, services: list, metadata: dict):
    """Print raw API response data for each discovery layer."""
    console.print()
    console.print(Panel(
        "[bold]Raw API Responses[/bold]\n\n"
        f"Layers with data: [bold]{len(raw_responses)}[/bold]  |  "
        f"Services found (pre-analysis): [bold]{len(services)}[/bold]",
        border_style="magenta",
    ))

    if not raw_responses:
        console.print("[dim]No raw responses captured (all APIs may have failed).[/dim]\n")
        return

    for layer_key in _LAYER_ORDER:
        if layer_key not in raw_responses:
            continue

        label_num, label_name, label_api = _LAYER_LABELS.get(
            layer_key, ("?", layer_key, "")
        )

        data = raw_responses[layer_key]

        # Compute a summary line
        summary = _raw_summary(layer_key, data)

        console.print()
        console.print(f"[bold magenta]── {label_num}: {label_name} ──[/bold magenta]")
        console.print(f"  [dim]API: {label_api}[/dim]")
        if summary:
            console.print(f"  {summary}")

        # Print the JSON with syntax highlighting
        json_str = json.dumps(data, indent=2, default=str)
        # Truncate very large responses for readability
        lines = json_str.split("\n")
        if len(lines) > 200:
            truncated = "\n".join(lines[:200])
            truncated += f"\n\n  ... ({len(lines) - 200} more lines, use --json for full output)"
            json_str = truncated

        console.print(Syntax(json_str, "json", theme="monokai", line_numbers=False, word_wrap=True))

    # Also print the merged services list (connector output, pre-backend-analysis)
    console.print()
    console.print("[bold magenta]── Merged Services (sent to backend) ──[/bold magenta]")
    console.print(f"  [dim]{len(services)} services after dedup + merge[/dim]")
    merged_json = json.dumps(services, indent=2, default=str)
    merged_lines = merged_json.split("\n")
    if len(merged_lines) > 300:
        merged_json = "\n".join(merged_lines[:300])
        merged_json += f"\n\n  ... ({len(merged_lines) - 300} more lines)"
    console.print(Syntax(merged_json, "json", theme="monokai", line_numbers=False, word_wrap=True))

    # Metadata
    console.print()
    console.print("[bold magenta]── Discovery Metadata ──[/bold magenta]")
    console.print(Syntax(json.dumps(metadata, indent=2, default=str), "json", theme="monokai", line_numbers=False, word_wrap=True))
    console.print()


def _raw_summary(layer_key: str, data) -> str:
    """Generate a one-line summary for a raw response layer."""
    if layer_key == "servicePrincipals":
        if isinstance(data, list):
            total = sum(len(page.get("value", [])) for page in data)
            return f"[dim]{total} service principals across {len(data)} page(s)[/dim]"
    elif layer_key == "auditLogs/signIns":
        if isinstance(data, list):
            total = sum(len(page.get("value", [])) for page in data)
            return f"[dim]{total} sign-in entries across {len(data)} page(s)[/dim]"
    elif layer_key == "reports/copilotUsage":
        if isinstance(data, dict):
            count = len(data.get("value", []))
            return f"[dim]{count} user record(s)[/dim]"
    elif layer_key == "subscribedSkus":
        if isinstance(data, dict):
            count = len(data.get("value", []))
            return f"[dim]{count} subscribed SKU(s)[/dim]"
    elif layer_key == "resourceGraph":
        if isinstance(data, dict):
            count = len(data.get("data", []))
            return f"[dim]{count} resource(s)[/dim]"
    elif layer_key == "powerPlatformResources":
        if isinstance(data, dict):
            count = len(data.get("data", []))
            return f"[dim]{count} Copilot Studio agent(s)[/dim]"
    elif layer_key == "cognitiveServices/inspect":
        if isinstance(data, list):
            return f"[dim]{len(data)} Azure OpenAI resource(s) inspected[/dim]"
    elif layer_key == "botService/inspect":
        if isinstance(data, list):
            return f"[dim]{len(data)} Bot Service resource(s) inspected[/dim]"
    elif layer_key == "modelCatalog":
        if isinstance(data, list):
            total_models = sum(e.get("models_count", 0) for e in data)
            return f"[dim]{len(data)} location(s), {total_models} model(s) in catalog[/dim]"
    elif layer_key == "accessConnections":
        if isinstance(data, dict):
            sp_count = len(data.get("sp_resolutions", {}))
            conn_count = sum(len(v) for v in data.get("confirmed_connections", {}).values())
            return f"[dim]{sp_count} SP(s) resolved, {conn_count} confirmed connection(s)[/dim]"
    return ""


# ── Display helpers ───────────────────────────────────────────────────────


def _display_device_code(flow: dict):
    """Show sign-in instructions and auto-open browser."""
    url = flow.get("verification_uri", "https://microsoft.com/devicelogin")
    code = flow.get("user_code", "???")

    copied = _copy_to_clipboard(code)
    clipboard_line = (
        "\n\n  [green]Code copied to clipboard (Ctrl+V to paste)[/green]"
        if copied else ""
    )

    console.print(Panel(
        "Copy the code below, then sign in with your admin account\n"
        "in the browser window that will open.\n\n"
        f"  URL:   [bold blue]{url}[/bold blue]\n\n"
        f"  Code:  [bold yellow]{code}[/bold yellow]"
        f"{clipboard_line}",
        title="Sign In",
        border_style="yellow",
        padding=(1, 2),
    ))

    for remaining in range(5, 0, -1):
        console.print(f"  Opening browser in {remaining}s — copy the code above...", end="\r")
        time.sleep(1)
    console.print(" " * 60, end="\r")  # clear countdown line

    try:
        webbrowser.open(url)
        console.print("[green]Browser opened.[/green] Paste the code and sign in.")
    except Exception:
        console.print("Could not open browser automatically. Visit the URL above.")

    console.print("[dim]Waiting for sign-in...[/dim]\n")


def _display_auth_error(error_msg: str):
    """Show actionable guidance for authentication failures."""
    console.print(f"\n[red]Authentication failed.[/red]\n")

    # Consent denied
    if "AADSTS65001" in error_msg:
        console.print(Panel(
            "[bold]Permission consent required[/bold]\n\n"
            "The admin must approve the requested permissions.\n"
            "When the sign-in page appears, click [bold]Accept[/bold]\n"
            "to grant Humanbound read-only access to:\n\n"
            "  - Application.Read.All  (list apps)\n"
            "  - AuditLog.Read.All     (sign-in activity)\n"
            "  - Reports.Read.All      (usage reports)\n"
            "  - User.ReadBasic.All    (owner names)\n\n"
            "Then run [bold]hb discover[/bold] again.",
            border_style="yellow",
            padding=(1, 2),
        ))
    # Conditional Access blocked
    elif "AADSTS530003" in error_msg:
        console.print(Panel(
            "[bold]Blocked by Conditional Access[/bold]\n\n"
            "Your tenant's Conditional Access policies are blocking\n"
            "the device code sign-in. Options:\n\n"
            "  1. Sign in from a compliant device/network\n"
            "  2. Complete MFA when prompted in the browser\n"
            "  3. Ask your Azure AD admin to allow device code flow",
            border_style="yellow",
            padding=(1, 2),
        ))
    # User cancelled or timed out
    elif "expired" in error_msg.lower() or "cancel" in error_msg.lower():
        console.print("Sign-in was cancelled or timed out.")
        console.print("Run [bold]hb discover[/bold] to try again.")
    # Anything else
    else:
        console.print(f"[dim]{error_msg}[/dim]\n")
        console.print("If this persists, contact [bold]support@humanbound.ai[/bold]")


# Categories that represent deployed agents vs AI endpoints
_AGENT_CATEGORIES = {"copilot_studio_agent"}
_ENDPOINT_CATEGORIES = {"ai_platform"}


def _classify_into_sections(services: list) -> dict:
    """Classify assessed services into display sections.

    Returns dict with keys: agents, endpoints, in_development, adoption.

    Uses generic category field for classification — no vendor-specific
    resource type checks. Service principals and licenses go into adoption.
    """
    sections = {"agents": [], "endpoints": [], "in_development": [], "adoption": []}

    for svc in services:
        evidence = svc.get("evidence", {})
        category = svc.get("category", "")
        stage = evidence.get("stage", "")

        if stage == "in_development":
            sections["in_development"].append(svc)
        elif category in _AGENT_CATEGORIES:
            sections["agents"].append(svc)
        elif category in _ENDPOINT_CATEGORIES:
            sections["endpoints"].append(svc)
        else:
            sections["adoption"].append(svc)

    # Sort each section by risk
    for key in sections:
        sections[key].sort(key=lambda s: _RISK_SORT.get(s.get("risk", ""), 99))

    return sections


def _display_risk_summary(summary: dict, status: str):
    """Display the headline risk summary panel from backend summary."""
    total = summary.get("total_assets", 0)
    testable = summary.get("testable", 0)
    by_risk = summary.get("by_risk", {})

    line1_parts = [f"[bold]{total}[/bold] AI services found"]
    critical = by_risk.get("critical", 0)
    high = by_risk.get("high", 0)
    if critical:
        line1_parts.append(f"[red bold]{critical} critical[/red bold]")
    if high:
        line1_parts.append(f"[red]{high} high[/red]")
    if testable:
        line1_parts.append(f"[green]{testable} testable[/green]")

    # Section counts
    agents = summary.get("agents_count", 0)
    endpoints = summary.get("endpoints_count", 0)
    in_dev = summary.get("in_development_count", 0)
    section_parts = []
    if agents:
        section_parts.append(f"{agents} agent{'s' if agents != 1 else ''}")
    if endpoints:
        section_parts.append(f"{endpoints} endpoint{'s' if endpoints != 1 else ''}")
    if in_dev:
        section_parts.append(f"{in_dev} in development")

    body = "  |  ".join(line1_parts)
    if section_parts:
        body += f"\n[dim]{', '.join(section_parts)}[/dim]"

    console.print(Panel(
        body,
        title="Discovery Results",
        border_style="green" if status == "complete" else "yellow",
    ))
    console.print()


def _display_lifecycle_warnings(services: list):
    """Show lifecycle warnings for models approaching deprecation/retirement."""
    warnings = []
    for svc in services:
        for m in svc.get("evidence", {}).get("models", []):
            lc = m.get("lifecycle") or {}
            if not lc:
                continue
            status = lc.get("status", "active")
            mname = m.get("name", "unknown")
            if status == "retired":
                ret = lc.get("retirement_date", "")
                warnings.append(f"  [red bold]RETIRED[/red bold]  {mname}" + (f" ({ret})" if ret else ""))
            elif status == "deprecated":
                date = lc.get("retirement_date", "") or lc.get("deprecation_date", "")
                warnings.append(f"  [yellow]DEPRECATED[/yellow] {mname}" + (f" (EOL {date})" if date else ""))
            else:
                eol = lc.get("retirement_date") or lc.get("deprecation_date") or ""
                days = _days_until(eol) if eol else None
                if days is not None and days <= 90:
                    warnings.append(f"  [yellow bold]RETIRING[/yellow bold]   {mname} — {days} days remaining")
    if warnings:
        console.print(Panel(
            "\n".join(warnings),
            title="Model Lifecycle",
            border_style="yellow",
        ))
        console.print()


def _guardrail_badge(svc: dict) -> str:
    """Return a colored guardrail badge from control_assessment."""
    ca = svc.get("control_assessment") or {}
    gs = ca.get("guardrail_status")
    if gs == "full":
        return "[green]Full[/green]"
    elif gs == "partial":
        return "[yellow]Partial[/yellow]"
    elif gs == "none":
        return "[red]NONE[/red]"
    return "[dim]-[/dim]"


def _days_until(date_str: str) -> int | None:
    """Parse a YYYY-MM-DD date string and return days until that date, or None."""
    if not date_str:
        return None
    from datetime import datetime, timezone
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (target - datetime.now(timezone.utc)).days
    except (ValueError, TypeError):
        return None


def _format_lifecycle_badge(lifecycle: dict) -> str:
    """Return a colored lifecycle badge for CLI display."""
    if not lifecycle:
        return "[dim]-[/dim]"

    status = lifecycle.get("status", "active")
    ret_date = lifecycle.get("retirement_date", "")
    dep_date = lifecycle.get("deprecation_date", "")

    if status == "retired":
        date_str = f" ({ret_date})" if ret_date else ""
        return f"[red bold]RETIRED{date_str}[/red bold]"
    elif status == "deprecated":
        date_str = f" ({ret_date})" if ret_date else (f" ({dep_date})" if dep_date else "")
        return f"[yellow]Deprecated{date_str}[/yellow]"
    else:
        # Active — check for upcoming retirement
        days = _days_until(ret_date) or _days_until(dep_date)
        eol = ret_date or dep_date
        if days is not None and days <= 90:
            return f"[yellow bold]Retiring soon[/yellow bold] [dim]({days}d)[/dim]"
        elif eol:
            return f"[green]Active[/green] [dim](EOL {eol})[/dim]"
        else:
            return "[green]Active[/green]"


def _display_agents_section(agents: list):
    """Display the Agents section — deployed conversational AI agents."""
    if not agents:
        return

    console.print("[bold]Agents[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=True)
    table.add_column("Agent Name", min_width=22)
    table.add_column("Owner", min_width=16)
    table.add_column("Source", min_width=14)
    table.add_column("Channels", min_width=16)
    table.add_column("Auth", min_width=12, justify="center")
    table.add_column("Network", min_width=10, justify="center")
    table.add_column("Risk", min_width=8, justify="center")
    table.add_column("", min_width=8, justify="center")

    insecure_agents = []

    for svc in agents:
        evidence = svc.get("evidence", {})
        security = evidence.get("security", {})
        channels = evidence.get("channels", [])
        auth_type_val = evidence.get("auth_type", "")
        risk = svc.get("risk", "unknown")
        risk_color = RISK_COLORS.get(risk, "dim")

        name = svc["name"]

        # Source label from category
        source_str = CATEGORY_LABELS.get(svc.get("category", ""), svc.get("category", ""))

        # Channels from generic channel list
        enabled_channels = [ch["name"] for ch in channels if ch.get("enabled", True)]
        channels_str = ", ".join(enabled_channels) if enabled_channels else "[dim]-[/dim]"

        # Auth from generic auth_type + security.local_auth_disabled
        if security.get("local_auth_disabled") is False:
            auth_str = f"{auth_type_val} [red](local)[/red]" if auth_type_val else "[red](local)[/red]"
        elif auth_type_val:
            auth_str = auth_type_val
        else:
            auth_str = "[dim]-[/dim]"

        # Network from generic security.public_access
        pub = security.get("public_access")
        if pub is True:
            network_str = "[red]Public[/red]"
        elif pub is False:
            network_str = "[green]Private[/green]"
        else:
            network_str = "[dim]-[/dim]"

        # Owner
        owner_name = evidence.get("owner_name", "")
        owner_str = owner_name if owner_name else "[dim]-[/dim]"

        badge = "[green]TESTABLE[/green]" if svc.get("testable") else "[dim]-[/dim]"

        table.add_row(
            name,
            owner_str,
            source_str,
            channels_str,
            auth_str,
            network_str,
            f"[{risk_color}]{risk.upper()}[/{risk_color}]",
            badge,
        )

        # Track agents with insecure channel configuration
        if security.get("channel_secure") is False:
            insecure_agents.append((name, security))

    console.print(table)

    # Channel security sub-table for insecure agents
    _display_channel_details(insecure_agents)
    console.print()


def _display_channel_details(insecure_agents: list):
    """Display channel security issues for agents with insecure configuration."""
    if not insecure_agents:
        return

    console.print()
    console.print("[red]Channel Security Issues[/red]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, padding=(0, 1))
    table.add_column("Agent", min_width=20)
    table.add_column("Secure Site", min_width=12, justify="center")
    table.add_column("Trusted Origins", min_width=20)

    for agent_name, sec in insecure_agents:
        secure = "[red]No[/red]"
        origins = sec.get("trusted_origins", [])
        origins_str = ", ".join(origins) if origins else "[yellow]none[/yellow]"

        table.add_row(agent_name, secure, origins_str)

    console.print(table)


def _display_endpoints_section(endpoints: list):
    """Display the Endpoints section — AI platform resources."""
    if not endpoints:
        return

    console.print("[bold]Endpoints[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=True)
    table.add_column("Endpoint", min_width=22)
    table.add_column("Models", min_width=18)
    table.add_column("Guardrails", min_width=10, justify="center")
    table.add_column("Location", min_width=12)
    table.add_column("Risk", min_width=8, justify="center")
    table.add_column("", min_width=8, justify="center")

    for svc in endpoints:
        evidence = svc.get("evidence", {})
        risk = svc.get("risk", "unknown")
        risk_color = RISK_COLORS.get(risk, "dim")

        # Models from generic model list
        models = evidence.get("models", [])
        model_names = [m.get("name", "") for m in models if m.get("name")]
        models_str = ", ".join(model_names) if model_names else "[dim]-[/dim]"

        location = evidence.get("location", "")
        badge = "[green]TESTABLE[/green]" if svc.get("testable") else "[dim]-[/dim]"

        table.add_row(
            svc["name"],
            models_str,
            _guardrail_badge(svc),
            location,
            f"[{risk_color}]{risk.upper()}[/{risk_color}]",
            badge,
        )

    console.print(table)

    # Detailed model sub-tables for endpoints with model data
    _display_endpoint_details(endpoints)
    console.print()


def _display_endpoint_details(services: list):
    """Display model and security details for AI endpoint resources."""
    endpoints_with_models = [
        s for s in services
        if s.get("evidence", {}).get("models")
    ]
    if not endpoints_with_models:
        return

    console.print()

    for svc in endpoints_with_models:
        evidence = svc.get("evidence", {})
        models = evidence.get("models", [])
        sec = evidence.get("security", {})

        model_table = Table(
            title=svc["name"],
            show_header=True,
            header_style="bold",
            show_lines=False,
            padding=(0, 1),
        )
        model_table.add_column("Model", min_width=18)
        model_table.add_column("Version", min_width=10)
        model_table.add_column("SKU", min_width=14)
        model_table.add_column("Lifecycle", min_width=16)

        for m in models:
            capacity = m.get("capacity")
            sku_label = m.get("sku", "")
            if capacity:
                sku_label += f" ({capacity})"
            lifecycle = m.get("lifecycle") or {}
            lifecycle_str = _format_lifecycle_badge(lifecycle)
            model_table.add_row(
                m.get("name", ""),
                m.get("version", ""),
                sku_label,
                lifecycle_str,
            )

        console.print(model_table)

        # Security summary from generic security dict
        parts = []
        cf = sec.get("content_filtering")
        if cf is True:
            parts.append("Content Filtering: [green]ON[/green]")
        elif cf is False:
            parts.append("Content Filtering: [red]OFF[/red]")

        ip = sec.get("injection_protection")
        if ip is True:
            parts.append("Injection Protection: [green]ON[/green]")
        elif ip is False:
            parts.append("Injection Protection: [red]OFF[/red]")

        if parts:
            console.print(f"  [dim]{' | '.join(parts)}[/dim]")

        console.print()


def _display_in_development_section(services: list):
    """Display the In Development section — ML Projects and staged resources."""
    if not services:
        return

    console.print("[bold]In Development[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, padding=(0, 1))
    table.add_column("Project", min_width=22)
    table.add_column("Resource Group", min_width=18)
    table.add_column("Location", min_width=12)
    table.add_column("Risk", min_width=8, justify="center")

    for svc in services:
        evidence = svc.get("evidence", {})
        risk = svc.get("risk", "unknown")
        risk_color = RISK_COLORS.get(risk, "dim")

        table.add_row(
            svc["name"],
            evidence.get("resource_group", ""),
            evidence.get("location", ""),
            f"[{risk_color}]{risk.upper()}[/{risk_color}]",
        )

    console.print(table)
    console.print()


def _display_adoption_section(services: list):
    """Display the Adoption section — licensed/consented AI services without Azure resources."""
    if not services:
        return

    console.print("[bold]AI Adoption[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=True)
    table.add_column("Service", min_width=25)
    table.add_column("Category", min_width=16)
    table.add_column("Status", min_width=10, justify="center")
    table.add_column("Users", min_width=12, justify="center")
    table.add_column("Risk", min_width=8, justify="center")
    table.add_column("", min_width=8, justify="center")

    for svc in services:
        evidence = svc.get("evidence", {})
        risk = svc.get("risk", "unknown")
        risk_color = RISK_COLORS.get(risk, "dim")
        category = CATEGORY_LABELS.get(svc.get("category", ""), svc.get("category", ""))
        status_label = STATUS_LABELS.get(svc.get("status", ""), svc.get("status", ""))
        badge = "[green]TESTABLE[/green]" if svc.get("testable") else "[dim]-[/dim]"

        # User counts
        user_parts = []
        if evidence.get("active_users"):
            user_parts.append(f"{evidence['active_users']} active")
        if evidence.get("licensed_users"):
            user_parts.append(f"{evidence['licensed_users']} licensed")
        users_str = ", ".join(user_parts) if user_parts else "[dim]-[/dim]"

        table.add_row(
            svc["name"],
            category,
            status_label,
            users_str,
            f"[{risk_color}]{risk.upper()}[/{risk_color}]",
            badge,
        )

    console.print(table)
    console.print()


def _display_topology_section(topology: dict):
    """Display a text-based topology map showing resource connections."""
    if not topology:
        return

    edges = topology.get("edges", [])
    if not edges:
        return

    # Build node name lookup (with lifecycle annotations for model nodes)
    nodes_by_id = {}
    for n in topology.get("nodes", []):
        label = n["name"]
        lc = n.get("lifecycle") or {}
        lc_status = lc.get("status", "")
        if lc_status == "retired":
            ret = lc.get("retirement_date", "")
            label += f" [red bold](RETIRED{' ' + ret if ret else ''})[/red bold]"
        elif lc_status == "deprecated":
            ret = lc.get("retirement_date", "")
            dep = lc.get("deprecation_date", "")
            date = ret or dep
            label += f" [yellow](DEPRECATED{' EOL ' + date if date else ''})[/yellow]"
        else:
            eol = lc.get("retirement_date", "") or lc.get("deprecation_date", "")
            days = _days_until(eol)
            if days is not None and days <= 90:
                label += f" [yellow bold](RETIRING SOON {days}d)[/yellow bold]"
        nodes_by_id[n["id"]] = label

    console.print("[bold]Resource Topology[/bold]")
    console.print()

    lines = []
    for edge in edges:
        source_name = nodes_by_id.get(edge["source"], edge["source"])
        target_name = nodes_by_id.get(edge["target"], edge["target"])
        secure = edge.get("secure", True)
        detail = edge.get("detail", "")

        if not secure:
            arrow = "[red]-->[/red]"
            suffix = f" [red](INSECURE{': ' + detail if detail else ''})[/red]"
        elif "confirmed" in detail and "unconfirmed" not in detail:
            arrow = "[green]-->[/green]"
            suffix = " [green](confirmed)[/green]"
        elif "unconfirmed" in detail:
            arrow = "[yellow]-->[/yellow]"
            suffix = " [yellow](co-located, unconfirmed)[/yellow]"
        else:
            arrow = "-->"
            suffix = f" [dim]({detail})[/dim]" if detail else ""

        lines.append(f"  {source_name} {arrow} {target_name}{suffix}")

    console.print("\n".join(lines))
    console.print()


def _display_recommendations(recommendations: list):
    """Display backend-provided recommendations."""
    if not recommendations:
        return

    lines = []
    for rec in recommendations:
        severity = rec.get("severity", "medium")
        color = SEVERITY_COLORS.get(severity, "dim")
        icon = SEVERITY_ICONS.get(severity, "")
        treatment = rec.get("treatment", "")
        treatment_label = f" [{treatment}]" if treatment else ""

        lines.append(
            f"  [{color}]{icon} {severity.upper()}[/{color}]  {rec.get('action', '')}"
            f"[dim]{treatment_label}[/dim]\n"
            f"          [dim]{rec.get('rationale', '')}[/dim]"
        )

    has_critical = any(r.get("severity") == "critical" for r in recommendations)
    console.print(Panel(
        "\n\n".join(lines),
        title="Recommended Actions",
        border_style="red" if has_critical else "yellow",
        padding=(1, 1),
    ))


def _display_context_help():
    """Display an explainer panel about risk levels and guardrail status."""
    console.print()
    console.print(Panel(
        "[bold]What This Means[/bold]\n\n"
        "[bold]Risk Levels[/bold]\n"
        "  [red bold]CRITICAL[/red bold]  No content safety guardrails or insecure channel config\n"
        "  [red]HIGH[/red]      Service has broad capabilities or handles sensitive data\n"
        "  [yellow]MEDIUM[/yellow]    Standard AI service with typical exposure\n"
        "  [green]LOW[/green]       Limited capability, low exposure, or in development\n\n"
        "[bold]Sections[/bold]\n"
        "  Agents          Deployed conversational AI agents\n"
        "  Endpoints       AI platform resources (model hosting)\n"
        "  In Development  AI projects not yet deployed\n"
        "  AI Adoption     Licensed/consented AI services and platform access\n\n"
        "[bold]Guardrails[/bold]\n"
        "  [green]Full[/green]      All security controls enabled\n"
        "  [yellow]Partial[/yellow]   Some controls missing (e.g. injection protection off)\n"
        "  [red]NONE[/red]      No safety controls configured\n\n"
        "[bold]Next Steps[/bold]\n"
        "  Use [bold]hb test[/bold] to run adversarial security tests on testable services.",
        border_style="blue",
        padding=(1, 2),
    ))


def _display_results(analysis: dict, metadata: dict):
    """Display structured analysis results from backend, organised into sections."""
    services = analysis.get("services", [])
    summary = analysis.get("summary", {})
    recommendations = analysis.get("recommendations", [])
    topology = analysis.get("topology")
    status = metadata.get("status", "unknown")

    if not services:
        if status == "failed":
            console.print("[red]Discovery failed.[/red] Could not query any APIs.")
        else:
            console.print("[yellow]No AI services found.[/yellow]")
        _display_metadata(metadata)
        return

    # 1. Risk summary panel
    _display_risk_summary(summary, status)

    # 1b. Model lifecycle warnings
    _display_lifecycle_warnings(services)

    # 2. Classify into sections
    sections = _classify_into_sections(services)

    # 3. Agents section
    _display_agents_section(sections["agents"])

    # 4. Endpoints section
    _display_endpoints_section(sections["endpoints"])

    # 5. In Development section
    _display_in_development_section(sections["in_development"])

    # 6. Adoption section
    _display_adoption_section(sections["adoption"])

    # 7. Topology map
    _display_topology_section(topology)

    # 8. Recommendations
    _display_recommendations(recommendations)

    # 9. Context help
    _display_context_help()

    # 10. Metadata footer
    _display_metadata(metadata)


def _display_metadata(metadata: dict):
    """Show API query status footer."""
    console.print()
    apis_queried = metadata.get("apis_queried", [])
    apis_failed = metadata.get("apis_failed", [])
    permissions_missing = metadata.get("permissions_missing", [])

    if apis_queried:
        console.print(f"[dim]APIs queried: {', '.join(apis_queried)}[/dim]")
    if apis_failed:
        console.print(f"[yellow]APIs failed: {', '.join(apis_failed)}[/yellow]")
    if permissions_missing:
        console.print(Panel(
            "[bold]Some permissions are missing.[/bold]\n\n"
            "The scan completed but couldn't access all data.\n"
            "Ask your Azure AD admin to grant consent for:\n\n"
            + "\n".join(f"  [red]x[/red] {p}" for p in permissions_missing)
            + "\n\nThen run [bold]hb discover[/bold] again for full results.",
            border_style="yellow",
            padding=(1, 2),
        ))


# ── Evaluation & persistence display ─────────────────────────────────────


def _format_standards_refs(standards: dict) -> str:
    """Format standards dict into a compact reference string."""
    if not standards:
        return ""
    labels = {
        "owasp_llm": "OWASP",
        "mitre_atlas": "MITRE",
        "nist_ai_rmf": "NIST",
        "iso_42001": "ISO 42001",
        "eu_ai_act": "EU AI Act",
        "gdpr": "GDPR",
    }
    parts = []
    for key in ("owasp_llm", "mitre_atlas", "nist_ai_rmf", "iso_42001", "eu_ai_act", "gdpr"):
        val = standards.get(key)
        if val:
            parts.append(f"{labels.get(key, key)} {val}")
    return " · ".join(parts)


def _display_evaluations(evaluations: list, posture_estimate):
    """Display full threat analysis results from AssetEvaluator."""
    console.print()

    # Aggregate threat counts by severity
    all_threats = []
    for ev in evaluations:
        all_threats.extend(ev.get("triggered_threats", []))

    sev_counts = {}
    for t in all_threats:
        s = t.get("severity", "medium")
        sev_counts[s] = sev_counts.get(s, 0) + 1

    posture_str = f"[bold]{posture_estimate:.0f}/100[/bold]" if posture_estimate is not None else "[dim]N/A[/dim]"
    threat_parts = []
    for sev in ["critical", "high", "medium"]:
        count = sev_counts.get(sev, 0)
        if count:
            color = RISK_COLORS.get(sev, "dim")
            threat_parts.append(f"[{color}]{count} {sev}[/{color}]")

    summary_line = f"Posture Estimate: {posture_str}"
    if threat_parts:
        summary_line += f"  |  Threats: {', '.join(threat_parts)}"

    console.print(Panel(
        f"[bold]Security Evaluation[/bold]\n\n{summary_line}",
        border_style="red" if sev_counts.get("critical") else ("yellow" if sev_counts.get("high") else "green"),
    ))
    console.print()

    # Per-service panels with enriched detail
    for ev in evaluations:
        risk = ev.get("risk_level", "unknown")
        risk_color = RISK_COLORS.get(risk, "dim")
        threats = ev.get("triggered_threats", [])
        gaps = ev.get("governance_gaps", [])

        lines = []

        # Evidence basis badge
        confidence = ev.get("confidence", 1.0)
        basis = ev.get("evidence_basis", "evidence-based")
        if basis == "baseline":
            lines.append(f"[dim italic]Baseline assessment (worst-case, {confidence:.0%} observed)[/dim italic]")
        else:
            lines.append(f"[dim italic]Evidence-based ({confidence:.0%} observed)[/dim italic]")
        lines.append("")

        # Threats section
        if threats:
            lines.append("[bold]Triggered Threats[/bold]")
            sorted_threats = sorted(
                threats,
                key=lambda x: {"critical": 0, "high": 1, "medium": 2}.get(x.get("severity", ""), 3),
            )
            for t in sorted_threats:
                sev = t.get("severity", "medium")
                sev_color = RISK_COLORS.get(sev, "dim")
                sai_id = t.get("sai_id", "")
                name = t.get("name", "").replace("_", " ").title()

                lines.append(f"  [{sev_color}]{sev.upper()}[/{sev_color}]  {sai_id} — {name}")

                desc = t.get("description", "")
                if desc:
                    lines.append(f"    [dim]{desc}[/dim]")

                evidence = t.get("evidence", [])
                if evidence:
                    lines.append(f"    Evidence: [dim]{', '.join(evidence)}[/dim]")

                remediation = t.get("remediation", "")
                if remediation:
                    lines.append(f"    Fix: {remediation}")

                refs = _format_standards_refs(t.get("standards", {}))
                if refs:
                    lines.append(f"    [dim]Ref: {refs}[/dim]")

                lines.append("")
        else:
            lines.append("[green]No threats detected[/green]")
            lines.append("")

        # Governance gaps section
        if gaps:
            lines.append("[bold]Governance Gaps[/bold]")
            for gap in gaps:
                if isinstance(gap, dict):
                    sid = gap.get("signal_id", "")
                    desc = gap.get("description", sid)
                    rem = gap.get("remediation", "")
                    lines.append(f"  [yellow]![/yellow] {desc} ({sid})")
                    if rem:
                        lines.append(f"    [dim]-> {rem}[/dim]")
                else:
                    lines.append(f"  [yellow]![/yellow] {gap}")

        body = "\n".join(lines)
        service_name = ev.get("service_name", "")
        console.print(Panel(
            body,
            title=f" {service_name} ",
            subtitle=f" [{risk_color}]{risk.upper()}[/{risk_color}] ",
            border_style=risk_color.split()[0] if risk_color else "dim",
            padding=(1, 2),
        ))
        console.print()


def _display_persist_summary(result: dict):
    """Display a summary of what was persisted to inventory."""
    persisted = result.get("persisted", 0)
    findings_created = result.get("findings_created", 0)
    findings_updated = result.get("findings_updated", 0)
    posture_snapshots = result.get("posture_snapshots", 0)

    console.print()
    console.print(Panel(
        "[bold green]Saved to inventory[/bold green]\n\n"
        f"  Assets persisted:     [bold]{persisted}[/bold]\n"
        f"  Findings created:     {findings_created}\n"
        f"  Findings updated:     {findings_updated}\n"
        f"  Posture snapshots:    {posture_snapshots}",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()

    if persisted > 0:
        console.print("[dim]Use 'hb inventory' to view your AI assets.[/dim]")
        console.print("[dim]Use 'hb inventory view <id>' for asset details.[/dim]")


# ── Report exports ────────────────────────────────────────────────────────

_RISK_BADGE_HTML = {
    "critical": '<span class="badge badge-error">CRITICAL</span>',
    "high": '<span class="badge badge-error" style="opacity:.8">HIGH</span>',
    "medium": '<span class="badge badge-warning">MEDIUM</span>',
    "low": '<span class="badge badge-good">LOW</span>',
    "unknown": '<span class="badge badge-neutral">UNKNOWN</span>',
}


def _compute_risk_score(by_risk: dict) -> float:
    """Compute a 0-100 score from risk level distribution."""
    weights = {"critical": 0, "high": 25, "medium": 75, "low": 100, "info": 100, "unknown": 50}
    total = sum(by_risk.values())
    if total == 0:
        return 100.0
    return sum(weights.get(level, 50) * count for level, count in by_risk.items()) / total


def _report_score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _export_browser_discover_report(analysis: dict, metadata: dict, report_path, persist_result=None):
    """Export browser-mode discovery results as a branded HTML report."""
    from ..report_builder import ReportBuilder, _esc

    services = analysis.get("services", [])
    summary = analysis.get("summary", {})
    recommendations = analysis.get("recommendations", [])
    status = metadata.get("status", "unknown")

    total = summary.get("total_assets", 0)
    by_risk = summary.get("by_risk", {})
    testable = summary.get("testable", 0)
    critical = by_risk.get("critical", 0)
    high = by_risk.get("high", 0)
    agents_count = summary.get("agents_count", 0)
    endpoints_count = summary.get("endpoints_count", 0)
    in_dev_count = summary.get("in_development_count", 0)

    rb = ReportBuilder("AI Service Discovery", f"{total} services assessed")

    evaluations = analysis.get("evaluations", [])
    posture_estimate = analysis.get("posture_estimate")

    # ── Model lifecycle scan ──────────────────────────────────────────
    _retiring_models = []
    _deprecated_models = []
    _retired_models = []
    for svc in services:
        for m in svc.get("evidence", {}).get("models", []):
            lc = m.get("lifecycle") or {}
            if not lc:
                continue
            lc_status = lc.get("status", "active")
            mname = m.get("name", "unknown")
            if lc_status == "retired":
                _retired_models.append(mname)
            elif lc_status == "deprecated":
                _deprecated_models.append(mname)
            else:
                eol = lc.get("retirement_date") or lc.get("deprecation_date") or ""
                days = _days_until(eol) if eol else None
                if days is not None and days <= 90:
                    _retiring_models.append((mname, days))
    _lifecycle_concern_count = len(_retired_models) + len(_deprecated_models) + len(_retiring_models)

    # ── 1. Hero ──────────────────────────────────────────────────────
    # Derive risk counts from evaluator (same system that produces posture_estimate)
    # so the score and the headline counts are always consistent.
    if evaluations:
        eval_risk_counts = {}
        for ev in evaluations:
            rl = ev.get("risk_level", "info")
            eval_risk_counts[rl] = eval_risk_counts.get(rl, 0) + 1
        critical = eval_risk_counts.get("critical", 0)
        high = eval_risk_counts.get("high", 0)
    else:
        critical = by_risk.get("critical", 0)
        high = by_risk.get("high", 0)

    risk_score = posture_estimate if posture_estimate is not None else _compute_risk_score(by_risk)
    grade = _report_score_to_grade(risk_score)

    if critical > 0:
        verdict = (
            f"Your organisation has <strong>{total}</strong> AI services. "
            f"<strong style='color:var(--error)'>{critical} have critical security gaps</strong> "
            f"requiring immediate attention."
        )
    elif high > 0:
        verdict = (
            f"Your organisation has <strong>{total}</strong> AI services. "
            f"<strong style='color:var(--warning)'>{high} have high-risk configurations</strong> "
            f"that should be reviewed."
        )
    else:
        verdict = (
            f"Your organisation has <strong>{total}</strong> AI services "
            f"with no critical or high risks identified."
        )

    hero_metrics = {
        "Total Services": total,
        "Testable": testable,
        "Critical": critical,
        "High Risk": high,
    }
    if _lifecycle_concern_count:
        hero_metrics["Retiring Models"] = _lifecycle_concern_count
    rb.add_hero(risk_score, grade, verdict, metrics=hero_metrics)

    # ── 2. Executive Summary ─────────────────────────────────────────
    exec_parts = [f"Discovery identified <strong>{total} AI services</strong> across your cloud environment"]
    section_desc = []
    if agents_count:
        section_desc.append(f"{agents_count} deployed agent{'s' if agents_count != 1 else ''}")
    if endpoints_count:
        section_desc.append(f"{endpoints_count} AI endpoint{'s' if endpoints_count != 1 else ''}")
    adoption_count = total - agents_count - endpoints_count - in_dev_count
    if adoption_count > 0:
        section_desc.append(f"{adoption_count} adopted service{'s' if adoption_count != 1 else ''}")
    if in_dev_count:
        section_desc.append(f"{in_dev_count} in development")
    exec_parts[-1] += f": {', '.join(section_desc)}." if section_desc else "."

    if critical or high:
        count = critical + high
        exec_parts.append(
            f"<strong>{count} service{'s' if count != 1 else ''}</strong> present elevated risk "
            f"due to missing security controls, insecure configurations, or broad data access."
        )
    if testable:
        exec_parts.append(
            f"{testable} service{'s' if testable != 1 else ''} can be onboarded for adversarial security testing."
        )
    if _retired_models:
        exec_parts.append(
            f"<strong style='color:var(--error)'>{len(_retired_models)} retired model{'s' if len(_retired_models) != 1 else ''}</strong> "
            f"still deployed ({', '.join(_retired_models[:3])}) — migrate immediately."
        )
    if _deprecated_models:
        exec_parts.append(
            f"<strong style='color:var(--warning)'>{len(_deprecated_models)} deprecated model{'s' if len(_deprecated_models) != 1 else ''}</strong> "
            f"in use ({', '.join(_deprecated_models[:3])})."
        )
    if _retiring_models:
        labels = [f"{n} ({d}d)" for n, d in sorted(_retiring_models, key=lambda x: x[1])]
        exec_parts.append(
            f"<strong style='color:var(--warning)'>{len(_retiring_models)} model{'s' if len(_retiring_models) != 1 else ''} "
            f"retiring within 90 days</strong>: {', '.join(labels[:3])}."
        )
    if status == "partial":
        exec_parts.append(
            "Note: some APIs could not be queried — results may be incomplete. "
            "Grant missing permissions and re-run for full coverage."
        )
    rb.add_executive_summary(" ".join(exec_parts))

    # ── 3. Risk Heatmap ──────────────────────────────────────────────
    # Use evaluator risk levels when available (same system as posture score)
    if total > 0:
        heatmap_risk = eval_risk_counts if evaluations else by_risk
        rb.add_heatmap("Security Risk Distribution", heatmap_risk)

    # ── 4. Classified service tables ─────────────────────────────────
    sections = _classify_into_sections(services)

    # Agents table (generic evidence keys)
    if sections["agents"]:
        agent_rows = []
        for svc in sections["agents"]:
            evidence = svc.get("evidence", {})
            risk = svc.get("risk", "unknown")
            security = evidence.get("security", {})
            channels = evidence.get("channels", [])
            auth_type_val = evidence.get("auth_type", "")

            name = svc.get("name", "")
            source = CATEGORY_LABELS.get(svc.get("category", ""), svc.get("category", ""))

            # Channels from generic channel list
            enabled_channels = [ch["name"] for ch in channels if ch.get("enabled", True)]
            channels_str = ", ".join(enabled_channels) if enabled_channels else "-"

            # Auth from generic security + auth_type
            if security.get("local_auth_disabled") is False:
                auth_html = f'{_esc(auth_type_val)} <span class="badge badge-error">LOCAL</span>' if auth_type_val else '<span class="badge badge-error">LOCAL</span>'
            elif auth_type_val:
                auth_html = _esc(auth_type_val)
            else:
                auth_html = "-"

            # Network from generic security.public_access
            pub = security.get("public_access")
            if pub is True:
                network_html = '<span class="badge badge-error">PUBLIC</span>'
            elif pub is False:
                network_html = '<span class="badge badge-success">PRIVATE</span>'
            else:
                network_html = "-"

            risk_badge = _RISK_BADGE_HTML.get(risk, _esc(risk))
            testable_badge = '<span class="badge badge-good">Yes</span>' if svc.get("testable") else "-"

            agent_rows.append([
                _esc(name), _esc(source), _esc(channels_str),
                auth_html, network_html, risk_badge, testable_badge,
            ])

        rb.add_table("Deployed Agents",
                      columns=["Name", "Source", "Channels", "Auth", "Network", "Risk", "Testable"],
                      rows=agent_rows)

    # Endpoints table (generic evidence keys)
    if sections["endpoints"]:
        ep_rows = []
        for svc in sections["endpoints"]:
            evidence = svc.get("evidence", {})
            risk = svc.get("risk", "unknown")

            models = evidence.get("models", [])
            model_parts = []
            for m in models:
                mname = m.get("name", "")
                if not mname:
                    continue
                lc = m.get("lifecycle") or {}
                lc_status = lc.get("status", "active")
                if lc_status == "retired":
                    model_parts.append(f'{_esc(mname)} <span class="badge badge-error">RETIRED</span>')
                elif lc_status == "deprecated":
                    ret = lc.get("retirement_date", "")
                    suffix = f" (EOL {_esc(ret)})" if ret else ""
                    model_parts.append(f'{_esc(mname)} <span class="badge badge-warning">DEPRECATED{_esc(suffix)}</span>')
                else:
                    eol = lc.get("retirement_date", "") or lc.get("deprecation_date", "")
                    days = _days_until(eol)
                    if days is not None and days <= 90:
                        model_parts.append(f'{_esc(mname)} <span class="badge badge-warning">RETIRING SOON ({days}d)</span>')
                    else:
                        model_parts.append(_esc(mname))
            models_str = ", ".join(model_parts) if model_parts else "-"

            ca = svc.get("control_assessment") or {}
            gs = ca.get("guardrail_status", "")
            if gs == "full":
                guard_html = '<span class="badge badge-success">FULL</span>'
            elif gs == "partial":
                guard_html = '<span class="badge badge-warning">PARTIAL</span>'
            elif gs == "none":
                guard_html = '<span class="badge badge-error">NONE</span>'
            else:
                guard_html = "-"

            location = evidence.get("location", "-")
            risk_badge = _RISK_BADGE_HTML.get(risk, _esc(risk))

            ep_rows.append([
                _esc(svc.get("name", "")), models_str,
                guard_html, _esc(location), risk_badge,
            ])

        rb.add_table("AI Endpoints",
                      columns=["Endpoint", "Models", "Guardrails", "Location", "Risk"],
                      rows=ep_rows)

    # Adoption table
    if sections["adoption"]:
        adopt_rows = []
        for svc in sections["adoption"]:
            evidence = svc.get("evidence", {})
            risk = svc.get("risk", "unknown")
            category = CATEGORY_LABELS.get(svc.get("category", ""), svc.get("category", ""))
            status_label = STATUS_LABELS.get(svc.get("status", ""), svc.get("status", ""))

            user_parts = []
            if evidence.get("active_users"):
                user_parts.append(f"{evidence['active_users']} active")
            if evidence.get("licensed_users"):
                user_parts.append(f"{evidence['licensed_users']} licensed")
            users_str = ", ".join(user_parts) if user_parts else "-"

            risk_badge = _RISK_BADGE_HTML.get(risk, _esc(risk))
            adopt_rows.append([
                _esc(svc.get("name", "")), _esc(category),
                _esc(status_label), _esc(users_str), risk_badge,
            ])

        rb.add_table("AI Adoption &amp; Licensing",
                      columns=["Service", "Category", "Status", "Users", "Risk"],
                      rows=adopt_rows)

    # In development
    if sections["in_development"]:
        dev_rows = []
        for svc in sections["in_development"]:
            evidence = svc.get("evidence", {})
            risk = svc.get("risk", "unknown")
            dev_rows.append([
                _esc(svc.get("name", "")),
                _esc(evidence.get("resource_group", "")),
                _esc(evidence.get("location", "")),
                _RISK_BADGE_HTML.get(risk, _esc(risk)),
            ])
        rb.add_table("In Development",
                      columns=["Project", "Resource Group", "Location", "Risk"],
                      rows=dev_rows)

    # ── 4b. Topology Diagram (Mermaid) ─────────────────────────────
    topology = analysis.get("topology", {})
    topo_nodes = topology.get("nodes", [])
    topo_edges = topology.get("edges", [])
    if topo_nodes and topo_edges:
        mermaid_lines = ["graph LR"]

        # Risk levels from evaluations for node styling
        eval_risk_map = {}
        for ev in evaluations:
            sn = ev.get("service_name", "")
            rl = ev.get("risk_level", "")
            if sn and rl:
                eval_risk_map[sn] = rl

        # Build node definitions
        for node in topo_nodes:
            node_id = node["id"].replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "")
            label = _esc(node["name"])
            risk = eval_risk_map.get(node["name"], "")
            lifecycle = node.get("lifecycle") or {}
            lc_status = lifecycle.get("status", "")

            if lc_status == "retired":
                ret = lifecycle.get("retirement_date", "")
                label += f"<br/>RETIRED" + (f" {_esc(ret)}" if ret else "")
            elif lc_status == "deprecated":
                ret = lifecycle.get("retirement_date", "")
                dep = lifecycle.get("deprecation_date", "")
                date = ret or dep
                label += f"<br/>DEPRECATED" + (f" EOL {_esc(date)}" if date else "")
            else:
                eol = lifecycle.get("retirement_date", "") or lifecycle.get("deprecation_date", "")
                days = _days_until(eol)
                if days is not None and days <= 90:
                    label += f"<br/>RETIRING SOON ({days}d)"
                elif risk:
                    label += f"<br/>{risk.upper()}"

            mermaid_lines.append(f'    {node_id}["{label}"]')

        # Build edges
        for edge in topo_edges:
            src = edge["source"].replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "")
            tgt = edge["target"].replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "")
            detail = edge.get("detail", "")
            secure = edge.get("secure", True)

            if not secure:
                edge_label = f"INSECURE" + (f": {detail}" if detail else "")
                mermaid_lines.append(f'    {src} -->|"{_esc(edge_label)}"| {tgt}')
            elif "confirmed" in detail and "unconfirmed" not in detail:
                mermaid_lines.append(f'    {src} -->|"confirmed access"| {tgt}')
            elif "unconfirmed" in detail:
                mermaid_lines.append(f'    {src} -.->|"co-located"| {tgt}')
            else:
                if detail:
                    mermaid_lines.append(f'    {src} -->|"{_esc(detail)}"| {tgt}')
                else:
                    mermaid_lines.append(f'    {src} --> {tgt}')

        # Node styling classes
        mermaid_lines.append("")
        mermaid_lines.append("    classDef critical fill:#dc3545,color:#fff,stroke:#dc3545")
        mermaid_lines.append("    classDef high fill:#fd7e14,color:#fff,stroke:#fd7e14")
        mermaid_lines.append("    classDef medium fill:#ffc107,color:#000,stroke:#ffc107")
        mermaid_lines.append("    classDef low fill:#28a745,color:#fff,stroke:#28a745")
        mermaid_lines.append("    classDef retired fill:#dc3545,color:#fff,stroke:#fff,stroke-width:2px")
        mermaid_lines.append("    classDef deprecated fill:#fd7e14,color:#fff,stroke:#fff,stroke-width:2px")
        mermaid_lines.append("    classDef retiring_soon fill:#ffc107,color:#000,stroke:#fff,stroke-width:2px")

        # Apply classes to nodes (lifecycle takes precedence over risk for model nodes)
        for node in topo_nodes:
            node_id = node["id"].replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "")
            lifecycle = node.get("lifecycle") or {}
            lc_status = lifecycle.get("status", "")

            if lc_status == "retired":
                mermaid_lines.append(f"    class {node_id} retired")
            elif lc_status == "deprecated":
                mermaid_lines.append(f"    class {node_id} deprecated")
            else:
                eol = lifecycle.get("retirement_date", "") or lifecycle.get("deprecation_date", "")
                days = _days_until(eol)
                if days is not None and days <= 90:
                    mermaid_lines.append(f"    class {node_id} retiring_soon")
                else:
                    risk = eval_risk_map.get(node["name"], "")
                    if risk in ("critical", "high", "medium", "low"):
                        mermaid_lines.append(f"    class {node_id} {risk}")

        rb.add_mermaid("Resource Topology", "\n".join(mermaid_lines))

    # ── 5. Security Evaluations (enriched cards) ────────────────────
    if evaluations:
        cards_html = '<h2 style="margin-top:2rem;margin-bottom:1rem">Security Evaluations</h2>'
        for ev in evaluations:
            risk = ev.get("risk_level", "unknown")
            risk_badge = _RISK_BADGE_HTML.get(risk, _esc(risk))
            service_name = _esc(ev.get("service_name", ""))
            threats = ev.get("triggered_threats", [])
            gaps = ev.get("governance_gaps", [])

            card_body = ""

            # Evidence basis badge
            confidence = ev.get("confidence", 1.0)
            basis = ev.get("evidence_basis", "evidence-based")
            if basis == "baseline":
                card_body += (
                    f'<div style="margin-bottom:1rem">'
                    f'<span class="badge badge-warning">BASELINE</span> '
                    f'<span style="font-size:0.85rem;color:var(--text-secondary)">'
                    f'Worst-case assessment &mdash; {confidence:.0%} of signals backed by observed data</span></div>'
                )
            else:
                card_body += (
                    f'<div style="margin-bottom:1rem">'
                    f'<span class="badge badge-good">EVIDENCE-BASED</span> '
                    f'<span style="font-size:0.85rem;color:var(--text-secondary)">'
                    f'{confidence:.0%} of signals backed by observed data</span></div>'
                )

            # Threats
            if threats:
                card_body += '<div style="margin-bottom:1rem"><strong>Triggered Threats</strong></div>'
                sorted_threats = sorted(
                    threats,
                    key=lambda x: {"critical": 0, "high": 1, "medium": 2}.get(x.get("severity", ""), 3),
                )
                for t in sorted_threats:
                    sev = t.get("severity", "medium")
                    sev_badge = _RISK_BADGE_HTML.get(sev, _esc(sev))
                    sai_id = _esc(t.get("sai_id", ""))
                    name = _esc(t.get("name", "").replace("_", " ").title())
                    desc = _esc(t.get("description", ""))
                    remediation = _esc(t.get("remediation", ""))
                    evidence = t.get("evidence", [])
                    standards = t.get("standards", {})

                    card_body += f'<div style="margin-bottom:1.2rem;padding-left:0.5rem;border-left:3px solid var(--border)">'
                    card_body += f'<div>{sev_badge} <strong>{sai_id}</strong> — {name}</div>'
                    if desc:
                        card_body += f'<div style="margin-top:0.3rem;color:var(--text-secondary)">{desc}</div>'
                    if evidence:
                        evidence_str = ", ".join(_esc(e) for e in evidence)
                        card_body += f'<div style="margin-top:0.3rem;font-size:0.85rem;color:var(--text-secondary)">Evidence: {evidence_str}</div>'
                    if remediation:
                        card_body += f'<div style="margin-top:0.3rem"><strong>Fix:</strong> {remediation}</div>'
                    if standards:
                        ref_parts = []
                        std_labels = {"owasp_llm": "OWASP", "mitre_atlas": "MITRE", "nist_ai_rmf": "NIST", "iso_42001": "ISO 42001", "eu_ai_act": "EU AI Act", "gdpr": "GDPR"}
                        for key in ("owasp_llm", "mitre_atlas", "nist_ai_rmf", "iso_42001", "eu_ai_act", "gdpr"):
                            val = standards.get(key)
                            if val:
                                ref_parts.append(f"{std_labels.get(key, key)} {_esc(str(val))}")
                        if ref_parts:
                            card_body += f'<div style="margin-top:0.3rem;font-size:0.8rem;color:var(--text-secondary)">{" · ".join(ref_parts)}</div>'
                    card_body += '</div>'
            else:
                card_body += '<div style="color:var(--success);margin-bottom:1rem">No threats detected</div>'

            # Governance gaps
            if gaps:
                card_body += '<div style="margin-top:1rem;margin-bottom:0.5rem"><strong>Governance Gaps</strong></div>'
                for gap in gaps:
                    if isinstance(gap, dict):
                        sid = _esc(gap.get("signal_id", ""))
                        g_desc = _esc(gap.get("description", sid))
                        g_rem = _esc(gap.get("remediation", ""))
                        card_body += f'<div style="margin-bottom:0.5rem;padding-left:0.5rem;border-left:3px solid var(--warning)">'
                        card_body += f'<span style="color:var(--warning)">&#9888;</span> {g_desc} ({sid})'
                        if g_rem:
                            card_body += f'<div style="font-size:0.85rem;color:var(--text-secondary)">&rarr; {g_rem}</div>'
                        card_body += '</div>'
                    else:
                        card_body += f'<div style="margin-bottom:0.3rem"><span style="color:var(--warning)">&#9888;</span> {_esc(str(gap))}</div>'

            cards_html += (
                f'<div class="card" style="margin-bottom:1.5rem">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">'
                f'<h3 style="margin:0">{service_name}</h3>{risk_badge}</div>'
                f'{card_body}</div>'
            )

        rb._sections.append(cards_html)

    # ── 5b. Persistence Summary ─────────────────────────────────────
    if persist_result:
        rb.add_kv("Persistence Summary", {
            "Assets Persisted": persist_result.get("persisted", 0),
            "Findings Created": persist_result.get("findings_created", 0),
            "Findings Updated": persist_result.get("findings_updated", 0),
            "Posture Snapshots": persist_result.get("posture_snapshots", 0),
        })

    # ── 6. Prioritised Actions ───────────────────────────────────────
    if recommendations:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_recs = sorted(recommendations, key=lambda r: severity_order.get(r.get("severity", "medium"), 2))
        actions = []
        for rec in sorted_recs[:5]:
            severity = rec.get("severity", "medium")
            effort = "quick" if severity == "critical" else ("moderate" if severity == "high" else "strategic")
            actions.append({
                "title": _esc(rec.get("action", "")),
                "description": _esc(rec.get("rationale", "")),
                "effort": effort,
            })
        rb.add_actions("Prioritised Actions", actions)

    # ── 7. Metadata ──────────────────────────────────────────────────
    apis_failed = metadata.get("apis_failed", [])
    permissions_missing = metadata.get("permissions_missing", [])
    if apis_failed or permissions_missing:
        meta_items = []
        if apis_failed:
            meta_items.append(f"<strong>APIs failed:</strong> {_esc(', '.join(apis_failed))}")
        if permissions_missing:
            meta_items.append(f"<strong>Missing permissions:</strong> {_esc(', '.join(permissions_missing))}")
        rb.add_panel("Scan Metadata", "<br>".join(meta_items))

    # ── 8. Appendix: Methodology ─────────────────────────────────────
    from ..report_builder import STANDARDS_REFERENCE_HTML
    rb.add_appendix("Appendix: Methodology & References",
        "<p>This report was produced by the <code>hb discover</code> CLI command. "
        "The operator signed in to their cloud tenant via a browser-based device-code flow "
        "with read-only delegated permissions. The CLI queried the tenant's management APIs "
        "to enumerate AI-related services, applications, and resources. "
        "The raw inventory was then sent to the Humanbound platform, which assessed each "
        "service against 38 evidence signals across 15 SAI threat classes (6 risk domains), "
        "assigned risk levels, and generated actionable recommendations. "
        "No changes were made to the tenant during this process.</p>"
        + STANDARDS_REFERENCE_HTML)

    saved = rb.save(None if report_path == "auto" else report_path)
    console.print(f"\n[green]Report saved:[/green] {saved}")


