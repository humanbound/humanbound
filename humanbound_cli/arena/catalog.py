# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena catalog: index.json + per-agent arena.yaml, fetched from a URL or a local path.

HB_ARENA_INDEX overrides the location (URL, index.json path, or a directory holding one).
Fetched manifests are cached under ~/.humanbound/arena/agents/<id>/<version>/.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml
from pydantic import BaseModel, Field

from .. import __version__
from .manifest import AGENT_ID_RE, ArenaManifest, ManifestError, load_manifest, parse_manifest
from .paths import DEFAULT_INDEX_URL, arena_dir

INDEX_SCHEMA_VERSION = 1


class CatalogError(RuntimeError):
    """The catalog or an agent in it can't be used. The message is ready to show."""


class IndexEntry(BaseModel):
    id: str
    version: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: str = ""
    origin: str = ""
    manifest_url: str


class Index(BaseModel):
    schema_version: int
    min_hb_version: str | None = None
    generated_at: str | None = None
    agents: list[IndexEntry] = Field(default_factory=list)


@dataclass
class LoadedIndex:
    index: Index
    location: str  # resolved index.json location, the base for relative manifest_url
    stale: bool  # served from cache because the source was unreachable


def version_key(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.split(".")[:3]:
        match = re.match(r"\d+", piece)
        parts.append(int(match.group()) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def index_location() -> str:
    return os.environ.get("HB_ARENA_INDEX") or DEFAULT_INDEX_URL


def _is_url(location: str) -> bool:
    return location.startswith(("http://", "https://"))


def _read_text(location: str) -> str:
    if _is_url(location):
        resp = httpx.get(location, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    return Path(location).read_text(encoding="utf-8")


def _join(base: str, relative: str) -> str:
    if _is_url(base):
        # Never treat `relative` as a local filesystem path when the base is remote:
        # urljoin resolves a leading "/" against the base's origin, not the local disk.
        return urljoin(base, relative)
    if _is_url(relative) or Path(relative).is_absolute():
        return relative
    return str(Path(base).parent / relative)


def _cache_file() -> Path:
    return arena_dir() / "cache" / "index.json"


def _parse_index(text: str, loc: str) -> Index:
    try:
        return Index.model_validate(json.loads(text))
    except ValueError as e:
        reason = str(e).splitlines()[0]
        raise CatalogError(f"the arena catalog at {loc} is invalid: {reason}") from None


def _load_cached_index(loc: str) -> LoadedIndex | None:
    """The cached index, but only when it was cached from this exact `loc` (a URL)."""
    cache = _cache_file()
    if not cache.exists():
        return None
    try:
        raw = cache.read_text(encoding="utf-8")
        cached = json.loads(raw)
        cached_location = cached["location"]
        if cached_location != loc:
            return None
        index = Index.model_validate(cached["index"])
    except (OSError, UnicodeDecodeError, ValueError, KeyError):
        return None
    return LoadedIndex(index, cached_location, True)


def load_index(location: str | None = None) -> LoadedIndex:
    loc = location or index_location()
    if not _is_url(loc) and Path(loc).is_dir():
        loc = str(Path(loc) / "index.json")
    try:
        text = _read_text(loc)
    except (httpx.HTTPError, OSError, UnicodeDecodeError) as e:
        if _is_url(loc):
            cached = _load_cached_index(loc)
            if cached is not None:
                return cached
        raise CatalogError(f"cannot load the arena catalog from {loc}: {e}") from None

    index = _parse_index(text, loc)
    if index.schema_version > INDEX_SCHEMA_VERSION:
        raise CatalogError("the arena catalog needs a newer hb → pip install -U humanbound")
    if (
        index.min_hb_version
        and __version__ != "dev"
        and version_key(__version__) < version_key(index.min_hb_version)
    ):
        raise CatalogError(
            f"this agent catalog needs a newer hb (>= {index.min_hb_version}, you have "
            f"{__version__}) → pip install -U humanbound"
        )
    cache = _cache_file()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"location": loc, "index": index.model_dump(mode="json")}), encoding="utf-8"
    )
    return LoadedIndex(index, loc, False)


def resolve(index: Index, ref: str) -> IndexEntry:
    """Resolve 'id' (highest version) or 'id:version' to a catalog entry."""
    agent_id, _, version = ref.partition(":")
    matches = [e for e in index.agents if e.id == agent_id]
    if not matches:
        close = difflib.get_close_matches(agent_id, sorted({e.id for e in index.agents}), n=3)
        hint = (
            f" Did you mean: {', '.join(close)}?"
            if close
            else " Run 'hb arena ls' to see available agents."
        )
        raise CatalogError(f"unknown arena agent '{agent_id}'.{hint}")
    if version:
        for entry in matches:
            if entry.version == version:
                return entry
        available = ", ".join(sorted((e.version for e in matches), key=version_key))
        raise CatalogError(f"{agent_id} has no version {version}. Available: {available}")
    return max(matches, key=lambda e: version_key(e.version))


def agent_dir(agent_id: str, version: str) -> Path:
    return arena_dir() / "agents" / agent_id / version


def _check_compose_path(compose: str, agent_id: str) -> None:
    if Path(compose).is_absolute() or ".." in Path(compose).parts:
        raise CatalogError(
            f"cannot fetch the compose file for {agent_id}: "
            f"source.compose must be a relative path with no '..' segments, got '{compose}'"
        )


def _fetch_and_validate_manifest(
    entry: IndexEntry, index_loc: str
) -> tuple[ArenaManifest, str, str]:
    """Fetch, parse and mismatch-check an agent's arena.yaml. No disk writes.

    Returns (manifest, raw manifest text, resolved manifest location).
    """
    manifest_loc = _join(index_loc, entry.manifest_url)
    try:
        text = _read_text(manifest_loc)
    except (httpx.HTTPError, OSError) as e:
        raise CatalogError(f"cannot fetch the manifest for {entry.id}: {e}") from None
    try:
        manifest = parse_manifest(yaml.safe_load(text))
    except yaml.YAMLError as e:
        raise ManifestError(f"cannot parse the manifest for {entry.id}: {e}") from None
    if (manifest.id, manifest.version) != (entry.id, entry.version):
        raise CatalogError(
            f"catalog/manifest mismatch: the index lists {entry.id}:{entry.version} but its "
            f"manifest says {manifest.id}:{manifest.version}"
        )
    return manifest, text, manifest_loc


def read_manifest(entry: IndexEntry, index_loc: str) -> ArenaManifest:
    """Fetch and validate an agent's arena.yaml (mismatch-checked). No disk writes.

    Use this for read-only lookups (e.g. `hb arena info` on an agent that isn't
    installed yet) where "installed" must keep meaning pulled/run, not merely browsed.
    """
    manifest, _, _ = _fetch_and_validate_manifest(entry, index_loc)
    return manifest


def fetch_manifest(entry: IndexEntry, index_loc: str) -> tuple[ArenaManifest, Path]:
    """Download an agent's arena.yaml (and compose file) into the local cache.

    Everything is fetched before anything is written, so a failure partway through
    never leaves a half-installed agent behind.
    """
    manifest, text, manifest_loc = _fetch_and_validate_manifest(entry, index_loc)

    compose_text = None
    if manifest.source.compose:
        _check_compose_path(manifest.source.compose, entry.id)
        try:
            compose_text = _read_text(_join(manifest_loc, manifest.source.compose))
        except (httpx.HTTPError, OSError) as e:
            raise CatalogError(f"cannot fetch the compose file for {entry.id}: {e}") from None

    target = agent_dir(manifest.id, manifest.version)
    target.mkdir(parents=True, exist_ok=True)
    if compose_text is not None:
        (target / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    else:
        # This version is now image-based: drop any docker-compose.yml from a stale install.
        (target / "docker-compose.yml").unlink(missing_ok=True)
    (target / "arena.yaml").write_text(text, encoding="utf-8")
    return manifest, target


def installed(agent_id: str, version: str | None = None) -> tuple[ArenaManifest, Path] | None:
    """The cached manifest for an agent (highest version unless one is given)."""
    if not AGENT_ID_RE.match(agent_id):
        return None
    base = arena_dir() / "agents" / agent_id
    if not base.is_dir():
        return None
    versions = [p.name for p in base.iterdir() if (p / "arena.yaml").exists()]
    if version:
        versions = [v for v in versions if v == version]
    if not versions:
        return None
    chosen = base / max(versions, key=version_key)
    return load_manifest(chosen / "arena.yaml"), chosen


def list_installed() -> list[ArenaManifest]:
    root = arena_dir() / "agents"
    if not root.is_dir():
        return []
    result = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        try:
            found = installed(p.name)
        except ManifestError:
            continue
        if found is not None:
            result.append(found[0])
    return result


def remove_installed(agent_id: str) -> bool:
    if not AGENT_ID_RE.match(agent_id):
        raise CatalogError(f"'{agent_id}' is not a valid arena agent id")
    base = arena_dir() / "agents" / agent_id
    if not base.exists():
        return False
    shutil.rmtree(base)
    return True
