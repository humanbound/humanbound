# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Read-modify-write helper for scope.capabilities.

Backend contract (PR #34): PUT /projects/{id} fully replaces scope.
We must GET, merge our override into the existing scope, then PUT.

Also handles the dataset-archive warning + confirm UX so both consumers
(connect command, projects update command) behave identically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

import click

from humanbound_cli.extractors.capabilities import CAPABILITY_KEYS

_ARCHIVE_WARNING = (
    "Changing scope.capabilities will archive all current datasets "
    "for this project (regenerates test coverage plans). Continue?"
)


@dataclass
class WriteResult:
    no_op: bool
    cancelled: bool
    final_capabilities: dict[str, bool]


def merge_capabilities(current: dict | None, override: dict[str, bool]) -> dict:
    """Set-only merge. Unspecified known keys keep their current value;
    unknown keys in `current` are preserved untouched."""
    base = {key: False for key in CAPABILITY_KEYS}
    if current:
        base.update(current)
    base.update(override)
    return base


def diff_capabilities(old: dict, new: dict) -> list[tuple[str, bool, bool]]:
    """Return a sorted list of (key, old_value, new_value) for the 4 known keys."""
    return [
        (key, bool(old.get(key, False)), bool(new.get(key, False)))
        for key in sorted(CAPABILITY_KEYS)
    ]


def write_capabilities(
    client,
    project_id: str,
    override: dict[str, bool],
    *,
    yes: bool,
    console,
    confirm_callback: Callable[[str], bool] | None = None,
) -> WriteResult:
    """GET → validate → merge → no-op detect → confirm → PUT.

    Backend requires the full scope object (no PATCH; no deep merge).
    Side effect: changing scope archives all project datasets — surfaced
    as a confirm prompt unless `yes=True`.

    `confirm_callback` is for tests; in prod, click.confirm is used.
    """
    project = client.get_project(project_id)
    scope = dict(project.get("scope") or {})

    obs = scope.get("overall_business_scope") or ""
    if len(obs) < 20:
        console.print(
            "[red]Cannot update capabilities: project scope is incomplete.[/red]\n"
            "[dim]Run `hb connect --repo <path>` to bootstrap scope first, "
            "or set scope via the dashboard.[/dim]"
        )
        raise SystemExit(1)

    current_caps = scope.get("capabilities") or {}
    new_caps = merge_capabilities(current_caps, override)

    diff = diff_capabilities(current_caps, new_caps)
    if all(old == new for _key, old, new in diff):
        console.print("[dim]No changes — capabilities already match.[/dim]")
        return WriteResult(no_op=True, cancelled=False, final_capabilities=new_caps)

    _print_diff(console, diff)

    if not yes:
        confirmed = (confirm_callback or click.confirm)(_ARCHIVE_WARNING)
        if not confirmed:
            return WriteResult(
                no_op=False, cancelled=True, final_capabilities=current_caps or new_caps
            )

    scope["capabilities"] = new_caps
    client.update_project(project_id, {"scope": scope})

    console.print("[green]✓ Capabilities updated.[/green]")
    console.print("[dim]Backend will fire `capabilities.changed` webhook event.[/dim]")
    return WriteResult(no_op=False, cancelled=False, final_capabilities=new_caps)


def _print_diff(console, diff):
    console.print("\n[bold]Capability changes:[/bold]")
    for key, old, new in diff:
        marker = "→" if old != new else " "
        suffix = "" if old != new else " [dim](no change)[/dim]"
        console.print(f"  {key:<16} {str(old).lower():<5} {marker} {str(new).lower():<5}{suffix}")
    console.print("")
