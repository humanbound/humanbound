# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Remembered confirmations for agents from a catalog other than the default one.

`hb arena run` asks once per agent id@version (per owner, i.e. per arena dir) before it
runs an agent that isn't from the default catalog. The answer is kept in
~/.humanbound/arena/accepted.json together with a fingerprint of the installed arena.yaml,
compose file and install record (catalog location, image digests), so a changed manifest
(other images, other keys, other hosts it may reach) or other digests are asked about
again.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .catalog import COMPOSE_FILE, PROVENANCE_FILE
from .manifest import ArenaManifest
from .paths import arena_dir, ensure_arena_dir

ACCEPTED_FILE = "accepted.json"


def _path() -> Path:
    return arena_dir() / ACCEPTED_FILE


def _key(m: ArenaManifest) -> str:
    return f"{m.id}@{m.version}"


def fingerprint(agent_dir: Path) -> str:
    """sha256 over the installed arena.yaml, compose file and install record (if any)."""
    digest = hashlib.sha256()
    for name in ("arena.yaml", COMPOSE_FILE, PROVENANCE_FILE):
        path = Path(agent_dir) / name
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def _read() -> dict[str, str]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def is_accepted(m: ArenaManifest, agent_dir: Path) -> bool:
    try:
        return _read().get(_key(m)) == fingerprint(agent_dir)
    except OSError:
        return False


def accept(m: ArenaManifest, agent_dir: Path) -> None:
    """Remember the confirmation (atomically, 0600)."""
    values = _read()
    values[_key(m)] = fingerprint(agent_dir)
    folder = ensure_arena_dir()
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".accepted-", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2, sort_keys=True)
        os.replace(tmp, _path())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
