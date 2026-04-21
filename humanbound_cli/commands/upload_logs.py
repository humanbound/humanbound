# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Upload conversation logs command.

DEPRECATED: 'hb upload-logs' is deprecated in favour of 'hb logs upload'.
This module is kept for backward compatibility. Remove after v2.0.
"""

import json
import click
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()

# DEPRECATED: remove after v2.0 — replaced by 'hb logs upload'
_DEPRECATION_MSG = (
    "[yellow]Warning:[/yellow] 'hb upload-logs' is deprecated. "
    "Use [bold]hb logs upload[/bold] instead."
)


@click.command("upload-logs")
@click.argument("file", type=click.Path(exists=True))
@click.option("--tag", help="Tag for the dataset (used to reference in test runs)")
@click.option("--lang", help="Language of the conversations (e.g., english)")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def upload_logs_command(file: str, tag: str, lang: str, force: bool):
    """Upload conversation logs for evaluation.

    DEPRECATED: Use 'hb logs upload' instead. This command will be
    removed in a future version.

    FILE: Path to a JSON file containing conversations.

    \b
    Expected file format:
      [
        {
          "conversation": [
            {"u": "user message", "a": "bot response"},
            {"u": "follow up", "a": "bot reply"}
          ],
          "thread_id": "optional-id"
        },
        ...
      ]

    \b
    Examples:
      hb upload-logs conversations.json
      hb upload-logs conversations.json --tag prod-v2  # DEPRECATED: use 'hb logs upload' instead
      hb upload-logs conversations.json --lang english
    """
    # DEPRECATED: remove after v2.0
    console.print(_DEPRECATION_MSG)
    console.print()

    client = HumanboundClient()

    if not client.is_authenticated():
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    project_id = client.project_id
    if not project_id:
        console.print("[yellow]No project selected.[/yellow]")
        console.print("Use 'hb projects use <id>' to select a project first.")
        raise SystemExit(1)

    # Read and parse file
    file_path = Path(file)
    try:
        content = file_path.read_text()
        conversations = json.loads(content)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON file:[/red] {e}")
        raise SystemExit(1)

    if not isinstance(conversations, list):
        console.print("[red]File must contain a JSON array of conversations.[/red]")
        raise SystemExit(1)

    if not conversations:
        console.print("[yellow]File contains no conversations.[/yellow]")
        raise SystemExit(1)

    # Show summary
    console.print(f"  File: [bold]{file_path.name}[/bold]")
    console.print(f"  Conversations: [bold]{len(conversations)}[/bold]")
    if tag:
        console.print(f"  Tag: [bold]{tag}[/bold]")
    if lang:
        console.print(f"  Language: [bold]{lang}[/bold]")

    if not force:
        if not Confirm.ask(f"\nUpload {len(conversations)} conversations?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    try:
        with console.status(f"Uploading {len(conversations)} conversations..."):
            response = client.upload_conversations(project_id, conversations, tag=tag, lang=lang)

        console.print(f"\n[green]Upload complete.[/green]")

        dataset_id = response.get("dataset_id", response.get("id", ""))
        if dataset_id:
            console.print(f"  Dataset ID: [bold]{dataset_id}[/bold]")

        test_category = response.get("test_category", "")
        if test_category:
            console.print(f"  Test category: [bold]{test_category}[/bold]")
            console.print(f"\n[dim]Run evaluation with: hb test --category \"{test_category}\"[/dim]")

    except NotAuthenticatedError:
        console.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
