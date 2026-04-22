# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Azure Sentinel integration commands.

DEPRECATED: 'hb sentinel' is deprecated in favour of 'hb webhooks'.
This module is kept for backward compatibility. Remove after v2.0.
"""

import json
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from ..client import HumanboundClient
from ..config import CONFIG_DIR
from ..exceptions import APIError, NotAuthenticatedError

console = Console()

# DEPRECATED: remove after v2.0 — replaced by 'hb webhooks'
_DEPRECATION_MSG = (
    "[yellow]Warning:[/yellow] 'hb sentinel' is deprecated. Use [bold]hb webhooks[/bold] instead."
)

SENTINEL_CONFIG_FILE = CONFIG_DIR / "sentinel.json"

# All event types the connector should receive
ALL_EVENT_TYPES = [
    "finding.created",
    "finding.regressed",
    "posture.grade_changed",
    "drift.detected",
    "campaign.completed",
    "ascam.phase_changed",
    "ascam.paused",
    "ascam.resumed",
]

SETUP_INSTRUCTIONS = """
[bold]Azure Sentinel Integration[/bold]

[dim]Requirements:[/dim]
  - Azure CLI ([green]az[/green])  — https://aka.ms/install-azure-cli
  - Azure Functions Core Tools ([green]func[/green])  — https://aka.ms/install-azure-functions-core-tools

[dim]Steps:[/dim]

  0. Create a resource group (skip if you already have one):

     [green]az group create --name <your-rg> --location <region>[/green]

  1. Clone the connector repository:

     [green]git clone https://github.com/Humanbound/humanbound-sentinel-connector.git
     cd humanbound-sentinel-connector[/green]

  2. Deploy infrastructure to your Azure subscription:

     [green]az deployment group create \\
       --resource-group <your-rg> \\
       --template-file infrastructure/main.bicep \\
       --parameters workspaceName=<name>[/green]

  3. Deploy the connector code to the Function App:

     [green]az deployment group show --resource-group <your-rg> --name main \\
       --query properties.outputs.connectorFunctionName.value -o tsv[/green]

     [green]cd connector
     func azure functionapp publish <func-name>[/green]

  4. Connect Humanbound to your connector:

     [green]az deployment group show --resource-group <your-rg> --name main \\
       --query properties.outputs.connectorUrl.value -o tsv[/green]

     [green]hb sentinel connect --url <connector-url>[/green]

[dim]Commands:[/dim]
  [cyan]hb sentinel deploy[/cyan]       Deploy infrastructure + content to Azure
  [cyan]hb sentinel connect[/cyan]      Register webhook to your connector
  [cyan]hb sentinel sync[/cyan]         Replay historical events to Sentinel
  [cyan]hb sentinel status[/cyan]       Check connector health
  [cyan]hb sentinel test[/cyan]         Send a test event
  [cyan]hb sentinel disconnect[/cyan]   Remove the webhook

[dim]Automated deployment:[/dim]
  [green]hb sentinel deploy --resource-group <your-rg>[/green]

  Runs all deployment steps in sequence:
    1. Create resource group (if needed)
    2. Deploy infrastructure via Bicep
    3. Deploy connector code via Azure Functions Core Tools
    4. Display outputs (connector URL, workspace ID, etc.)

  Requires: Azure CLI (az) + Azure Functions Core Tools (func)
"""


def _load_sentinel_config() -> dict:
    """Load sentinel config from disk."""
    if SENTINEL_CONFIG_FILE.exists():
        try:
            return json.loads(SENTINEL_CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_sentinel_config(config: dict) -> None:
    """Save sentinel config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SENTINEL_CONFIG_FILE.write_text(json.dumps(config, indent=2))
    SENTINEL_CONFIG_FILE.chmod(0o600)


def _remove_sentinel_config() -> None:
    """Remove sentinel config file."""
    if SENTINEL_CONFIG_FILE.exists():
        SENTINEL_CONFIG_FILE.unlink()


def _require_sentinel_config() -> dict:
    """Load sentinel config or exit with error."""
    config = _load_sentinel_config()
    if not config or not config.get("webhook_id"):
        console.print("[red]Not connected to Sentinel.[/red]")
        console.print("Run 'hb sentinel connect --url <connector-url>' first.")
        raise SystemExit(1)
    return config


@click.group("sentinel", invoke_without_command=True)
@click.pass_context
def sentinel_group(ctx):
    """Azure Sentinel integration for security events.

    DEPRECATED: Use 'hb webhooks' instead. This command group will be
    removed in a future version.

    \b
    Deliver Humanbound security events to Azure Sentinel via a
    customer-deployed connector Azure Function.

    \b
    Quick start:
      1. Deploy connector (see instructions below)
      2. hb sentinel connect --url <connector-url>
      3. hb sentinel test
      4. hb sentinel sync --since 2026-01-01
    """
    # DEPRECATED: remove after v2.0
    console.print(_DEPRECATION_MSG)
    console.print()

    if ctx.invoked_subcommand is not None:
        return

    console.print(Panel(SETUP_INSTRUCTIONS, border_style="blue", padding=(1, 2)))


@sentinel_group.command("connect")
@click.option("--url", required=True, help="Connector Azure Function URL (HTTPS)")
@click.option("--secret", default=None, help="Webhook signing secret (auto-generated if omitted)")
@click.option("--name", default="Sentinel Connector", help="Webhook display name")
def connect(url: str, secret: str, name: str):
    """Register a webhook pointing to your Sentinel connector.

    Generates a signing secret, creates the webhook, sends a test ping,
    and saves the configuration locally.
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <org-id>' first.")
        raise SystemExit(1)

    # Check for existing connection
    existing = _load_sentinel_config()
    if existing.get("webhook_id"):
        console.print(f"[yellow]Already connected.[/yellow] Webhook ID: {existing['webhook_id']}")
        if not Confirm.ask("Replace existing connection?"):
            return

    # Generate secret if not provided
    webhook_secret = secret or secrets.token_hex(32)

    try:
        with console.status("Creating webhook..."):
            result = client.create_webhook(
                url=url,
                secret=webhook_secret,
                name=name,
                event_types=ALL_EVENT_TYPES,
            )

        webhook_id = result.get("id")
        if not webhook_id:
            console.print("[red]Failed to create webhook — no ID returned.[/red]")
            raise SystemExit(1)

        # Save config
        _save_sentinel_config(
            {
                "webhook_id": webhook_id,
                "webhook_secret": webhook_secret,
                "connector_url": url,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        console.print(f"[green]Webhook created.[/green] ID: {webhook_id}")

        # Send test ping
        with console.status("Sending test ping..."):
            try:
                client.test_webhook(webhook_id)
                console.print("[green]Test ping delivered successfully.[/green]")
            except APIError as e:
                console.print(f"[yellow]Test ping failed:[/yellow] {e}")
                console.print(
                    "[dim]The webhook was created but connectivity could not be verified.[/dim]"
                )

        console.print(f"\n[dim]Webhook secret (save this):[/dim] {webhook_secret}")
        console.print("[dim]Config saved to ~/.humanbound/sentinel.json[/dim]")

        # Remind user to sync secret to their Azure Function
        console.print(
            "\n[yellow]Important:[/yellow] Set the signing secret on your connector Function App:"
        )
        console.print(
            f"  [green]az functionapp config appsettings set \\\n    --resource-group <your-rg> \\\n    --name <func-name> \\\n    --settings WEBHOOK_SECRET={webhook_secret}[/green]"
        )
        console.print("[dim]Then run 'hb sentinel test' to verify.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@sentinel_group.command("sync")
@click.option("--since", default=None, help="Start date (ISO 8601, e.g. 2026-01-01)")
@click.option("--until", default=None, help="End date (ISO 8601)")
@click.option("--project", "project_id", default=None, help="Filter by project ID")
@click.option("--event-type", default=None, help="Filter by event type")
def sync(since: str, until: str, project_id: str, event_type: str):
    """Replay historical events to Sentinel for backfill.

    Triggers async delivery of past security events through the
    registered webhook. Max 1000 events per request.
    """
    config = _require_sentinel_config()
    webhook_id = config["webhook_id"]

    client = HumanboundClient()
    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        console.print("Use 'hb switch <org-id>' first.")
        raise SystemExit(1)

    try:
        with console.status("Starting replay..."):
            result = client.replay_webhook(
                webhook_id=webhook_id,
                since=since,
                until=until,
                project_id=project_id,
                event_type=event_type,
            )

        queued = result.get("events_queued", 0)
        if queued == 0:
            console.print("[yellow]No matching events found.[/yellow]")
        else:
            console.print(f"[green]Replay started[/green] — {queued} events queued for delivery.")
            console.print(
                "[dim]Events are being delivered asynchronously. Use 'hb sentinel status' to monitor.[/dim]"
            )

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@sentinel_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(as_json: bool):
    """Check Sentinel connector health and recent deliveries."""
    config = _require_sentinel_config()
    webhook_id = config["webhook_id"]

    client = HumanboundClient()
    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        raise SystemExit(1)

    try:
        with console.status("Fetching status..."):
            webhook = client.get_webhook(webhook_id)
            deliveries = client.list_webhook_deliveries(webhook_id, page=1, size=10)

        if as_json:
            print(
                json.dumps(
                    {"webhook": webhook, "recent_deliveries": deliveries}, indent=2, default=str
                )
            )
            return

        # Webhook info
        is_active = webhook.get("is_active", False)
        active_str = "[green]active[/green]" if is_active else "[red]inactive[/red]"
        console.print(
            Panel(
                f"Status: {active_str}\n"
                f"URL: [dim]{webhook.get('url', 'N/A')}[/dim]\n"
                f"Name: {webhook.get('name', 'N/A')}\n"
                f"[dim]ID: {webhook_id}[/dim]\n"
                f"[dim]Connected: {config.get('connected_at', 'N/A')}[/dim]",
                title="Sentinel Connector",
                border_style="blue",
                padding=(1, 2),
            )
        )

        # Recent deliveries
        delivery_data = deliveries.get("data", [])
        if not delivery_data:
            console.print("\n[dim]No recent deliveries.[/dim]")
            return

        console.print("\n[bold]Recent Deliveries:[/bold]\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Event ID", no_wrap=True)
        table.add_column("Status", width=8)
        table.add_column("Attempt", justify="right", width=8)
        table.add_column("Error", width=30)

        success_count = 0
        for d in delivery_data:
            code = d.get("status_code")
            error = d.get("error", "") or ""
            event_id = str(d.get("event_id", ""))
            attempt = str(d.get("attempt", 1))

            if code and 200 <= code < 300:
                status_str = f"[green]{code}[/green]"
                success_count += 1
            elif code:
                status_str = f"[red]{code}[/red]"
            else:
                status_str = "[red]ERR[/red]"

            table.add_row(event_id, status_str, attempt, error[:30] if error else "")

        console.print(table)
        console.print(
            f"\n[dim]Success rate (last {len(delivery_data)}): {success_count}/{len(delivery_data)}[/dim]"
        )

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@sentinel_group.command("test")
def test():
    """Send a test event to verify connectivity."""
    config = _require_sentinel_config()
    webhook_id = config["webhook_id"]

    client = HumanboundClient()
    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        raise SystemExit(1)

    try:
        with console.status("Sending test event..."):
            client.test_webhook(webhook_id)

        console.print("[green]Test event delivered successfully.[/green]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Test failed:[/red] {e}")
        raise SystemExit(1)


@sentinel_group.command("disconnect")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def disconnect(force: bool):
    """Remove the Sentinel webhook and local configuration."""
    config = _require_sentinel_config()
    webhook_id = config["webhook_id"]

    if not force:
        if not Confirm.ask(
            f"Disconnect Sentinel webhook [bold]{webhook_id}[/bold]? Events will stop flowing."
        ):
            console.print("[dim]Cancelled.[/dim]")
            return

    client = HumanboundClient()
    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console.print("[yellow]No organisation selected.[/yellow]")
        raise SystemExit(1)

    try:
        with console.status("Removing webhook..."):
            client.delete_webhook(webhook_id)

        _remove_sentinel_config()
        console.print("[green]Sentinel webhook removed.[/green]")
        console.print("[dim]Local configuration cleared.[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        # Still clean up local config if the webhook was already deleted
        if "not found" in str(e).lower():
            _remove_sentinel_config()
            console.print("[dim]Local configuration cleared (webhook already removed).[/dim]")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Deploy script generation + execution
# ---------------------------------------------------------------------------

DEPLOY_SCRIPT_TEMPLATE = r"""#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  Humanbound Sentinel — Automated Deployment
#  Generated by: hb sentinel deploy
# =============================================================================

RESOURCE_GROUP="{resource_group}"
LOCATION="{location}"
WORKSPACE_NAME="{workspace_name}"
ORG_DISPLAY_NAME="{org_display_name}"
REPO_URL="https://github.com/Humanbound/humanbound-sentinel-connector.git"

echo ""
echo "============================================"
echo " Humanbound Sentinel — Automated Deployment"
echo "============================================"
echo ""
echo "  Resource Group:  $RESOURCE_GROUP"
echo "  Location:        $LOCATION"
echo "  Workspace:       $WORKSPACE_NAME"
if [ -n "$ORG_DISPLAY_NAME" ]; then
    echo "  Organisation:    $ORG_DISPLAY_NAME"
fi
echo ""

# --- Step 0: Check prerequisites ---
echo "[Step 0/6] Checking prerequisites..."

if ! command -v az &> /dev/null; then
    echo ""
    echo "ERROR: Azure CLI (az) is not installed."
    echo ""
    echo "  Install it from: https://aka.ms/install-azure-cli"
    echo ""
    echo "  macOS:   brew install azure-cli"
    echo "  Linux:   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash"
    echo "  Windows: winget install Microsoft.AzureCLI"
    echo ""
    echo "  After installing, run: az login"
    exit 1
fi

if ! command -v func &> /dev/null; then
    echo ""
    echo "ERROR: Azure Functions Core Tools (func) is not installed."
    echo ""
    echo "  Install it from: https://aka.ms/install-azure-functions-core-tools"
    echo ""
    echo "  macOS:   brew tap azure/functions && brew install azure-functions-core-tools@4"
    echo "  Linux:   See https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local"
    echo "  Windows: winget install Microsoft.AzureFunctionsCoreTools"
    echo ""
    exit 1
fi

echo "  az:   $(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo 'ok')"
echo "  func: $(func --version 2>/dev/null || echo 'ok')"

# --- Step 1: Ensure Azure login ---
echo ""
echo "[Step 1/6] Verifying Azure login..."

if ! az account show &> /dev/null; then
    echo "  Not logged in. Opening browser for authentication..."
    az login
fi

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "  Subscription: $SUBSCRIPTION_ID"

# --- Step 2: Create resource group ---
echo ""
echo "[Step 2/6] Creating resource group (if needed)..."

az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none 2>/dev/null || true
echo "  Resource group: $RESOURCE_GROUP"

# --- Step 3: Clone repository + deploy infrastructure ---
echo ""
echo "[Step 3/6] Deploying infrastructure (Bicep)..."

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

git clone --depth 1 "$REPO_URL" "$WORK_DIR/repo" 2>/dev/null
echo "  Repository cloned."

DEPLOYMENT_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$WORK_DIR/repo/infrastructure/main.bicep" \
    --parameters location="$LOCATION" workspaceName="$WORKSPACE_NAME" \
    --query "properties.outputs" -o json)

echo "  Infrastructure deployed."

# --- Step 4: Deploy connector function code ---
echo ""
echo "[Step 4/6] Deploying connector function code..."

FUNC_NAME=$(echo "$DEPLOYMENT_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['connectorFunctionName']['value'])")

(cd "$WORK_DIR/repo/connector" && func azure functionapp publish "$FUNC_NAME" --python 2>/dev/null)
echo "  Connector deployed to: $FUNC_NAME"

# --- Step 5: Validate deployment ---
echo ""
echo "[Step 5/6] Validating deployment..."

CONNECTOR_URL=$(echo "$DEPLOYMENT_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['connectorUrl']['value'])")
WORKSPACE_ID=$(echo "$DEPLOYMENT_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['workspaceId']['value'])")
DCE_ENDPOINT=$(echo "$DEPLOYMENT_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['dceEndpoint']['value'])")

CHECKS_PASSED=0
CHECKS_TOTAL=4

# Check 1: Function app is reachable
echo ""
echo "  Checking connector function app..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$CONNECTOR_URL" 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" != "000" ]; then
    echo "    [PASS] Connector reachable (HTTP $HTTP_STATUS)"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo "    [FAIL] Connector not reachable at $CONNECTOR_URL"
fi

# Check 2: Sentinel is enabled
echo "  Checking Sentinel is enabled..."
SENTINEL_ENABLED=$(az security insights show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE_NAME" \
    --query "name" -o tsv 2>/dev/null || echo "")
if [ -n "$SENTINEL_ENABLED" ]; then
    echo "    [PASS] Microsoft Sentinel enabled"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    # Fallback: check via solutions
    SOLUTION_EXISTS=$(az resource show \
        --resource-group "$RESOURCE_GROUP" \
        --resource-type "Microsoft.OperationsManagement/solutions" \
        --name "SecurityInsights($WORKSPACE_NAME)" \
        --query "name" -o tsv 2>/dev/null || echo "")
    if [ -n "$SOLUTION_EXISTS" ]; then
        echo "    [PASS] Microsoft Sentinel enabled"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo "    [FAIL] Microsoft Sentinel not detected"
    fi
fi

# Check 3: Analytic rules deployed
echo "  Checking analytic rules..."
RULE_COUNT=$(az sentinel alert-rule list \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE_NAME" \
    --query "length([?contains(properties.displayName || '', 'Humanbound')])" \
    -o tsv 2>/dev/null || echo "0")
if [ "$RULE_COUNT" -ge 4 ] 2>/dev/null; then
    echo "    [PASS] $RULE_COUNT analytic rules found"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    # Fallback: check via REST API
    RULE_COUNT=$(az rest --method get \
        --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.OperationalInsights/workspaces/$WORKSPACE_NAME/providers/Microsoft.SecurityInsights/alertRules?api-version=2023-11-01" \
        --query "length(value[?contains(properties.displayName, 'Humanbound')])" \
        -o tsv 2>/dev/null || echo "0")
    if [ "$RULE_COUNT" -ge 4 ] 2>/dev/null; then
        echo "    [PASS] $RULE_COUNT analytic rules found"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo "    [WARN] Expected 4 analytic rules, found $RULE_COUNT"
    fi
fi

# Check 4: Hunting queries (saved searches) deployed
echo "  Checking hunting queries..."
SEARCH_COUNT=$(az monitor log-analytics workspace saved-search list \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE_NAME" \
    --query "length([?contains(name, 'humanbound_')])" \
    -o tsv 2>/dev/null || echo "0")
if [ "$SEARCH_COUNT" -ge 6 ] 2>/dev/null; then
    echo "    [PASS] $SEARCH_COUNT hunting queries found"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo "    [WARN] Expected 6 hunting queries, found $SEARCH_COUNT"
fi

# --- Step 6: Summary ---
echo ""

# Auto-connect mode: Python handles the summary + webhook setup
if [ "${HB_AUTO_CONNECT:-}" = "1" ]; then
    echo "  Infrastructure deployed: $CHECKS_PASSED/$CHECKS_TOTAL checks passed"
    exit 0
fi

echo "[Step 6/6] Done!"
echo ""

if [ "$CHECKS_PASSED" -eq "$CHECKS_TOTAL" ]; then
    echo "============================================"
    echo " ALL CHECKS PASSED ($CHECKS_PASSED/$CHECKS_TOTAL)"
    echo "============================================"
    echo ""
    echo "  Sentinel is fully deployed and operational."
    echo ""
    echo "  Connector URL:  $CONNECTOR_URL"
    echo "  Function App:   $FUNC_NAME"
    echo "  Workspace:      $WORKSPACE_NAME"
    echo ""
    echo "============================================"
    echo " Next Steps"
    echo "============================================"
    echo ""
    echo "  1. Connect Humanbound to your Sentinel connector:"
    echo ""
    echo "     hb sentinel connect --url $CONNECTOR_URL"
    echo ""
    echo "  2. Verify the connection:"
    echo ""
    echo "     hb sentinel test"
    echo ""
    echo "  3. Replay historical events (optional):"
    echo ""
    echo "     hb sentinel sync --since 2025-01-01"
    echo ""
    echo "  4. Open the CISO Dashboard in Azure Portal:"
    echo ""
    echo "     Sentinel > Workbooks > 'Humanbound AI Security — CISO Dashboard'"
    echo ""
    echo "     https://portal.azure.com/#blade/Microsoft_Azure_Security_Insights/MainMenuBlade"
    echo ""
else
    echo "============================================"
    echo " DEPLOYMENT COMPLETED WITH WARNINGS"
    echo " ($CHECKS_PASSED/$CHECKS_TOTAL checks passed)"
    echo "============================================"
    echo ""
    echo "  Some resources may still be provisioning."
    echo "  Wait a few minutes and re-check in the Azure Portal."
    echo ""
    echo "  Connector URL:  $CONNECTOR_URL"
    echo "  Workspace ID:   $WORKSPACE_ID"
    echo "  Workspace Name: $WORKSPACE_NAME"
    echo "  DCE Endpoint:   $DCE_ENDPOINT"
    echo "  Function App:   $FUNC_NAME"
    echo ""
    echo "  Troubleshoot:"
    echo "    az deployment group show --resource-group $RESOURCE_GROUP --name main"
    echo "    az deployment operation list --resource-group $RESOURCE_GROUP --name sentinel-content"
    echo ""
fi
"""


@sentinel_group.command("deploy")
@click.option("--resource-group", "--rg", required=True, help="Azure resource group name")
@click.option("--location", default="northeurope", help="Azure region (default: northeurope)")
@click.option(
    "--workspace",
    default="la-humanbound",
    help="Log Analytics workspace name (default: la-humanbound)",
)
@click.option("--export-only", is_flag=True, help="Export the script without running it")
@click.option(
    "--output", "output_path", default=None, help="Save script to file (implies --export-only)"
)
@click.option("--no-connect", is_flag=True, help="Deploy infrastructure only, skip webhook setup")
def deploy(
    resource_group: str,
    location: str,
    workspace: str,
    export_only: bool,
    output_path: str,
    no_connect: bool,
):
    """Deploy Sentinel infrastructure, content, and connector in one command.

    \b
    Generates and runs a deployment script that:
      1. Checks for az CLI and func tools
      2. Creates the resource group (if needed)
      3. Deploys infrastructure via Bicep (workspace, DCE/DCR, Sentinel, content)
      4. Deploys the connector Azure Function code
      5. Validates: connector reachable, Sentinel enabled, rules + queries deployed
      6. Creates webhook + sets signing secret on the connector (auto-connect)

    \b
    After deployment, the CISO can open the Sentinel workbook immediately —
    no manual 'hb sentinel connect' step required.

    \b
    Use --no-connect to deploy infrastructure only (skip webhook setup).

    \b
    Requirements:
      - Azure CLI (az)  — https://aka.ms/install-azure-cli
      - Azure Functions Core Tools (func) — https://aka.ms/install-azure-functions-core-tools
      - Humanbound login (hb login) — unless --no-connect or --export-only

    \b
    Examples:
      hb sentinel deploy --resource-group rg-humanbound
      hb sentinel deploy --rg rg-demo --location eastus --workspace la-demo
      hb sentinel deploy --rg rg-demo --no-connect
      hb sentinel deploy --rg rg-demo --export-only
      hb sentinel deploy --rg rg-demo --output deploy.sh
    """
    # When auto-connecting, verify Humanbound auth early (before deploying infra)
    client = None
    org_name = ""
    if not export_only and not output_path and not no_connect:
        client = HumanboundClient()
        if not client.is_authenticated():
            console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
            console.print("[dim]Or use --no-connect to deploy infrastructure only.[/dim]")
            raise SystemExit(1)
        if not client.organisation_id:
            console.print(
                "[yellow]No organisation selected.[/yellow] Run 'hb switch <org-id>' first."
            )
            console.print("[dim]Or use --no-connect to deploy infrastructure only.[/dim]")
            raise SystemExit(1)

        # Fetch org name for workbook personalisation
        try:
            orgs = client.list_organisations()
            org = next((o for o in orgs if o.get("id") == client.organisation_id), None)
            org_name = org.get("name", "") if org else ""
        except Exception:
            org_name = ""

    # Check prerequisites early when not export-only
    if not export_only and not output_path:
        missing = []
        if not shutil.which("az"):
            missing.append(("Azure CLI", "az", "https://aka.ms/install-azure-cli"))
        if not shutil.which("func"):
            missing.append(
                (
                    "Azure Functions Core Tools",
                    "func",
                    "https://aka.ms/install-azure-functions-core-tools",
                )
            )

        if missing:
            console.print("[red]Missing required tools:[/red]\n")
            for name, cmd, url in missing:
                console.print(f"  [bold]{name}[/bold] ([cyan]{cmd}[/cyan])")
                console.print(f"  Install: [green]{url}[/green]\n")
            raise SystemExit(1)

    # Generate the script (manual replace to avoid conflict with bash curly braces)
    script = DEPLOY_SCRIPT_TEMPLATE
    script = script.replace("{resource_group}", resource_group)
    script = script.replace("{location}", location)
    script = script.replace("{workspace_name}", workspace)
    script = script.replace("{org_display_name}", org_name)

    # Export mode — save to file
    if output_path or export_only:
        dest = Path(output_path) if output_path else Path(f"sentinel-deploy-{resource_group}.sh")
        dest.write_text(script)
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        console.print(f"[green]Script saved to:[/green] {dest}")
        console.print(f"\nRun it with: [green]./{dest}[/green]")
        return

    # Run mode — execute directly
    panel_lines = [
        "[bold]Deploying Sentinel to Azure[/bold]\n",
        f"  Resource Group:  [cyan]{resource_group}[/cyan]",
        f"  Location:        [cyan]{location}[/cyan]",
        f"  Workspace:       [cyan]{workspace}[/cyan]",
    ]
    if org_name:
        panel_lines.append(f"  Organisation:    [cyan]{org_name}[/cyan]")
    console.print(Panel("\n".join(panel_lines), border_style="blue", padding=(1, 2)))

    if not Confirm.ask("\nProceed with deployment?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    console.print("")

    # Write temp script and run
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, prefix="hb-sentinel-deploy-"
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        os.chmod(script_path, 0o755)
        env = os.environ.copy()
        if not no_connect:
            env["HB_AUTO_CONNECT"] = "1"

        result = subprocess.run(
            ["bash", script_path],
            check=False,
            env=env,
        )

        if result.returncode != 0:
            console.print(f"\n[red]Deployment failed[/red] (exit code {result.returncode}).")
            console.print("[dim]Check the output above for details.[/dim]")
            raise SystemExit(result.returncode)

    finally:
        os.unlink(script_path)

    # --- Auto-connect: create webhook + set secret ---
    if no_connect or not client:
        return

    connector_url = None
    try:
        # Retrieve deployment outputs
        console.print("\n[bold]Connecting Humanbound to Sentinel...[/bold]")
        outputs_result = subprocess.run(
            [
                "az",
                "deployment",
                "group",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                "main",
                "--query",
                "properties.outputs",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        outputs = json.loads(outputs_result.stdout)
        connector_url = outputs["connectorUrl"]["value"]
        func_name = outputs["connectorFunctionName"]["value"]

        # Check for existing connection
        existing = _load_sentinel_config()
        if existing.get("webhook_id"):
            console.print(
                f"  [yellow]Existing connection found.[/yellow] Webhook: {existing['webhook_id']}"
            )
            if not Confirm.ask("  Replace existing connection?"):
                console.print("[dim]Skipping webhook setup. Infrastructure was deployed.[/dim]")
                return

        # Create webhook
        webhook_secret = secrets.token_hex(32)
        with console.status("  Creating webhook..."):
            wh_result = client.create_webhook(
                url=connector_url,
                secret=webhook_secret,
                name="Sentinel Connector",
                event_types=ALL_EVENT_TYPES,
            )
        webhook_id = wh_result.get("id")
        if not webhook_id:
            raise APIError("No webhook ID returned")
        console.print(f"  Webhook created (ID: {webhook_id})")

        # Set signing secret on connector Function App
        console.print("  Setting webhook secret on connector...")
        subprocess.run(
            [
                "az",
                "functionapp",
                "config",
                "appsettings",
                "set",
                "--resource-group",
                resource_group,
                "--name",
                func_name,
                "--settings",
                f"WEBHOOK_SECRET={webhook_secret}",
                "--output",
                "none",
            ],
            check=True,
        )
        console.print("  Secret configured.")

        # Wait for settings to propagate, then test
        console.print("  Waiting for settings to propagate...")
        time.sleep(10)

        with console.status("  Sending test ping..."):
            client.test_webhook(webhook_id)
        console.print("  [green]Test event delivered successfully.[/green]")

        # Save local config
        config_data = {
            "webhook_id": webhook_id,
            "webhook_secret": webhook_secret,
            "connector_url": connector_url,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        if org_name:
            config_data["organisation_name"] = org_name
        _save_sentinel_config(config_data)

        # Final summary
        workbook_label = (
            f"Humanbound AI Security — {org_name}"
            if org_name
            else "Humanbound AI Security — CISO Dashboard"
        )
        summary_lines = [
            "[bold green]Sentinel is fully deployed and connected![/bold green]\n",
            f"  Connector URL:  [cyan]{connector_url}[/cyan]",
            f"  Function App:   [cyan]{func_name}[/cyan]",
            f"  Workspace:      [cyan]{workspace}[/cyan]",
        ]
        if org_name:
            summary_lines.append(f"  Organisation:    [cyan]{org_name}[/cyan]")
        summary_lines.append(f"  Webhook ID:     [dim]{webhook_id}[/dim]")
        summary_lines.append("\n  Open the CISO Dashboard in Azure Portal:")
        summary_lines.append(f"  [dim]Sentinel > Workbooks > '{workbook_label}'[/dim]")
        console.print(
            Panel(
                "\n".join(summary_lines),
                border_style="green",
                padding=(1, 2),
                title="All Done",
            )
        )

    except (APIError, NotAuthenticatedError) as e:
        console.print(f"\n[yellow]Auto-connect failed:[/yellow] {e}")
        console.print("Infrastructure was deployed successfully.")
        if connector_url:
            console.print(
                f"Connect manually: [green]hb sentinel connect --url {connector_url}[/green]"
            )
        else:
            console.print(
                "Run 'az deployment group show ...' to get the connector URL, then use 'hb sentinel connect'."
            )
    except Exception as e:
        console.print(f"\n[yellow]Post-deployment setup failed:[/yellow] {e}")
        console.print("Infrastructure was deployed successfully.")
        if connector_url:
            console.print(
                f"Connect manually: [green]hb sentinel connect --url {connector_url}[/green]"
            )
        else:
            console.print(
                "Run 'az deployment group show ...' to get the connector URL, then use 'hb sentinel connect'."
            )
