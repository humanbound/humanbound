# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb orchestrators`: list, create and check the orchestrators `hb test -t` can run.

Custom orchestrators live in ~/.humanbound/orchestrators/<name>/. Engine modules
(and yaml) are imported inside functions so `hb` startup stays cheap. Manifest
text is printed without Rich markup interpretation.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "orchestrator"
TEMPLATE_FILES = ("manifest.yaml", "config.py", "generator.py", "judge.py", "orchestrator.py")

# Becomes a Python package name and a `-t` value, so keep it to identifier characters.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _looks_like_path(arg: str) -> bool:
    return "/" in arg or os.sep in arg or arg.startswith((".", "~"))


def _say(msg: str, style: str | None = None) -> None:
    console.print(Text(msg, style=style or ""), soft_wrap=True)


@dataclass
class _Check:
    """What validation found in one orchestrator directory."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


def _read_manifest(path: Path, check: _Check) -> None:
    import yaml

    manifest_file = path / "manifest.yaml"
    if not manifest_file.is_file():
        check.warnings.append("no manifest.yaml (name, version and description are optional)")
        return
    try:
        manifest = yaml.safe_load(manifest_file.read_text())
    except yaml.YAMLError as e:
        check.errors.append(f"manifest.yaml is not valid YAML: {e}")
        return
    if manifest is None:
        manifest = {}
    if not isinstance(manifest, dict):
        check.errors.append("manifest.yaml must be a mapping of keys to values")
        return
    check.manifest = manifest
    missing = [k for k in ("name", "version", "description") if not manifest.get(k)]
    if missing:
        check.warnings.append(f"manifest.yaml has no {', '.join(missing)}")


def _static_check(path: Path) -> _Check:
    """Checks that do not import the orchestrator's code."""
    from ..engine.local_runner import find_builtin_orchestrator

    check = _Check()
    if not (path / "orchestrator.py").is_file():
        check.errors.append(f"no orchestrator.py in {path}")
    _read_manifest(path, check)
    builtin = find_builtin_orchestrator(path.name)
    if builtin is not None:
        check.errors.append(
            f"'{path.name}' is the name of the built-in {builtin.category}, "
            f"so `hb test -t {path.name}` runs the built-in; rename the directory"
        )
    return check


def _contract_check(path: Path, check: _Check) -> None:
    """Import the orchestrator the way `hb test` does and check its entry points."""
    import inspect

    from ..engine.local_runner import _load_custom_orchestrator

    try:
        module = _load_custom_orchestrator(path.name, path)
    except Exception as e:  # any import-time failure is the user's to see
        check.errors.append(f"{type(e).__name__}: {e}")
        return

    # The arguments LocalTestRunner passes; a signature that cannot take them fails at run time.
    calls = {
        "orchestrator_generate": ((None, None), {}),
        "orchestrator_run": (
            (),
            dict(
                organisation_id=None,
                model_provider=None,
                experiment=None,
                prompts=None,
                few_shots_model=None,
                callbacks=None,
            ),
        ),
    }
    for name, (args, kwargs) in calls.items():
        try:
            inspect.signature(getattr(module, name)).bind(*args, **kwargs)
        except (TypeError, ValueError) as e:
            check.errors.append(f"{name} cannot be called the way `hb test` calls it: {e}")


@click.group("orchestrators")
def orchestrators_group():
    """List, create and check orchestrators for the local engine.

    \b
    Examples:
      hb orchestrators list                     # Built-in and custom orchestrators
      hb orchestrators new pii_leak             # Scaffold ~/.humanbound/orchestrators/pii_leak/
      hb orchestrators validate pii_leak        # Check it without running a test
      hb test --endpoint ./bot.json -t pii_leak --wait
    """


@orchestrators_group.command("list")
def list_command():
    """List built-in orchestrators and those in ~/.humanbound/orchestrators/."""
    from ..engine.local_runner import BUILTIN_ORCHESTRATORS, custom_orchestrators_dir

    table = Table(show_lines=False)
    table.add_column("Name (-t)", style="bold", no_wrap=True)
    table.add_column("Source")
    table.add_column("Version")
    table.add_column("Description")

    for b in BUILTIN_ORCHESTRATORS:
        name = Text(b.name)
        if b.aliases:
            name.append(f"\nalso: {', '.join(b.aliases)}", style="dim")
        table.add_row(name, "built-in", "", Text(b.description))

    root = custom_orchestrators_dir()
    custom = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for path in custom:
        if path.name.startswith((".", "_")):
            continue
        check = _static_check(path)
        if check.errors:
            description = Text(check.errors[0], style="red")
        else:
            description = Text(str(check.manifest.get("description", "")))
        table.add_row(
            Text(path.name), "custom", Text(str(check.manifest.get("version", ""))), description
        )

    console.print(table)
    _say(f"Custom orchestrators are read from {root}")
    if not custom:
        _say("Create one with: hb orchestrators new <name>", "dim")


@orchestrators_group.command("new")
@click.argument("name")
@click.option("--description", default="", help="Description written to manifest.yaml.")
@click.option("--author", default="", help="Author written to manifest.yaml.")
@click.option(
    "--dir",
    "parent_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Create it under this directory instead of ~/.humanbound/orchestrators/.",
)
def new_command(name, description, author, parent_dir):
    """Create a working custom orchestrator to start from.

    The scaffold holds single-turn conversations with your agent, one per
    opening prompt in config.py, and asks an LLM judge to score each reply.
    """
    from ..engine.local_runner import custom_orchestrators_dir, find_builtin_orchestrator

    if not NAME_RE.match(name):
        raise click.BadParameter(
            "use lowercase letters, digits and underscores, starting with a letter",
            param_hint="NAME",
        )
    builtin = find_builtin_orchestrator(name)
    if builtin is not None:
        raise click.BadParameter(
            f"'{name}' is the built-in {builtin.category}; choose another name",
            param_hint="NAME",
        )

    target = (parent_dir or custom_orchestrators_dir()) / name
    if target.exists():
        raise click.ClickException(f"{target} already exists; nothing was changed")

    values = {
        "name": name,
        # JSON strings are valid YAML scalars, so any text is quoted safely.
        "description": json.dumps(description or f"Custom orchestrator {name}"),
        "author": json.dumps(author),
    }
    target.mkdir(parents=True)
    for filename in TEMPLATE_FILES:
        text = (TEMPLATES_DIR / f"{filename}.tmpl").read_text()
        (target / filename).write_text(Template(text).safe_substitute(values))

    _say(f"✓ Created {target}", "green")
    _say("  Edit config.py first: the attack category, opening prompts and judging rubric.")
    _say("")
    _say("Next:")
    if parent_dir is None:
        _say(f"  hb orchestrators validate {name}")
        _say(f"  hb test --endpoint ./bot.json -t {name} --wait")
    else:
        # Absolute, so `validate` reads it as a path even after `--dir .`.
        _say(f"  hb orchestrators validate {target.resolve()}")
        _say(
            f"  `hb test -t {name}` looks only in {custom_orchestrators_dir()}, "
            f"so copy or link it there to run it."
        )


@orchestrators_group.command("validate")
@click.argument("name_or_path")
def validate_command(name_or_path):
    """Check a custom orchestrator without running a test.

    NAME_OR_PATH is a name in ~/.humanbound/orchestrators/, or a path to an
    orchestrator directory when it contains a / or starts with . or ~
    (./pii_leak, not pii_leak, for a folder in the current directory).
    This imports its code, as `hb test` does, but calls no LLM and no agent.
    Exits 1 if `hb test` could not run it.
    """
    from ..engine.local_runner import custom_orchestrators_dir

    # A bare name always means an installed orchestrator, so an unrelated folder
    # of the same name in the current directory is never picked up instead.
    if _looks_like_path(name_or_path):
        path = Path(name_or_path).expanduser()
        if not path.is_dir():
            raise click.ClickException(f"No orchestrator directory at {path}")
    else:
        path = custom_orchestrators_dir() / name_or_path
        if not path.is_dir():
            raise click.ClickException(
                f"No orchestrator named '{name_or_path}' in {path.parent}. "
                f"See `hb orchestrators list`, or pass ./{name_or_path} for a folder here."
            )
    path = path.resolve()

    check = _static_check(path)
    if not any(e.startswith("no orchestrator.py") for e in check.errors):
        _contract_check(path, check)

    for warning in check.warnings:
        _say(f"! {warning}", "yellow")
    for error in check.errors:
        _say(f"✗ {error}", "red")
    if check.errors:
        raise SystemExit(1)
    version = check.manifest.get("version")
    label = f"{path.name} {version}" if version else path.name
    installed = custom_orchestrators_dir().resolve()
    if path.parent == installed:
        _say(f"✓ {label} is valid; run it with -t {path.name}", "green")
    else:
        _say(f"✓ {label} is valid", "green")
        _say(f"  Copy or link it into {installed} to run it with -t {path.name}.")
