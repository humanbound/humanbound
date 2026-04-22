# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Shared report download + open helper for entity-level report commands."""

import webbrowser
from pathlib import Path

from rich.console import Console

console = Console()


def download_and_open(
    client,
    endpoint: str,
    default_filename: str,
    output: str = None,
    no_open: bool = False,
    include_project: bool = False,
):
    """Download HTML report from backend and optionally open in browser.

    Args:
        client: HumanboundClient instance
        endpoint: API endpoint (e.g. "projects/{id}/report")
        default_filename: Default output filename
        output: Custom output path (overrides default)
        no_open: If True, save only without opening browser
        include_project: Include project_id header in request
    """
    try:
        with console.status("[dim]Generating report (this may take a moment)...[/dim]"):
            response = client.get(endpoint, timeout=120, include_project=include_project)
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            console.print("[red]Report generation timed out.[/red]")
            console.print(
                "[dim]The report endpoint is processing heavy data. Try again in a moment.[/dim]"
            )
        elif "connection refused" in error_msg.lower() or "newconnectionerror" in error_msg.lower():
            console.print("[red]Cannot connect to the server.[/red]")
            console.print("[dim]Make sure the server is running.[/dim]")
        else:
            console.print(f"[red]Error generating report:[/red] {e}")
        raise SystemExit(1)

    # Extract HTML content
    if isinstance(response, str):
        html = response
    elif isinstance(response, dict) and response.get("message"):
        html = response["message"]
    elif isinstance(response, dict) and response.get("html"):
        html = response["html"]
    elif isinstance(response, bytes):
        html = response.decode("utf-8")
    else:
        import json

        html = json.dumps(response, indent=2, default=str)

    filepath = Path(output or default_filename)
    filepath.write_text(html)
    console.print(f"[green]Report saved:[/green] {filepath}")

    if not no_open:
        webbrowser.open(f"file://{filepath.absolute()}")
