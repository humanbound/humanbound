# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Guardrails command for exporting guardrail configurations."""

import json
from pathlib import Path

import click
from rich.console import Console

from .. import telemetry
from ..agent_yaml import build_agent_yaml, dump_agent_yaml, load_scope_file
from ..config import write_secure_file
from ..engine import get_runner
from ..engine.platform_runner import PlatformTestRunner
from ..exceptions import APIError, NotAuthenticatedError

console = Console()
console_err = Console(stderr=True)


@click.command("guardrails")
@click.option(
    "--output", "-o", type=click.Path(), help="Output file path (prints to stdout if not specified)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "yaml", "openai"]),
    default="json",
    help="Output format (json=Humanbound format, yaml=YAML; not logged in, the "
    "humanbound-firewall agent.yaml; openai=OpenAI moderation format)",
)
@click.option(
    "--vendor",
    "-v",
    type=click.Choice(["humanbound", "openai"]),
    default="humanbound",
    help="Vendor format for guardrails export",
)
@click.option(
    "--model", type=str, default=None, help="Model to use for guardrails (e.g., gpt-4o-mini)"
)
@click.option(
    "--include-reasoning",
    is_flag=True,
    default=False,
    help="Include reasoning in guardrail responses",
)
@click.option(
    "--scope",
    "scope_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Not logged in, with --format yaml: build agent.yaml from this scope file "
    "(YAML/JSON, as for hb test --scope) instead of the latest local run.",
)
def guardrails_command(
    output: str,
    output_format: str,
    vendor: str,
    model: str,
    include_reasoning: bool,
    scope_path: str,
):
    """Export guardrails configuration for your project.

    Generates guardrail configurations based on discovered vulnerabilities
    and learned attack patterns that can be used with:
    - Humanbound Firewall OSS library
    - OpenAI moderation API format

    \b
    Examples:
      hb guardrails                          # Export Humanbound format
      hb guardrails --vendor=openai          # Export OpenAI format
      hb guardrails -o guardrails.json       # Save to file
      hb guardrails -f yaml -o agent.yaml    # Save as YAML
      hb guardrails -f yaml --scope scope.json -o agent.yaml   # Local: from a scope file
      hb guardrails --include-reasoning      # Include reasoning in output
    """
    runner = get_runner()
    is_platform = isinstance(runner, PlatformTestRunner)

    if not is_platform:
        if output_format == "yaml" and vendor == "humanbound":
            _local_agent_yaml(output, scope_path)
        else:
            _local_guardrails(output, output_format, vendor)
        return

    if scope_path:
        console_err.print("[dim]--scope applies when not logged in; ignoring it.[/dim]")

    client = runner.client

    if not client.project_id:
        console_err.print("[yellow]No project selected.[/yellow]")
        console_err.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    try:
        # Build query parameters
        params = {}
        if model:
            params["model"] = model
        if include_reasoning:
            params["include_reasoning"] = "true"

        # Fetch guardrails from API
        with console.status("Fetching guardrails...", spinner="dots"):
            response = client.get(
                f"projects/{client.project_id}/guardrails/export/{vendor}",
                params=params,
                include_project=True,  # API requires project_id header
            )
        guardrails = response

        # Format output
        if output_format == "yaml":
            formatted = _format_yaml(guardrails)
        elif output_format == "openai" and vendor != "openai":
            # Convert to OpenAI format if requested but fetched Humanbound format
            formatted = json.dumps(guardrails, indent=2, default=str)
        else:
            formatted = json.dumps(guardrails, indent=2, default=str)

        # Output
        if output:
            write_secure_file(output, formatted)
            console.print(f"[green]Guardrails exported to:[/green] {output}")
            console.print(f"[dim]Vendor: {vendor}[/dim]")
            console.print(f"[dim]Format: {output_format}[/dim]")
        else:
            print(formatted)

    except NotAuthenticatedError:
        telemetry.fire_gated_command_hit()
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


def _local_agent_yaml(output, scope_path):
    """Build the humanbound-firewall agent.yaml from a scope file or the latest local run."""
    try:
        if scope_path:
            scope, source = load_scope_file(scope_path), Path(scope_path).name
        else:
            scope, source = _latest_run_scope()
    except ValueError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if scope is None:
        console_err.print("[yellow]No scope found for agent.yaml.[/yellow] Either:")
        console_err.print(
            "  run a test:        hb test --endpoint ./config.json --scope ./scope.json --wait"
        )
        console_err.print("  or pass the scope: hb guardrails --format yaml --scope ./scope.json")
        raise SystemExit(1)

    formatted = dump_agent_yaml(build_agent_yaml(scope), source)
    if output:
        write_secure_file(output, formatted)
        console.print(f"[green]Firewall policy exported to:[/green] {output}")
        console.print(f'[dim]Load with Firewall.from_config("{output}")[/dim]')
    else:
        print(formatted, end="")


def _latest_run_scope():
    """The scope saved by the latest local run, or (None, None) when there is none."""
    results_dir = Path(".humanbound/results")
    if not results_dir.exists():
        return None, None
    exp_dirs = sorted(results_dir.iterdir(), reverse=True)
    meta_file = exp_dirs[0] / "meta.json" if exp_dirs else None
    if meta_file is None or not meta_file.exists():
        return None, None
    scope = json.loads(meta_file.read_text()).get("scope")
    return (scope, f"local run {exp_dirs[0].name}") if scope else (None, None)


def _local_guardrails(output, output_format, vendor):
    """Generate guardrails from local test results."""
    results_dir = Path(".humanbound/results")
    if not results_dir.exists():
        console_err.print("[yellow]No local test results found.[/yellow]")
        console_err.print("Run a test first: hb test --endpoint ./config.json --repo . --wait")
        raise SystemExit(1)

    # Find latest experiment
    exp_dirs = sorted(results_dir.iterdir(), reverse=True)
    if not exp_dirs:
        console_err.print("[yellow]No experiments found.[/yellow]")
        raise SystemExit(1)

    meta_file = exp_dirs[0] / "meta.json"
    logs_file = exp_dirs[0] / "logs.jsonl"

    if not meta_file.exists():
        console_err.print(f"[yellow]No results in {exp_dirs[0].name}.[/yellow]")
        raise SystemExit(1)

    meta = json.loads(meta_file.read_text())
    results = meta.get("results", {})
    insights = results.get("insights", meta.get("insights", []))

    # Read logs for pattern extraction
    logs = []
    if logs_file.exists():
        for line in logs_file.read_text().strip().split("\n"):
            if line.strip():
                logs.append(json.loads(line))

    # Generate rules from fail insights
    rules = []
    for i, insight in enumerate(insights):
        if insight.get("result") != "fail":
            continue
        rules.append(
            {
                "id": f"gr-{i + 1:03d}",
                "threat_class": insight.get("category", "unknown"),
                "pattern": insight.get("explanation", "")[:200],
                "action": "block",
                "severity": insight.get("severity", "medium"),
                "source": f"{exp_dirs[0].name}",
            }
        )

    guardrails = {
        "version": "1.0",
        "vendor": vendor,
        "rules": rules,
        "metadata": {
            "experiment": exp_dirs[0].name,
            "total_rules": len(rules),
        },
    }

    # Format output
    if output_format == "yaml":
        formatted = _format_yaml(guardrails)
    else:
        formatted = json.dumps(guardrails, indent=2, default=str)

    if output:
        write_secure_file(output, formatted)
        console.print(f"[green]Guardrails exported to:[/green] {output}")
        console.print(f"[dim]Rules: {len(rules)} | Source: {exp_dirs[0].name}[/dim]")
    else:
        print(formatted)


def _format_yaml(guardrails: dict) -> str:
    """Format guardrails as YAML."""
    try:
        import yaml

        return yaml.dump(guardrails, default_flow_style=False, sort_keys=False)
    except ImportError:
        # Fallback to simple YAML-like format
        lines = [
            "# Humanbound Guardrails Configuration",
            f"version: {guardrails.get('version', '1.0')}",
            "rules:",
        ]
        for rule in guardrails.get("rules", []):
            lines.append(f"  - id: {rule.get('id')}")
            lines.append(f"    type: {rule.get('type')}")
            lines.append(f"    severity: {rule.get('severity')}")
            lines.append(f"    category: {rule.get('category')}")
            lines.append(f"    action: {rule.get('action')}")
        return "\n".join(lines)
