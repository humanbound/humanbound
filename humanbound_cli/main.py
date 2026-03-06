"""Humanbound CLI entry point."""

import click
from rich.console import Console

from . import __version__
from .client import HumanboundClient
from .config import get_base_url

from .commands import (
    auth,
    orgs,
    projects,
    experiments,
    init,
    test,
    logs,
    posture,
    guardrails,
    docs,
    providers,
    findings,
    api_keys,
    members,
    coverage,
    campaigns,
    upload_logs,
    sentinel,
    discover,
    connectors,
    inventory,
    completion,
    connect,
    report,
    monitor,
    webhooks,
    mcp,
)

console = Console()


def get_client() -> HumanboundClient:
    """Get a configured Humanbound client."""
    return HumanboundClient()


@click.group()
@click.version_option(version=__version__, prog_name="hb")
@click.option(
    "--base-url",
    envvar="HUMANBOUND_BASE_URL",
    help="API base URL (default: https://api.humanbound.ai)",
)
@click.pass_context
def cli(ctx, base_url: str):
    """Humanbound CLI - AI agent security testing from the command line.

    Use 'hb login' to authenticate, then connect your agent and run tests.

    \b
    Quick Start:
      hb login                                # Authenticate
      hb connect --endpoint ./bot-config.json # Connect your agent
      hb test                                 # Run security tests
      hb status                               # Check progress
      hb findings                             # View results
      hb posture                              # View posture score
      hb report                               # Share with team
      hb monitor                              # Start continuous monitoring

    \b
    Platform Discovery:
      hb connect --vendor microsoft           # Scan cloud for shadow AI
    """
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url


# ---------------------------------------------------------------------------
# Layer 1 — The 9 Verbs (top-level commands)
# login, connect, test, status, findings, posture, logs, report, monitor
# These are registered below as aliases or direct commands.
# ---------------------------------------------------------------------------

# Layer 2 — Noun groups (always available)
cli.add_command(projects.projects_group)
cli.add_command(experiments.experiments_group)
cli.add_command(providers.providers_group)
cli.add_command(findings.findings_group)
cli.add_command(api_keys.api_keys_group)
cli.add_command(members.members_group)
cli.add_command(campaigns.campaigns_group)
cli.add_command(webhooks.webhooks_group)
cli.add_command(connectors.connectors_group)
cli.add_command(inventory.inventory_group)
cli.add_command(auth.auth_group)
cli.add_command(orgs.orgs_group)
cli.add_command(completion.completion_command)
cli.add_command(guardrails.guardrails_command)
cli.add_command(docs.docs_command)

# MCP server (optional — requires mcp SDK)
if mcp is not None:
    cli.add_command(mcp.mcp_command)

# Layer 1 — Top-level verbs
cli.add_command(connect.connect_command)
cli.add_command(test.test_command)
cli.add_command(logs.logs_group)
cli.add_command(posture.posture_command)
cli.add_command(report.report_command)
cli.add_command(monitor.monitor_command)

# ---------------------------------------------------------------------------
# DEPRECATED commands — kept for backward compatibility, remove after v2.0
# Each prints a deprecation warning and delegates to the replacement.
# ---------------------------------------------------------------------------
# DEPRECATED: hb init → use hb connect --endpoint (remove after v2.0)
cli.add_command(init.init_project)
# DEPRECATED: hb discover → use hb connect --vendor (remove after v2.0)
cli.add_command(discover.discover_command)
# DEPRECATED: hb coverage → use hb posture --coverage (remove after v2.0)
cli.add_command(coverage.coverage_command)
# DEPRECATED: hb upload-logs → use hb logs upload (remove after v2.0)
cli.add_command(upload_logs.upload_logs_command)
# DEPRECATED: hb sentinel → use hb webhooks (remove after v2.0)
cli.add_command(sentinel.sentinel_group)


# Convenience aliases at top level
@cli.command("login")
@click.pass_context
def login_alias(ctx):
    """Authenticate with Humanbound (alias for 'auth login')."""
    ctx.invoke(auth.login, base_url=ctx.obj.get("base_url"))


@cli.command("logout")
@click.option("--revoke", is_flag=True, help="Also clear browser SSO session (opens browser)")
@click.option("--port", default=8085, help="Local callback port (default: 8085)")
@click.pass_context
def logout_alias(ctx, revoke, port):
    """Clear stored credentials (alias for 'auth logout')."""
    ctx.invoke(auth.logout, revoke=revoke, port=port)


@cli.command("whoami")
@click.pass_context
def whoami_alias(ctx):
    """Show current authentication status (alias for 'auth whoami')."""
    ctx.invoke(auth.whoami)


@cli.command("switch")
@click.argument("org_id")
def switch_org(org_id: str):
    """Switch to a different organisation.

    ORG_ID: Organisation UUID to use.
    """
    from .client import HumanboundClient
    from .exceptions import NotAuthenticatedError, APIError

    client = HumanboundClient()

    try:
        # Verify the org exists by listing and checking
        orgs_list = client.list_organisations()
        org = next((o for o in orgs_list if o.get("id") == org_id), None)

        if not org:
            console.print(f"[red]Organisation not found:[/red] {org_id}")
            console.print("\nAvailable organisations:")
            for o in orgs_list:
                console.print(f"  {o.get('id')} - {o.get('name')}")
            raise SystemExit(1)

        client.set_organisation(org_id)
        console.print(f"[green]Switched to organisation:[/green] {org.get('name')}")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")


@cli.command("status")
@click.argument("experiment_id", required=False)
@click.option("--watch", "-w", is_flag=True, help="Watch status until completion")
@click.option("--all", "show_all", is_flag=True, help="Show all project experiments (polls every 60s)")
@click.pass_context
def status_alias(ctx, experiment_id: str, watch: bool, show_all: bool):
    """Check experiment status (alias for 'experiments status').

    If no experiment_id is provided, shows the most recent experiment.
    Use --all to see a dashboard of all project experiments.
    """
    if show_all:
        ctx.invoke(
            experiments.experiment_status,
            experiment_id=None,
            watch=False,
            interval=10,
            show_all=True,
        )
        return

    client = HumanboundClient()

    if not experiment_id:
        # Get most recent experiment
        if not client.project_id:
            console.print("[yellow]No project selected.[/yellow]")
            console.print("Use 'hb projects use <id>' to select a project.")
            raise SystemExit(1)

        try:
            response = client.list_experiments(page=1, size=1)
            exps = response.get("data", [])
            if not exps:
                console.print("[yellow]No experiments found.[/yellow]")
                raise SystemExit(1)
            experiment_id = exps[0].get("id")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)

    ctx.invoke(
        experiments.experiment_status,
        experiment_id=experiment_id,
        watch=watch,
        interval=10,
        show_all=False,
    )


if __name__ == "__main__":
    cli()
