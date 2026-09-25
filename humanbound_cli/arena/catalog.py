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
from .manifest import ArenaManifest, ManifestError, load_manifest, parse_manifest
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
    return Path(location).read_text()


def _join(base: str, relative: str) -> str:
    if _is_url(relative) or Path(relative).is_absolute():
        return relative
    if _is_url(base):
        return urljoin(base, relative)
    return str(Path(base).parent / relative)


def _cache_file() -> Path:
    return arena_dir() / "cache" / "index.json"


def load_index(location: str | None = None) -> LoadedIndex:
    loc = location or index_location()
    if not _is_url(loc) and Path(loc).is_dir():
        loc = str(Path(loc) / "index.json")
    try:
        text = _read_text(loc)
    except (httpx.HTTPError, OSError) as e:
        cache = _cache_file()
        if cache.exists():
            cached = json.loads(cache.read_text())
            return LoadedIndex(Index.model_validate(cached["index"]), cached["location"], True)
        raise CatalogError(f"cannot load the arena catalog from {loc}: {e}") from None

    index = Index.model_validate(json.loads(text))
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
    cache.write_text(json.dumps({"location": loc, "index": index.model_dump(mode="json")}))
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


def fetch_manifest(entry: IndexEntry, index_loc: str) -> tuple[ArenaManifest, Path]:
    """Download an agent's arena.yaml (and compose file) into the local cache."""
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
    target = agent_dir(manifest.id, manifest.version)
    target.mkdir(parents=True, exist_ok=True)
    (target / "arena.yaml").write_text(text)
    if manifest.source.compose:
        try:
            compose_text = _read_text(_join(manifest_loc, manifest.source.compose))
        except (httpx.HTTPError, OSError) as e:
            raise CatalogError(f"cannot fetch the compose file for {entry.id}: {e}") from None
        (target / "docker-compose.yml").write_text(compose_text)
    return manifest, target


def installed(agent_id: str, version: str | None = None) -> tuple[ArenaManifest, Path] | None:
    """The cached manifest for an agent (highest version unless one is given)."""
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
    found = (installed(p.name) for p in sorted(root.iterdir()) if p.is_dir())
    return [f[0] for f in found if f is not None]


def remove_installed(agent_id: str) -> bool:
    base = arena_dir() / "agents" / agent_id
    if not base.exists():
        return False
    shutil.rmtree(base)
    return True
