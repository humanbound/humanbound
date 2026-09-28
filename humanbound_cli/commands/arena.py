# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb arena`: run intentionally vulnerable AI agents locally and test them.

Arena modules (and yaml/json) are imported inside functions so `hb` startup stays cheap.
All user-facing and manifest text is printed without Rich markup interpretation.
"""

from __future__ import annotations

import sys
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


# ── output ──


def _say(msg: str, style: str | None = None) -> None:
    console.print(Text(msg, style=style or ""))


def _warn(msg: str) -> None:
    _say(msg, "yellow")


def _ok(msg: str) -> None:
    _say(msg, "green")


def _fail(msg: str, code: int = 1) -> NoReturn:
    if "\n" in msg:  # a list (e.g. container baseline problems): one item per line, unwrapped
        console.print(Text(msg, style="red"), soft_wrap=True)
    else:
        _say(msg, "red")
    raise SystemExit(code)


# ── helpers ──


def _load_index() -> LoadedIndex:
    from ..arena import catalog

    try:
        loaded = catalog.load_index()
    except catalog.CatalogError as e:
        _fail(str(e))
    if loaded.stale:
        _warn(f"couldn't reach {loaded.location}; showing the cached catalog")
    return loaded


def _ensure_installed(ref: str, *, refresh: bool) -> tuple[ArenaManifest, Path]:
    """The installed manifest for `ref`, fetching (and caching) it when needed.

    An install without a provenance record (from an older hb) is fetched again, so hb knows
    which catalog it came from; if that fails it is used as is (and treated as untrusted).
    """
    from ..arena import catalog
    from ..arena.manifest import ManifestError

    if not refresh:
        agent_id, _, version = ref.partition(":")
        try:
            found = catalog.installed(agent_id, version or None)
        except ManifestError:
            found = None  # a corrupt cache: fetch it again
        if found is not None:
            if catalog.read_provenance(found[1]) is not None:
                return found
            try:
                loaded = catalog.load_index()
                entry = catalog.resolve(loaded.index, f"{agent_id}:{found[0].version}")
                return catalog.fetch_manifest(entry, loaded.location)
            except (catalog.CatalogError, ManifestError, OSError):
                return found
    loaded = _load_index()
    try:
        return catalog.fetch_manifest(catalog.resolve(loaded.index, ref), loaded.location)
    except (catalog.CatalogError, ManifestError) as e:
        _fail(str(e))
    except OSError as e:
        _fail(f"cannot install {ref}: {e}")


def _load_manifest_for_info(ref: str) -> tuple[ArenaManifest, tuple]:
    """The installed manifest if there is one, else the catalog's. Never writes.

    Also returns the images (ImagePin: ref + digest) the catalog published for it: from the
    install record for an installed agent, else from the index entry.
    """
    from ..arena import catalog
    from ..arena.manifest import ManifestError

    agent_id, _, version = ref.partition(":")
    try:
        found = catalog.installed(agent_id, version or None)
    except ManifestError:
        found = None
    if found is not None:
        m, agent_dir = found
        provenance = catalog.read_provenance(agent_dir)
        return m, provenance.images if provenance else ()
    loaded = _load_index()
    try:
        entry = catalog.resolve(loaded.index, ref)
        return catalog.read_manifest(entry, loaded.location), tuple(entry.images)
    except (catalog.CatalogError, ManifestError) as e:
        _fail(str(e))


def _developer_line(m: ArenaManifest) -> str:
    dev = m.developer
    line = f"{dev.name} ({dev.url})"
    return f"{line}, contact: {dev.contact}" if dev.contact else line


def _preflight(m: ArenaManifest):
    """runtime.preflight's DockerInfo (None from a test double)."""
    from ..arena import runtime

    try:
        return runtime.preflight(m)
    except runtime.DockerError as e:
        _fail(str(e))


def _warn_if_loopback_exposed(info) -> None:
    from ..arena import runtime

    if info is not None and runtime.loopback_ports_exposed(info):
        _warn(
            f"Docker Engine {info.server_version} on Linux: ports published on 127.0.0.1 "
            "(like this intentionally vulnerable agent's) may be reachable from your local "
            "network on engines before 28; upgrade to Docker Engine 28 or later."
        )


def _gateway_port(strict: bool = True) -> int:
    """HB_ARENA_PORT (default 11500). Invalid: fail when strict, else use the default."""
    from ..arena import paths

    try:
        return paths.gateway_port()
    except ValueError as e:
        if strict:
            _fail(str(e))
        return paths.DEFAULT_GATEWAY_PORT


def _read_keys() -> dict[str, str]:
    from ..arena import keys

    try:
        return keys.read_config()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        _fail(f"cannot read {keys.config_file()}: {e}")


def _running_or_fail(agent_id: str, *, include_stopped: bool = False) -> RunningAgent:
    from ..arena import catalog, runtime

    try:
        agent = runtime.find_running(agent_id, include_stopped=include_stopped)
    except runtime.DockerError as e:
        _fail(str(e))
    if agent is None:
        _fail(catalog.not_running_message(agent_id))
    return agent


def _agent_dir(agent: RunningAgent) -> Path | None:
    """Our cached files for a running compose agent's version, if any: `docker compose` runs
    only on them (never on a compose file in the current directory)."""
    from ..arena import catalog
    from ..arena.manifest import ManifestError

    if agent.kind != "compose":
        return None
    try:
        found = catalog.installed(agent.id, agent.version or None)
    except (ManifestError, OSError):
        return None
    return Path(found[1]) if found else None


def _ensure_gateway(port: int) -> str:
    from ..arena import daemon

    try:
        return daemon.ensure_running(port)
    except daemon.GatewayError as e:
        _fail(str(e))


def _stop_gateway_if_idle(port: int) -> None:
    """Stop the gateway when no arena agent is left running (unknown if Docker is down)."""
    from ..arena import daemon, runtime

    try:
        if runtime.list_running():
            return
    except runtime.DockerError:
        return
    if daemon.stop_gateway(port):
        _say("gateway stopped")


def _legacy_hint() -> None:
    """Point at arena containers from an hb before owners: no owner sees them otherwise."""
    from ..arena import runtime

    try:
        legacy = {(a.id, a.name) for a in runtime.legacy_agents()}
    except runtime.DockerError:
        return
    if legacy:
        n = len(legacy)
        _warn(
            f"{n} arena container{'s' if n != 1 else ''} from an older hb → "
            "hb arena stop --all --any-owner"
        )


def _print_endpoints(agent_id: str, gateway: str, token: str | None = None) -> None:
    _say(f"  A2A agent card:   {gateway}/a2a/{agent_id}/.well-known/agent-card.json")
    _say(f"  A2A endpoint:     {gateway}/a2a/{agent_id}")
    _say(f"  OpenAI base URL:  {gateway}/v1  (model: arena/{agent_id})")
    if token:
        # click.echo: never wrapped, so the token can be copied in one piece.
        click.echo(f"  Access token:     {token}")
        click.echo("    send it as 'Authorization: Bearer <token>' (or 'X-Arena-Token: <token>');")
        click.echo(f"    OpenAI-compatible tools: OPENAI_API_KEY={token}")
    else:
        _say(f"  Access token:     required; hb arena endpoint {agent_id} prints it")


# ── group ──


# Commands that drive Docker (the others only read the catalog or the key store).
DOCKER_COMMANDS = frozenset(
    {"pull", "run", "ps", "logs", "stop", "reset", "rm", "endpoint", "serve", "check"}
)
# `hb arena check` exits 2 when it can't check (1 means problems were found).
CHECK_CANNOT_RUN = 2
IN_HB_IMAGE = (
    "hb arena can't run inside the hb Docker image: it starts agents with Docker on your "
    "machine, which the container can't reach. Install hb on the host instead: "
    "pip install humanbound"
)


@click.group("arena")
@click.pass_context
def arena_group(ctx: click.Context):
    """Run intentionally vulnerable AI agents locally and test them.

    \b
    hb arena ls / config set OPENAI_API_KEY=sk-... / run <agent> / hb test --target arena://<agent>
    """
    import os

    if ctx.invoked_subcommand not in DOCKER_COMMANDS:
        return
    code = CHECK_CANNOT_RUN if ctx.invoked_subcommand == "check" else 1
    if os.environ.get("HB_DOCKER_IMAGE"):
        _fail(IN_HB_IMAGE, code)
    if ctx.invoked_subcommand != "stop":  # stop --all still stops the gateway without Docker
        from ..arena import runtime

        if runtime.docker_cli() is None:
            _fail(runtime.DOCKER_MISSING, code)


# ── config ──


@arena_group.group("config")
def config_group():
    """Manage the keys arena agents need (~/.humanbound/arena/arena.env)."""


@config_group.command("set")
@click.argument("pairs", nargs=-1, required=True, metavar="KEY=VALUE...")
def config_set(pairs: tuple[str, ...]):
    """Store one or more keys, e.g. OPENAI_API_KEY=sk-..."""
    from ..arena import keys

    parsed: list[tuple[str, str]] = []
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            # Without '=' the whole argument may be the secret itself: only echo a name.
            shown = f"'{key}=…'" if keys.is_valid_name(key) else "a value without a KEY= name"
            _fail(f"expected KEY=VALUE, got {shown}")
        if keys.is_reserved(key):
            _fail(f"{key} is reserved for hb's own credentials")
        parsed.append((key, value))
    _read_keys()
    for key, value in parsed:
        try:
            keys.set_value(key, value)
        except ValueError as e:
            _fail(str(e))
        except OSError as e:
            _fail(f"cannot write {keys.config_file()}: {e}")
        _ok(f"✓ {key} saved")


@config_group.command("get")
@click.argument("key", required=False)
def config_get(key: str | None):
    """Show stored keys (masked)."""
    from ..arena import keys

    values = _read_keys()
    if key:
        if key not in values:
            _fail(f"{key} is not set")
        _say(f"{key}={keys.mask(values[key])}")
        return
    if not values:
        _say("No arena keys stored.")
        return
    for name, value in values.items():
        _say(f"{name}={keys.mask(value)}")


@config_group.command("unset")
@click.argument("key")
def config_unset(key: str):
    """Remove a stored key."""
    from ..arena import keys

    _read_keys()
    try:
        removed = keys.unset_value(key)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        _fail(f"cannot update {keys.config_file()}: {e}")
    if removed:
        _ok(f"✓ {key} removed")
    else:
        _say(f"{key} is not set")


# ── validate ──


@arena_group.command("validate")
@click.argument("path", type=click.Path(path_type=Path))
def validate_cmd(path: Path):
    """Validate an arena.yaml (and, for compose agents, its compose file)."""
    from ..arena import catalog, runtime
    from ..arena.manifest import ManifestError, load_manifest

    try:
        m = load_manifest(path)
    except ManifestError as e:
        _fail(str(e))
    folder_name = Path(path).resolve().parent.name
    if folder_name != m.id:
        _fail(
            f"the folder holding arena.yaml must be named after its id: expected '{m.id}', "
            f"got '{folder_name}' (the catalog serves agents from agents/<id>/arena.yaml)"
        )
    if m.source.compose:
        try:
            catalog.check_compose_path(m.source.compose)
        except catalog.CatalogError as e:
            _fail(str(e))
        folder = Path(path).parent
        try:
            runtime.checked_services(m, folder, folder / m.source.compose, allow_dotenv=True)
        except runtime.DockerError as e:
            _fail(str(e))
    _ok(f"✓ {m.id} {m.version} is a valid arena.yaml")


# ── ls / info ──


@arena_group.command("ls")
@click.option("--installed", "only_installed", is_flag=True, help="Only installed agents.")
def ls_cmd(only_installed: bool):
    """List catalog agents (or only installed ones)."""
    from ..arena import catalog, runtime

    installed = catalog.list_installed()
    installed_ids = {m.id for m in installed}
    try:
        running_ids = {a.id for a in runtime.list_running()}
    except runtime.DockerError:
        running_ids = set()  # Docker down: leave STATE blank

    rows: list[tuple[str, str, str, list[str]]] = []
    if only_installed:
        rows = [(m.id, m.version, m.difficulty, m.tags) for m in installed]
    else:
        index = _load_index().index
        latest: dict = {}
        for entry in index.agents:
            best = latest.get(entry.id)
            if best is None or catalog.version_key(entry.version) > catalog.version_key(
                best.version
            ):
                latest[entry.id] = entry
        rows = [(e.id, e.version, e.difficulty, e.tags) for e in latest.values()]
    if not rows:
        _say("No agents found.")
        return

    table = Table()
    for column in ("ID", "VERSION", "DIFFICULTY", "TAGS", "STATE"):
        table.add_column(column)
    for agent_id, version, difficulty, tags in sorted(rows):
        state = (
            "running"
            if agent_id in running_ids
            else "installed"
            if agent_id in installed_ids
            else ""
        )
        table.add_row(
            Text(agent_id), Text(version), Text(difficulty), Text(", ".join(tags)), Text(state)
        )
    console.print(table)


@arena_group.command("info")
@click.argument("ref")
@click.option("--agent-yaml", is_flag=True, help="Print only the embedded agent.yaml.")
def info_cmd(ref: str, agent_yaml: bool):
    """Show an agent's details, required keys and planted vulnerabilities."""
    import yaml

    m, images = _load_manifest_for_info(ref)
    if agent_yaml:
        click.echo(yaml.safe_dump(m.agent_yaml(), sort_keys=False, allow_unicode=True), nl=False)
        return

    _say(m.name, "bold")
    _say(f"id: {m.id}   version: {m.version}   difficulty: {m.difficulty}")
    _say(f"developer: {_developer_line(m)}")
    if m.source.upstream:
        up = m.source.upstream
        license_note = f" ({up.license})" if up.license else ""
        _say(f"upstream: {up.repo} @ {up.ref}{license_note}")
    if images:
        _say("images:")
        for pin in images:
            _say(f"  {pin.ref}  {pin.digest}")
    if m.tags:
        _say(f"tags: {', '.join(m.tags)}")
    _say("")
    _say(m.description)
    _say("")
    required, optional = m.runtime.env.required, m.runtime.env.optional
    _say(f"Required keys: {', '.join(required) if required else 'none'}")
    if optional:
        _say(f"Optional keys: {', '.join(optional)}")
    _say(f"Network: {_network_summary(m)}")
    if m.ground_truth:
        _say("")
        _say("Planted vulnerabilities:")
        for vid, gt in m.ground_truth.items():
            _say(f"  {vid} [{gt.category}] {gt.title or gt.description}")
            if gt.references:
                _say(f"      references: {', '.join(gt.references)}")
    _say("")
    _say(f"Run it:   hb arena run {m.id}")
    _say(f"Test it:  hb test --target arena://{m.id}")


def _network_summary(m: ArenaManifest) -> str:
    """What the agent may reach, before its keys are known (hb arena info)."""
    from ..arena import egress

    parts = []
    if egress.uses_model([*m.runtime.env.required, *m.runtime.env.optional]):
        parts.append(
            f"its model (api.openai.com:443, or the host and port of {egress.MODEL_URL_KEY})"
        )
    parts += [f"{host}:{port}" for host, port in map(egress.parse_entry, m.runtime.egress or ())]
    if not parts:
        return "blocked (it may reach nothing)"
    return "blocked, except " + ", ".join(parts)


# ── pull ──


@arena_group.command("pull")
@click.argument("ref")
def pull_cmd(ref: str):
    """Install an agent (id or id:version) and pull its image(s)."""
    from ..arena import runtime

    m, agent_dir = _ensure_installed(ref, refresh=True)
    _preflight(m)
    try:
        runtime.pull(m, agent_dir)
        runtime.pull_door_image()  # hb's proxy next to the agent
    except runtime.DockerError as e:
        _fail(str(e))
    telemetry.capture("arena_pull", _telemetry_props(m, agent_dir))
    _ok(f"✓ {m.id} {m.version} pulled")


# ── run ──


def _telemetry_props(m: ArenaManifest, agent_dir: Path) -> dict:
    """Agent id and version for the default catalog only; other catalogs stay anonymous."""
    from ..arena import catalog

    if catalog.is_trusted(agent_dir):
        return {"agent": m.id, "version": m.version}
    return {"agent": "custom"}


NOTICE = (
    "Arena agents are intentionally vulnerable. Their isolation is best effort: use them at "
    "your own risk.\n"
    "Never run them where there is sensitive data or access to critical systems.\n"
    "They are bound to 127.0.0.1; don't expose them to a network."
)
GATEWAY_NOTICE = (
    "This Docker can't take the gateway address off the agent's network: the agent may "
    "reach what the Docker host serves on all interfaces. A newer Docker closes this."
)
PROXY_HINT = (
    "This agent's only way out is hb's proxy (HTTP_PROXY / HTTPS_PROXY are set for it): a "
    "client that ignores those variables can't connect at all."
)
UNTRUSTED_SHELL_HINT = (
    "this agent is not from the default Humanbound catalog, so its keys are not read from "
    "your shell; use hb arena config set or --env-file"
)
LLM_ONLY_SHELL_HINT = (
    "only LLM keys (such as OPENAI_API_KEY) are read from your shell; set the others with "
    "hb arena config set or --env-file"
)


def _interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _image_refs(m: ArenaManifest, agent_dir: Path) -> list[str]:
    from ..arena import compose_safety

    if m.source.image:
        return [m.source.image]
    try:
        services = compose_safety.checked_services(m, agent_dir)
    except compose_safety.DockerError as e:
        _fail(str(e))
    return list(dict.fromkeys(spec["image"] for spec in services.values()))


def _confirm_untrusted(
    m: ArenaManifest,
    agent_dir: Path,
    key_names: list[str],
    yes: bool,
    network: str,
) -> None:
    """Ask once per id@version (and manifest, compose file, digests) before running an agent
    that isn't from the default catalog. --yes accepts; without a terminal, --yes is
    required."""
    from ..arena import catalog, consent

    if consent.is_accepted(m, agent_dir):
        return
    if not yes:
        provenance = catalog.read_provenance(agent_dir)
        where = provenance.index if provenance else "an unknown catalog"
        _warn(
            f"{m.name} ({m.id} {m.version}) is not from the default Humanbound catalog (it "
            f"comes from {where}). It will run on your machine, in Docker:"
        )
        _say(f"  developer: {m.developer.name} ({m.developer.url})")
        if m.developer.contact:
            _say(f"  contact:   {m.developer.contact}")
        if m.source.upstream:
            up = m.source.upstream
            _say(f"  upstream:  {up.repo} @ {up.ref}")
            _say(f"  license:   {up.license or 'not stated'}")
        digests = {pin.ref: pin.digest for pin in (provenance.images if provenance else ())}
        for i, image in enumerate(_image_refs(m, agent_dir)):
            label = "  images:    " if i == 0 else "             "
            _say(f"{label}{image}  {digests[image]}" if image in digests else label + image)
        _say(f"  keys:      {', '.join(key_names) if key_names else 'none'}")
        _say(f"  network:   {network}")
        if not _interactive():
            _fail(
                f"confirm {m.id} {m.version} before its first run: re-run with --yes to "
                "accept it (hb remembers the answer)"
            )
        if not click.confirm("Run it?", default=False):
            _fail("not started")
    try:
        consent.accept(m, agent_dir)
    except OSError as e:
        _warn(f"couldn't remember the confirmation: {e}")


def _show_notice() -> None:
    for line in NOTICE.splitlines():
        _warn(line)


@arena_group.command("run")
@click.argument("ref")
@click.option(
    "--env-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="KEY=VALUE file with the agent's keys (wins over arena.env and the shell).",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Don't ask before the first run of an agent from a catalog other than the default one.",
)
def run_cmd(ref: str, env_file: Path | None, yes: bool):
    """Start an agent (id or id:version) and make it reachable through the gateway.

    Only agents from the default Humanbound catalog may read LLM keys from your shell;
    agents from any other catalog (HB_ARENA_INDEX) are confirmed once before their first run.

    An agent's network access is blocked, except for its model (api.openai.com, or the host
    and port of OPENAI_BASE_URL) and the hosts its manifest lists (hb arena info shows them).
    Its web traffic goes through a proxy hb runs next to it. An allowed destination is still
    a way out, and a container is not a virtual machine.
    """
    from ..arena import catalog, daemon, egress, keys, runtime, target

    port = _gateway_port()
    m, agent_dir = _ensure_installed(ref, refresh=False)
    trusted = catalog.is_trusted(agent_dir)
    docker_info = _preflight(m)

    _read_keys()
    try:
        env, missing = keys.resolve_env(
            m.runtime.env.required,
            m.runtime.env.optional,
            env_file,
            allow_shell=trusted,
        )
    except (OSError, UnicodeDecodeError) as e:
        _fail(f"cannot read {env_file or keys.config_file()}: {e}")
    except ValueError as e:
        _fail(str(e))  # names the key, never the value
    if missing:
        lines = [f"{m.id} needs keys that are not set:"]
        lines += [f"  hb arena config set {k}=..." for k in missing]
        if not trusted:
            lines.append(UNTRUSTED_SHELL_HINT)
        elif any(k not in keys.SHELL_KEYS for k in missing):
            lines.append(LLM_ONLY_SHELL_HINT)
        _fail("\n".join(lines))
    try:
        destinations = runtime.allowed_destinations(m, env)
    except runtime.DockerError as e:
        _fail(str(e))
    network = f"blocked, except {egress.describe(destinations)}"
    if egress.uses_model(env) and not any(d.source == egress.MODEL for d in destinations):
        _warn(
            f"{egress.MODEL_URL_KEY} points at localhost, which inside a container is the "
            "agent itself. For a model on this machine use host.docker.internal."
        )
    if not trusted:
        _confirm_untrusted(m, agent_dir, list(env), yes, network)
    _say(f"Passing keys: {', '.join(env)}" if env else "Passing no keys")
    _say(f"Network: {network}")
    _show_notice()
    _warn_if_loopback_exposed(docker_info)

    kind = runtime.kind_of(m)
    try:
        if m.source.image and not runtime.image_present(m.source.image):
            runtime.pull(m, agent_dir)
        runtime.pull_door_image()
        _say(f"Starting {m.id} {m.version}…")
        agent = runtime.start(m, agent_dir, env)
        runtime.wait_healthy(agent, m.runtime.health)
    except runtime.HealthTimeout as e:
        tail = runtime.last_logs(m.id, kind, 50, agent_dir=agent_dir)
        if tail.strip():
            console.print(tail.rstrip(), markup=False, highlight=False)
        refused = runtime.refused_destinations(m.id)
        try:
            runtime.stop(m.id, kind, agent_dir=agent_dir)
        except runtime.DockerError:
            pass
        if refused:
            _warn(f"It tried to reach, and hb refused: {', '.join(refused)}")
        _warn(PROXY_HINT)
        # The containers are already stopped, so `hb arena logs` would show nothing.
        _fail(f"{e} (see the agent's logs above)")
    except runtime.DockerError as e:
        _fail(str(e))
    except (OSError, ValueError) as e:
        _fail(f"cannot start {m.id}: {e}")

    gateway_was_up = daemon.is_up(port)
    try:
        gateway = daemon.ensure_running(port)
    except daemon.GatewayError as e:
        try:
            runtime.stop(m.id, kind, agent_dir=agent_dir)
        except runtime.DockerError:
            pass
        _fail(f"{e} (the agent was stopped)")
    if gateway_was_up:
        # A running gateway may hold conversations with (and the port of) the old container.
        try:
            target.forget_via_gateway(m.id, gateway)
        except target.TargetError:
            pass

    telemetry.capture("arena_run", _telemetry_props(m, agent_dir))
    if agent.gateway_reachable:
        _warn(GATEWAY_NOTICE)
    _ok(f"✓ {m.id} {m.version} is running")
    _print_endpoints(m.id, gateway)
    _say(f"Test it:  hb test --target arena://{m.id}")


# ── check ──


def _cannot_check(msg: str) -> NoReturn:
    click.echo(msg, err=True)
    raise SystemExit(CHECK_CANNOT_RUN)


@arena_group.command("check")
@click.argument("agent_id")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
def check_cmd(agent_id: str, as_json: bool):
    """Check a running agent's containers against the container baseline.

    \b
    Every container of the agent, side services included, must:
      run as a user other than root; not be privileged;
      drop all Linux capabilities and add none; set no-new-privileges;
      share no namespace with the host; mount no host path or device;
      publish ports on 127.0.0.1 only (or publish nothing);
      be only on networks that have no route out.

    hb runs the same check before it reports an agent ready (hb arena run, reset) and before
    hb test --target arena://<id>, and stops an agent that fails it. This command only
    reports: it never stops anything.

    \b
    Exit codes:
      0  every container meets the container baseline
      1  problems found, one per line: <container>: <rule>: <problem>
      2  the agent isn't running, or Docker is unusable

    It checks configuration only: not what the agent does, and not what it sends to the
    destinations it may reach. Arena agents are intentionally vulnerable and their isolation
    is best effort: use them at your own risk, and never where there is sensitive data or
    access to critical systems.
    """
    import json

    from ..arena import baseline, catalog, runtime
    from ..arena.manifest import AGENT_ID_RE

    if not AGENT_ID_RE.fullmatch(agent_id):
        _cannot_check(catalog.not_running_message(agent_id))
    try:
        runtime.preflight()
        if runtime.find_running(agent_id) is None:
            _cannot_check(catalog.not_running_message(agent_id))
        containers = runtime.agent_containers(agent_id)
        networks = runtime.agent_networks(containers)
    except runtime.DockerError as e:
        _cannot_check(str(e))
    violations = baseline.check(containers, networks)
    names = [baseline.container_name(c, i) for i, c in enumerate(containers)]
    if as_json:
        report = {
            "agent": agent_id,
            "containers": names,
            "violations": [v.as_dict() for v in violations],
        }
        click.echo(json.dumps(report, indent=2))
    elif violations:
        for v in violations:
            click.echo(str(v))  # never wrapped: one problem per line
        n = len(violations)
        click.echo(
            f"✗ {agent_id} does not meet the container baseline: "
            f"{n} problem{'s' if n != 1 else ''}",
            err=True,
        )
    else:
        n = len(names)
        verb = "container meets" if n == 1 else "containers meet"
        click.echo(f"✓ {agent_id}: {n} {verb} the container baseline")
    if violations:
        raise SystemExit(1)


# ── ps / logs ──


@arena_group.command("ps")
def ps_cmd():
    """List running arena agents."""
    from ..arena import runtime
    from ..arena.paths import gateway_url

    try:
        agents = runtime.list_running()
    except runtime.DockerError as e:
        _fail(str(e))
    if not agents:
        _say("No arena agents running.")
        _legacy_hint()
        return
    gateway = gateway_url(_gateway_port())
    table = Table()
    for column in ("ID", "VERSION", "A2A", "NATIVE"):
        table.add_column(column)
    for a in sorted(agents, key=lambda a: a.id):
        table.add_row(
            Text(a.id), Text(a.version), Text(f"{gateway}/a2a/{a.id}"), Text(a.base_url or "")
        )
    console.print(table)
    _legacy_hint()


@arena_group.command("logs")
@click.argument("agent_id")
@click.option("-f", "--follow", is_flag=True, help="Follow the log output.")
@click.option("--tail", default=200, show_default=True, help="Lines to show.")
@click.option(
    "--door",
    is_flag=True,
    help="Show what the agent reached or was refused on the network, not the agent's own logs.",
)
def logs_cmd(agent_id: str, follow: bool, tail: int, door: bool):
    """Show an agent's container logs.

    With --door: one line per destination the agent tried through hb's proxy, "allowed",
    "blocked" or "failed", then host:port.
    """
    from ..arena import runtime

    agent = _running_or_fail(agent_id)
    try:
        if door:
            runtime.door_logs(agent_id, follow=follow, tail=tail)
            return
        runtime.logs(agent_id, agent.kind, follow=follow, tail=tail, agent_dir=_agent_dir(agent))
    except runtime.DockerError as e:
        _fail(str(e))
    except KeyboardInterrupt:
        pass


# ── stop / reset / rm ──


@arena_group.command("stop")
@click.argument("agent_id", required=False)
@click.option(
    "--all", "stop_all", is_flag=True, help="Stop all of your arena agents and your gateway."
)
@click.option(
    "--any-owner",
    is_flag=True,
    help="With --all: also stop agents started from other HOMEs (users, sessions) on this Docker.",
)
def stop_cmd(agent_id: str | None, stop_all: bool, any_owner: bool):
    """Stop an agent (or --all of yours). Your gateway stops when none of yours is left.

    Agents belong to the HOME that started them: other users or sessions on the same Docker
    are never touched unless you add --any-owner to --all.
    """
    from ..arena import daemon, paths, runtime

    if any_owner and not stop_all:
        _fail("--any-owner only works with --all (hb arena stop --all --any-owner)")
    if not agent_id and not stop_all:
        _fail("give an agent id or --all")
    port = _gateway_port(strict=False)
    # Stopped or exited containers count too: their network and keys file need cleaning up.
    if stop_all:
        try:
            agents = runtime.list_running(include_stopped=True, any_owner=any_owner)
        except runtime.DockerError as e:
            if daemon.stop_gateway(port):
                _say("gateway stopped")
            _fail(str(e))
        if not agents:
            _say("No arena agents running.")
        if any_owner:
            mine = paths.arena_owner()
            others = {(a.owner, a.id) for a in agents if a.owner not in (mine, "")}
            legacy = {a.id for a in agents if not a.owner}
            parts = []
            if others:
                n = len(others)
                parts.append(f"{n} agent{'s' if n != 1 else ''} from other owners")
            if legacy:
                parts.append(f"{len(legacy)} from an older hb")
            if parts:
                _warn(
                    f"--any-owner: also stopping {' and '.join(parts)} (other HOMEs, users or "
                    "sessions on this Docker); their gateways keep running."
                )
        seen: set[tuple[str, str]] = set()
        for a in agents:
            if (a.owner, a.id) in seen:
                continue
            seen.add((a.owner, a.id))
            try:
                if any_owner:
                    runtime.stop(a.id, a.kind, owner=a.owner, name=a.name or None)
                else:
                    runtime.stop(a.id, a.kind, agent_dir=_agent_dir(a))
            except runtime.DockerError as e:
                _fail(str(e))
            _ok(f"✓ {a.id} stopped")
        runtime.remove_doors(any_owner=any_owner)
        if not any_owner:
            _legacy_hint()
    else:
        agent = _running_or_fail(agent_id, include_stopped=True)
        try:
            runtime.stop(agent.id, agent.kind, agent_dir=_agent_dir(agent))
        except runtime.DockerError as e:
            _fail(str(e))
        _ok(f"✓ {agent.id} stopped")
    _stop_gateway_if_idle(port)


@arena_group.command("reset")
@click.argument("agent_id")
def reset_cmd(agent_id: str):
    """Recreate an agent from its image (drops its conversations)."""
    from ..arena import target

    _running_or_fail(agent_id)
    gateway = _ensure_gateway(_gateway_port())
    _say(f"Resetting {agent_id}…")
    try:
        target.reset_via_gateway(agent_id, gateway)
    except target.TargetError as e:
        _fail(str(e))
    _ok(f"✓ {agent_id} reset")


@arena_group.command("rm")
@click.argument("agent_id")
def rm_cmd(agent_id: str):
    """Stop an agent and remove its images and cached manifest."""
    from ..arena import catalog, runtime
    from ..arena.manifest import ManifestError

    corrupt = False
    try:
        found = catalog.installed(agent_id)
    except ManifestError as e:
        _warn(f"the cached manifest for {agent_id} is unreadable ({e}); removing the cache only")
        found, corrupt = None, True
    if found is None and not corrupt:
        _fail(f"{agent_id} is not installed")

    try:
        agent = runtime.find_running(agent_id, include_stopped=True)
    except runtime.DockerError as e:
        _warn(f"{e} (images were not removed)")
        agent, found = None, None
    try:
        if agent is not None:
            runtime.stop(agent.id, agent.kind, agent_dir=_agent_dir(agent))
            _ok(f"✓ {agent_id} stopped")
        if found is not None:
            runtime.remove_images(*found)
    except runtime.DockerError as e:
        _fail(str(e))
    try:
        catalog.remove_installed(agent_id)
    except catalog.CatalogError as e:
        _fail(str(e))
    except OSError as e:
        _fail(f"cannot remove the cached manifest for {agent_id}: {e}")
    _ok(f"✓ {agent_id} removed")
    _stop_gateway_if_idle(_gateway_port(strict=False))


# ── endpoint / serve ──


@arena_group.command("endpoint")
@click.argument("agent_id")
def endpoint_cmd(agent_id: str):
    """Print the URLs, the access token, a curl example and the hb bot config for an agent."""
    import json

    from ..arena import paths, target

    _running_or_fail(agent_id)
    gateway = _ensure_gateway(_gateway_port())
    try:
        token = paths.gateway_token()
    except OSError as e:
        _fail(f"cannot read {paths.token_file()}: {e}")
    _print_endpoints(agent_id, gateway, token)
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "SendMessage",
        "params": {
            "message": {"role": "ROLE_USER", "messageId": "m1", "parts": [{"text": "Hello"}]}
        },
    }
    click.echo("")
    click.echo(
        f"curl -s {gateway}/a2a/{agent_id} -H 'Authorization: Bearer {token}' "
        "-H 'A2A-Version: 1.0' -H 'Content-Type: application/json' "
        f"-d '{json.dumps(body, separators=(',', ':'))}'"
    )
    click.echo("")
    click.echo("hb bot config (hb test --endpoint; it holds the token, so keep it private):")
    click.echo(json.dumps(target.bot_config(agent_id, gateway, token=token), indent=2))


@arena_group.command("token")
def token_cmd():
    """Print your gateway access token (created if there is none yet).

    Prints only the token, for scripts: TOKEN=$(hb arena token). Every gateway call needs
    it. Treat it like a password: anyone who has it can drive your running agents.
    """
    from ..arena import paths

    try:
        token = paths.gateway_token()
    except OSError as e:
        click.echo(f"cannot read {paths.token_file()}: {e}", err=True)
        raise SystemExit(1) from e
    click.echo(token)


@arena_group.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Interface to bind.")
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    default=None,
    help="Port (default: HB_ARENA_PORT or 11500).",
)
def serve_cmd(host: str, port: int | None):
    """Run the gateway in the foreground.

    Other hb arena commands find the gateway via HB_ARENA_PORT (default 11500), so set
    it for them when you use --port. Every call needs the access token (hb arena endpoint
    <id> prints it), whatever --host is.
    """
    from ..arena import daemon
    from ..arena.paths import LOOPBACK_HOSTS, token_file

    port = port or _gateway_port()
    if host not in LOOPBACK_HOSTS:
        _warn(
            f"Binding to {host}: arena agents are intentionally vulnerable and will be "
            "reachable from your network."
        )
    if daemon.is_up(port):
        _fail(
            f"a gateway is already running on port {port} → hb arena stop --all or "
            "choose another --port"
        )
    if daemon.is_up(port, any_owner=True):
        _fail(
            f"port {port} is used by another user's or HOME's arena gateway → choose another "
            "--port (and set HB_ARENA_PORT to it for your other hb arena commands)"
        )
    _say(f"Serving the arena gateway on {host}:{port} (Ctrl+C to stop)")
    _say(
        f"Callers need the access token in {token_file()} "
        "(hb arena endpoint <id> prints it), sent as 'Authorization: Bearer <token>'."
    )
    daemon.serve(host, port)
