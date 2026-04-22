# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Docs command for opening Humanbound documentation."""

import webbrowser

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Documentation URLs
DOCS_URLS = {
    "home": "https://docs.humanbound.ai",
    "quickstart": "https://docs.humanbound.ai/quickstart",
    "cli": "https://docs.humanbound.ai/cli",
    "api": "https://docs.humanbound.ai/api",
    "owasp": "https://docs.humanbound.ai/owasp-llm-top-10",
    "firewall": "https://docs.humanbound.ai/firewall-oss",
    "examples": "https://docs.humanbound.ai/examples",
    "github": "https://github.com/Humanbound/humanbound-cli",
}


@click.command("docs")
@click.argument("topic", required=False, default="home")
@click.option(
    "--list",
    "-l",
    "list_topics",
    is_flag=True,
    help="List available documentation topics",
)
@click.option("--no-browser", "-n", is_flag=True, help="Don't open browser, just show URL")
def docs_command(topic: str, list_topics: bool, no_browser: bool):
    """Open Humanbound documentation in your browser.

    \b
    Topics:
      home       Main documentation site (default)
      quickstart Getting started guide
      cli        CLI reference
      api        API documentation
      owasp      OWASP LLM Top 10 testing guide
      firewall   Humanbound Firewall OSS library
      examples   Example configurations
      github     GitHub repository

    \b
    Examples:
      hb docs                    # Open main docs
      hb docs quickstart         # Open quickstart guide
      hb docs cli                # Open CLI reference
      hb docs --list             # List all topics
      hb docs api --no-browser   # Show API docs URL
    """
    if list_topics:
        _show_topics()
        return

    topic_lower = topic.lower()

    if topic_lower not in DOCS_URLS:
        console.print(f"[yellow]Unknown topic:[/yellow] {topic}")
        console.print(f"Available topics: {', '.join(DOCS_URLS.keys())}")
        console.print("\nUse 'hb docs --list' to see all topics with descriptions.")
        raise SystemExit(1)

    url = DOCS_URLS[topic_lower]

    if no_browser:
        console.print(f"[bold]Documentation URL:[/bold] {url}")
    else:
        console.print(f"[dim]Opening {topic} documentation...[/dim]")
        try:
            webbrowser.open(url)
            console.print(f"[green]Opened:[/green] {url}")
        except Exception as e:
            console.print(f"[yellow]Could not open browser:[/yellow] {e}")
            console.print(f"[bold]URL:[/bold] {url}")


def _show_topics():
    """Display available documentation topics."""
    console.print(
        Panel(
            "[bold]Humanbound Documentation[/bold]\n\n"
            "Use 'hb docs <topic>' to open documentation in your browser.",
            border_style="blue",
        )
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Topic", width=12)
    table.add_column("Description", width=40)
    table.add_column("URL", width=35)

    topics = [
        ("home", "Main documentation site", DOCS_URLS["home"]),
        ("quickstart", "Getting started guide", DOCS_URLS["quickstart"]),
        ("cli", "CLI command reference", DOCS_URLS["cli"]),
        ("api", "REST API documentation", DOCS_URLS["api"]),
        ("owasp", "OWASP LLM Top 10 testing", DOCS_URLS["owasp"]),
        ("firewall", "Firewall OSS library", DOCS_URLS["firewall"]),
        ("examples", "Example configurations", DOCS_URLS["examples"]),
        ("github", "GitHub repository", DOCS_URLS["github"]),
    ]

    for topic, desc, url in topics:
        table.add_row(topic, desc, f"[dim]{url}[/dim]")

    console.print(table)
    console.print("\n[dim]Example: hb docs quickstart[/dim]")
