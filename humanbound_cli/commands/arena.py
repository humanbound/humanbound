# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb arena: run intentionally vulnerable AI agents locally and test them.

Every `hb` invocation imports this module to register the group, so it stays light:
the arena modules (and through them httpx, pydantic models, the gateway stack) are
imported inside the commands that need them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .. import telemetry

if TYPE_CHECKING:
    from ..arena.catalog import LoadedIndex
    from ..arena.manifest import ArenaManifest

console = Console()


def _fail(message: str, code: int = 1) -> NoReturn:
    # Text, not markup: messages carry docker output and manifest text with "[...]" in it.
    console.print(Text(message, style="red"))
    raise SystemExit(code)


def _say(message: str, style: str | None = None) -> None:
    """Print literal text (no markup parsing, no highlighting)."""
    console.print(Text(message, style=style or ""))


def _ok(message: str) -> None:
    console.print(Text.assemble(("✓ ", "green"), message))


def _load_index() -> LoadedIndex:
    from ..arena import catalog

    try:
        loaded = catalog.load_index()
    except catalog.CatalogError as e:
        _fail(str(e))
    if loaded.stale:
        _say("Arena catalog unreachable; using the cached copy.", "yellow")
    return loaded


def _ensure_installed(ref: str, *, refresh: bool) -> tuple[ArenaManifest, Path]:
    """The cached manifest for `ref`, fetching it from the catalog when needed."""
    from ..arena import catalog
    from ..arena.manifest import ManifestError

    agent_id, _, version = ref.partition(":")
    if not refresh:
        try:
            found = catalog.installed(agent_id, version or None)
        except ManifestError:
            found = None  # a corrupt cached manifest: fetch it again
        if found:
            return found
    loaded = _load_index()
    try:
        return catalog.fetch_manifest(catalog.resolve(loaded.index, ref), loaded.location)
    except (catalog.CatalogError, ManifestError) as e:
        _fail(str(e))


def _preflight(m: ArenaManifest | None = None) -> None:
    from ..arena import runtime

    try:
        runtime.preflight(m)
    except runtime.DockerError as e:
        _fail(str(e))


@click.group("arena")
def arena_group():
    """Run intentionally vulnerable AI agents locally and test them.

    \b
      hb arena ls                                   # browse the catalog
      hb arena config set OPENAI_API_KEY=sk-...     # keys the agents need
      hb arena run <agent>                          # pull, start and serve over A2A
      hb test --target arena://<agent>              # test it (local engine, no login)
    """


# ── config ──


@arena_group.group("config")
def config_group():
    """Manage keys arena agents need (stored in ~/.humanbound/arena/arena.env, 0600)."""


@config_group.command("set")
@click.argument("pairs", nargs=-1, required=True)
def config_set(pairs):
    """Set one or more KEY=VALUE pairs."""
    from ..arena import keys

    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            # Echo only the part before any '=' so a mistyped secret is never printed.
            _fail(f"expected KEY=VALUE, got {key!r}")
        if keys.is_reserved(key):
            _fail(f"{key} is reserved for hb's own credentials and is never passed to agents")
        try:
            keys.set_value(key, value)
        except ValueError as e:
            _fail(str(e))
        _ok(f"{key} saved")


@config_group.command("get")
@click.argument("key", required=False)
def config_get(key):
    """Show stored keys (values masked)."""
    from ..arena import keys

    values = keys.read_config()
    if key:
        values = {key: values[key]} if key in values else {}
    if not values:
        _say("No arena keys stored.", "dim")
        return
    for k, v in values.items():
        _say(f"{k}={keys.mask(v)}")


@config_group.command("unset")
@click.argument("key")
def config_unset(key):
    """Remove a stored key."""
    from ..arena import keys

    if keys.unset_value(key):
        _ok(f"{key} removed")
    else:
        _say(f"{key} was not set", "dim")


# ── catalog ──


@arena_group.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def validate_command(path):
    """Validate an arena.yaml (arena fields and the embedded agent.yaml)."""
    from ..arena.manifest import ManifestError, load_manifest

    try:
        m = load_manifest(path)
    except ManifestError as e:
        _fail(str(e))
    _ok(f"{m.id} {m.version} is a valid arena.yaml")


@arena_group.command("ls")
@click.option("--installed", "installed_only", is_flag=True, help="Only agents pulled locally")
def ls_command(installed_only):
    """List catalog agents."""
    from ..arena import catalog, runtime

    try:
        running = {a.id for a in runtime.list_running()}
    except runtime.DockerError:
        running = set()
    installed_agents = catalog.list_installed()
    installed = {m.id for m in installed_agents}
    if installed_only:
        rows = [(m.id, m.version, m.difficulty, m.tags) for m in installed_agents]
    else:
        latest: dict[str, catalog.IndexEntry] = {}
        for e in _load_index().index.agents:
            current = latest.get(e.id)
            if current is None or catalog.version_key(e.version) > catalog.version_key(
                current.version
            ):
                latest[e.id] = e
        rows = [
            (e.id, e.version, e.difficulty, e.tags)
            for e in sorted(latest.values(), key=lambda e: e.id)
        ]
    if not rows:
        _say("No arena agents installed." if installed_only else "The catalog is empty.", "dim")
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("ID", "VERSION", "DIFFICULTY", "TAGS", "STATE"):
        table.add_column(col)
    for agent_id, version, difficulty, tags in rows:
        state = "running" if agent_id in running else ("installed" if agent_id in installed else "")
        table.add_row(*(Text(c) for c in (agent_id, version, difficulty, ", ".join(tags), state)))
    console.print(table)


@arena_group.command("info")
@click.argument("ref")
@click.option(
    "--agent-yaml", "as_agent_yaml", is_flag=True, help="Print only the embedded agent.yaml"
)
def info_command(ref, as_agent_yaml):
    """Show an agent's details, required keys and planted vulnerabilities."""
    import yaml

    m, _ = _ensure_installed(ref, refresh=False)
    if as_agent_yaml:
        click.echo(yaml.safe_dump(m.agent_yaml(), sort_keys=False, allow_unicode=True), nl=False)
        return
    console.print(
        Text.assemble((m.name, "bold"), f" ({m.id} {m.version}, {m.origin}, {m.difficulty})")
    )
    _say(m.description)
    if m.runtime.env.required:
        _say(f"\nRequired keys: {', '.join(m.runtime.env.required)}")
    if m.runtime.env.optional:
        _say(f"Optional keys: {', '.join(m.runtime.env.optional)}")
    if m.ground_truth:
        _say("\nPlanted vulnerabilities:")
        for key, gt in m.ground_truth.items():
            _say(f"  {key} [{gt.category}] {gt.description}")
    _say(f"\nRun it:   hb arena run {m.id}\nTest it:  hb test --target arena://{m.id}")


@arena_group.command("pull")
@click.argument("ref")
def pull_command(ref):
    """Download an agent's manifest and image(s)."""
    from ..arena import runtime

    m, agent_dir = _ensure_installed(ref, refresh=True)
    _preflight(m)
    try:
        runtime.pull(m, agent_dir)
    except runtime.DockerError as e:
        _fail(str(e))
    telemetry.capture("arena_pull", {"agent": m.id, "version": m.version})
    _ok(f"{m.id} {m.version} pulled")
