# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""User-facing display of capability scan results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Optional

import click

from .types import CAPABILITY_KEYS, CapabilityScanResult

_MAX_EVIDENCE_PER_CAPABILITY = 3


def print_detected_capabilities(result: CapabilityScanResult, console) -> None:
    """Print the capability detection block to the console."""
    by_cap = defaultdict(list)
    for ev in result.evidence:
        by_cap[ev.capability].append(ev)

    console.print("\n[bold]Detected capabilities:[/bold]")
    for cap in CAPABILITY_KEYS:
        present = result.capabilities.get(cap, False)
        marker = "[green]✓[/green]" if present else "[dim]✗[/dim]"
        label = f"{marker} {cap:<16}"
        hits = by_cap.get(cap, [])

        if not hits:
            console.print(f"  {label} [dim](no signals)[/dim]")
            continue

        for i, ev in enumerate(hits[:_MAX_EVIDENCE_PER_CAPABILITY]):
            prefix = label if i == 0 else " " * len(f"  ✓ {cap:<16}")
            console.print(f"  {prefix} [dim]←[/dim] {ev.signal} [dim]at {ev.file}:{ev.line}[/dim]")

        extra = len(hits) - _MAX_EVIDENCE_PER_CAPABILITY
        if extra > 0:
            indent = " " * len(f"  ✓ {cap:<16}")
            console.print(f"  {indent}    [dim](+{extra} more)[/dim]")
    console.print("")


def prompt_empty_scan_choice(
    *,
    console,
    choice_callback: Callable[[], str] | None = None,
    bool_callback: Callable[[str], bool] | None = None,
) -> dict[str, bool] | None:
    """Run the 1/2/3 chooser when the scan found zero signals.

    Returns:
      None — option [1] (default): leave scope.capabilities unset.
      dict — option [2]: explicit per-capability values.
      Raises SystemExit on option [3] (cancel).

    The callbacks let tests inject answers without click.prompt input.
    """
    console.print("[bold]No capabilities detected.[/bold] Choose:")
    console.print(
        "  [1] Leave scope.capabilities unset (platform infers from business scope) [default]"
    )
    console.print("  [2] Set capabilities explicitly now")
    console.print("  [3] Cancel")

    choose = choice_callback or (lambda: click.prompt("Choice", default="1", show_default=False))
    choice = choose()

    if choice == "1":
        return None
    if choice == "3":
        console.print("[yellow]Cancelled.[/yellow]")
        raise SystemExit(1)
    if choice != "2":
        console.print(f"[red]Invalid choice: {choice!r}[/red]")
        raise SystemExit(1)

    ask = bool_callback or (lambda key: click.confirm(f"  {key}?", default=False))
    return {key: ask(key) for key in CAPABILITY_KEYS}
