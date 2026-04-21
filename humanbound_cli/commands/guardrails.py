# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Guardrails command for exporting guardrail configurations."""

import click
from rich.console import Console
import json
import sys
from pathlib import Path

from ..client import HumanboundClient
from ..engine import get_runner
from ..engine.platform_runner import PlatformTestRunner
from ..exceptions import NotAuthenticatedError, APIError

console = Console()
console_err = Console(stderr=True)


@click.command("guardrails")
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output file path (prints to stdout if not specified)"
)
@click.option(
    "--format", "-f", "output_format",
    type=click.Choice(["json", "yaml", "openai"]),
    default="json",
    help="Output format (json=Humanbound format, openai=OpenAI moderation format)"
)
@click.option(
    "--vendor", "-v",
    type=click.Choice(["humanbound", "openai"]),
    default="humanbound",
    help="Vendor format for guardrails export"
)
@click.option(
    "--model",
    type=str,
    default=None,
    help="Model to use for guardrails (e.g., gpt-4o-mini)"
)
@click.option(
    "--include-reasoning",
    is_flag=True,
    default=False,
    help="Include reasoning in guardrail responses"
)
def guardrails_command(output: str, output_format: str, vendor: str, model: str, include_reasoning: bool):
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
      hb guardrails --format=yaml            # Output as YAML
      hb guardrails --include-reasoning      # Include reasoning in output
    """
    runner = get_runner()
    is_platform = isinstance(runner, PlatformTestRunner)

    if not is_platform:
        _local_guardrails(output, output_format, vendor)
        return

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
            Path(output).write_text(formatted)
            console.print(f"[green]Guardrails exported to:[/green] {output}")
            console.print(f"[dim]Vendor: {vendor}[/dim]")
            console.print(f"[dim]Format: {output_format}[/dim]")
        else:
            print(formatted)

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


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
    insights = meta.get("insights", [])

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
        rules.append({
            "id": f"gr-{i+1:03d}",
            "threat_class": insight.get("category", "unknown"),
            "pattern": insight.get("explanation", "")[:200],
            "action": "block",
            "severity": insight.get("severity", "medium"),
            "source": f"{exp_dirs[0].name}",
        })

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
        Path(output).write_text(formatted)
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
        lines = ["# Humanbound Guardrails Configuration", f"version: {guardrails.get('version', '1.0')}", "rules:"]
        for rule in guardrails.get("rules", []):
            lines.append(f"  - id: {rule.get('id')}")
            lines.append(f"    type: {rule.get('type')}")
            lines.append(f"    severity: {rule.get('severity')}")
            lines.append(f"    category: {rule.get('category')}")
            lines.append(f"    action: {rule.get('action')}")
        return "\n".join(lines)
