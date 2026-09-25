# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb arena: run intentionally vulnerable AI agents locally and test them.

Every `hb` invocation imports this module to register the group, so it stays light:
the arena modules (and through them httpx, pydantic models, the gateway stack) are
imported inside the commands that need them.
"""

from __future__ import annotations

import contextlib
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
    from ..arena.runtime import RunningAgent

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


def _load_manifest_for_info(ref: str) -> ArenaManifest:
    """The manifest for `ref`, without ever installing it.

    'installed' means pulled/run, not merely browsed: unlike `_ensure_installed`,
    this never caches a fetched manifest to disk.
    """
    from ..arena import catalog
    from ..arena.manifest import ManifestError

    agent_id, _, version = ref.partition(":")
    try:
        found = catalog.installed(agent_id, version or None)
    except ManifestError:
        found = None  # a corrupt cached manifest: fetch it fresh instead
    if found:
        return found[0]
    loaded = _load_index()
    try:
        return catalog.read_manifest(catalog.resolve(loaded.index, ref), loaded.location)
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
        except (OSError, UnicodeDecodeError) as e:
            _fail(f"cannot read {keys.config_file()}: {e}")
        except ValueError as e:
            _fail(str(e))
        _ok(f"{key} saved")


@config_group.command("get")
@click.argument("key", required=False)
def config_get(key):
    """Show stored keys (values masked)."""
    from ..arena import keys

    try:
        values = keys.read_config()
    except (OSError, UnicodeDecodeError) as e:
        _fail(f"cannot read {keys.config_file()}: {e}")
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

    try:
        removed = keys.unset_value(key)
    except (OSError, UnicodeDecodeError) as e:
        _fail(f"cannot read {keys.config_file()}: {e}")
    if removed:
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

    m = _load_manifest_for_info(ref)
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


# ── lifecycle ──

_NOTICE = (
    "Arena agents are intentionally vulnerable. They run in Docker and are bound to "
    "127.0.0.1 only; don't expose them to a network."
)


def _first_run_notice() -> None:
    from ..arena.paths import arena_dir

    marker = arena_dir() / ".notice_shown"
    if marker.exists():
        return
    _say(_NOTICE, "yellow")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def _gateway_port(*, strict: bool = True) -> int | None:
    """HB_ARENA_PORT (default 11500). A malformed value fails the command; with
    strict=False it returns None instead (nothing could have been started there)."""
    from ..arena.paths import gateway_port

    try:
        return gateway_port()
    except ValueError as e:
        if not strict:
            return None
        _fail(str(e))


def _gateway_url() -> str:
    from ..arena.paths import gateway_url

    return gateway_url(_gateway_port())


def _ensure_gateway() -> str:
    from ..arena import daemon

    port = _gateway_port()
    try:
        return daemon.ensure_running(port)
    except daemon.GatewayError as e:
        _fail(str(e))


def _running_or_fail(agent_id: str) -> RunningAgent:
    from ..arena import runtime

    try:
        agent = runtime.find_running(agent_id)
    except runtime.DockerError as e:
        _fail(str(e))
    if agent is None:
        _fail(f"{agent_id} is not running → hb arena run {agent_id}")
    return agent


def _stop_gateway_if_idle() -> None:
    """Stop the gateway once no arena agent is left running."""
    from ..arena import daemon, runtime

    try:
        if runtime.list_running():
            return
    except runtime.DockerError:
        return
    port = _gateway_port(strict=False)
    if port is not None and daemon.stop_gateway(port):
        _ok("gateway stopped")


def _print_endpoints(agent_id: str, gateway: str) -> None:
    _say(f"  A2A agent card  {gateway}/a2a/{agent_id}/.well-known/agent-card.json")
    _say(f"  A2A endpoint    {gateway}/a2a/{agent_id}")
    _say(f"  OpenAI base URL {gateway}/v1   (model: arena/{agent_id})")
    _say(f"\n  Test it:  hb test --target arena://{agent_id}")


@arena_group.command("run")
@click.argument("ref")
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Extra KEY=VALUE file for the agent",
)
def run_command(ref, env_file):
    """Pull (if needed), start an agent and serve it through the gateway."""
    from ..arena import daemon, keys, runtime

    # Validate the gateway port before touching Docker or the catalog, so a bad
    # HB_ARENA_PORT fails fast instead of after a pull/start we'd have to unwind.
    port = _gateway_port()
    m, agent_dir = _ensure_installed(ref, refresh=False)
    _preflight(m)
    # Community agents never see the shell environment: their manifest could name
    # any variable (cloud credentials, tokens) and have it handed over.
    allow_shell = m.origin == "first-party"
    try:
        env, missing = keys.resolve_env(
            m.runtime.env.required, m.runtime.env.optional, env_file, allow_shell=allow_shell
        )
    except (OSError, UnicodeDecodeError, ValueError) as e:
        path = env_file or keys.config_file()
        _fail(f"cannot read {path}: {e}")
    if missing:
        hints = "\n".join(f"  hb arena config set {k}=..." for k in missing)
        note = (
            ""
            if allow_shell
            else "\n(the shell environment is not used for community agents; "
            "set keys with hb arena config set or pass --env-file)"
        )
        _fail(f"{m.id} needs {', '.join(missing)}:\n{hints}{note}")
    # Names only: values never reach the terminal.
    _say(f"Passing keys: {', '.join(sorted(env))}" if env else "Passing no keys", "dim")
    _first_run_notice()
    kind = runtime.kind_of(m)
    try:
        if m.source.image and not runtime.image_present(m.source.image):
            runtime.pull(m, agent_dir)
        with console.status(f"Starting {m.id} {m.version}..."):
            agent = runtime.start(m, agent_dir, env)
            runtime.wait_healthy(agent, m.runtime.health)
    except runtime.HealthTimeout as e:
        logs = ""
        try:
            logs = runtime.last_logs(m.id, kind)
        except runtime.DockerError:
            pass
        try:
            runtime.stop(m.id, kind)
        except runtime.DockerError:
            pass
        if logs.strip():
            console.print(logs, markup=False, highlight=False)
        _fail(f"{e} → hb arena logs {m.id}")
    except runtime.DockerError as e:
        _fail(str(e))
    try:
        gateway = daemon.ensure_running(port)
    except (daemon.GatewayError, ValueError) as e:
        # The agent is up but has no gateway to be reached through: don't leave it
        # running unreachable, and say so.
        with contextlib.suppress(runtime.DockerError):
            runtime.stop(m.id, kind)
        _fail(f"{e} (the agent was stopped)")
    telemetry.capture("arena_run", {"agent": m.id, "version": m.version})
    _ok(f"{m.id} {m.version} is running\n")
    _print_endpoints(m.id, gateway)


@arena_group.command("ps")
def ps_command():
    """Show running agents."""
    from ..arena import runtime

    try:
        agents = runtime.list_running()
    except runtime.DockerError as e:
        _fail(str(e))
    if not agents:
        _say("No arena agents running.", "dim")
        return
    gateway = _gateway_url()
    table = Table(show_header=True, header_style="bold")
    for col in ("ID", "VERSION", "A2A", "NATIVE"):
        table.add_column(col)
    for a in agents:
        table.add_row(
            *(Text(c) for c in (a.id, a.version, f"{gateway}/a2a/{a.id}", a.base_url or ""))
        )
    console.print(table)


@arena_group.command("logs")
@click.argument("agent_id")
@click.option("-f", "--follow", is_flag=True, help="Keep streaming new log lines")
@click.option("--tail", default=200, show_default=True, help="Lines to show from the end")
def logs_command(agent_id, follow, tail):
    """Show an agent's container logs."""
    from ..arena import runtime

    agent = _running_or_fail(agent_id)
    try:
        runtime.logs(agent.id, agent.kind, follow=follow, tail=tail)
    except runtime.DockerError as e:
        _fail(str(e))


@arena_group.command("stop")
@click.argument("agent_id", required=False)
@click.option("--all", "stop_all", is_flag=True, help="Stop every arena agent and the gateway")
def stop_command(agent_id, stop_all):
    """Stop an agent (the gateway stops when nothing is left running)."""
    from ..arena import daemon, runtime

    if not agent_id and not stop_all:
        _fail("give an agent id or --all")
    if stop_all:
        try:
            targets = runtime.list_running()
        except runtime.DockerError as e:
            # Docker being down doesn't mean the gateway is: stop it regardless, then
            # report the docker error.
            port = _gateway_port(strict=False)
            if port is not None:
                daemon.stop_gateway(port)
            _fail(str(e))
        try:
            for a in targets:
                runtime.stop(a.id, a.kind)
                _ok(f"{a.id} stopped")
        except runtime.DockerError as e:
            _fail(str(e))
        if not targets:
            _say("No arena agents running.", "dim")
    else:
        agent = _running_or_fail(agent_id)
        try:
            runtime.stop(agent.id, agent.kind)
        except runtime.DockerError as e:
            _fail(str(e))
        _ok(f"{agent.id} stopped")
    _stop_gateway_if_idle()


@arena_group.command("reset")
@click.argument("agent_id")
def reset_command(agent_id):
    """Recreate an agent from its image (clean state) and drop its conversations."""
    from ..arena import target as arena_target

    _running_or_fail(agent_id)
    gateway = _ensure_gateway()
    try:
        with console.status(f"Resetting {agent_id}..."):
            arena_target.reset_via_gateway(agent_id, gateway)
    except arena_target.TargetError as e:
        _fail(str(e))
    _ok(f"{agent_id} reset")


@arena_group.command("rm")
@click.argument("agent_id")
def rm_command(agent_id):
    """Remove an agent's images and cached manifest."""
    from ..arena import catalog, runtime
    from ..arena.manifest import ManifestError
    from ..arena.paths import arena_dir

    try:
        found = catalog.installed(agent_id)
    except ManifestError:
        found = None  # corrupt cache: still stop it and remove what's there
    if found is None and not (
        catalog.AGENT_ID_RE.match(agent_id) and (arena_dir() / "agents" / agent_id).is_dir()
    ):
        _fail(f"{agent_id} is not installed")
    try:
        running = runtime.find_running(agent_id)
        if running:
            runtime.stop(running.id, running.kind)
        if found is not None:
            runtime.remove_images(*found)
    except runtime.DockerError as e:
        _fail(str(e))
    try:
        catalog.remove_installed(agent_id)
    except catalog.CatalogError as e:
        _fail(str(e))
    _ok(f"{agent_id} removed")
    _stop_gateway_if_idle()


@arena_group.command("endpoint")
@click.argument("agent_id")
def endpoint_command(agent_id):
    """Print ready-to-paste ways to call a running agent."""
    import json

    from ..arena import target as arena_target

    _running_or_fail(agent_id)
    gateway = _gateway_url()
    _print_endpoints(agent_id, gateway)
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {"role": "ROLE_USER", "messageId": "m-1", "parts": [{"text": "Hello"}]}
        },
    }
    console.print("\n[bold]curl (A2A SendMessage)[/bold]")
    click.echo(
        f"curl -s {gateway}/a2a/{agent_id} -H 'Content-Type: application/json' "
        f"-H 'A2A-Version: 1.0' -d '{json.dumps(body)}'"
    )
    console.print("\n[bold]hb bot config[/bold] (hb test --endpoint)")
    click.echo(json.dumps(arena_target.bot_config(agent_id, gateway), indent=2))


@arena_group.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=None, help="Default: HB_ARENA_PORT or 11500")
def serve_command(host, port):
    """Run the gateway in the foreground.

    \b
    Other commands (hb arena run/stop/reset) find the gateway via HB_ARENA_PORT
    (default 11500): set HB_ARENA_PORT so hb arena run/stop/reset find it if you
    serve on a non-default --port.
    """
    from ..arena import daemon
    from ..arena.paths import LOOPBACK_HOSTS

    if host not in LOOPBACK_HOSTS:
        _say(
            "Warning: arena agents are intentionally vulnerable and will be reachable "
            "from your network.",
            "yellow",
        )
    resolved_port = port if port is not None else _gateway_port()
    if daemon.is_up(resolved_port):
        _fail(
            f"a gateway is already running on port {resolved_port} → "
            "hb arena stop --all or choose another --port"
        )
    daemon.serve(host, resolved_port)
