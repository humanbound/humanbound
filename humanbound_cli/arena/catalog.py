# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena catalog: index.json + per-agent arena.yaml, fetched from a URL or a local path.

HB_ARENA_INDEX overrides the location (URL, index.json path, or a directory holding one).
Installed manifests are cached under ~/.humanbound/arena/agents/<id>/<version>/.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .. import __version__
from . import paths
from .manifest import (
    AGENT_ID_PATTERN,
    AGENT_ID_RE,
    IMAGE_REF_RE,
    MAX_YAML_BYTES,
    VERSION_PATTERN,
    ArenaManifest,
    ManifestError,
    has_control_chars,
    load_manifest,
    load_yaml,
    parse_manifest,
)
from .paths import arena_dir, ensure_arena_dir

INDEX_SCHEMA_VERSION = 1
COMPOSE_FILE = "docker-compose.yml"
PROVENANCE_FILE = "installed.json"  # where an installed agent came from
MAX_INDEX_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = MAX_YAML_BYTES  # arena.yaml and docker-compose.yml
MAX_REDIRECTS = 5
# How deep an index may nest. Python versions differ in how deep their JSON parser goes
# before it gives up, so the limit is checked here, the same everywhere.
MAX_INDEX_DEPTH = 64
FETCH_TIMEOUT_S = 15
_transport: httpx.BaseTransport | None = None  # tests plug an httpx.MockTransport in here


class CatalogError(RuntimeError):
    """The catalog or an agent in it can't be used. The message is ready to show."""


DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ImagePin(BaseModel):
    """An image the catalog published: the tag an agent's manifest (or compose file) uses and
    the registry digest it must resolve to."""

    ref: str
    digest: str = Field(pattern=DIGEST_PATTERN)

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if has_control_chars(value) or not IMAGE_REF_RE.fullmatch(value):
            raise ValueError(f"{value!r} is not an image reference")
        if "@" in value:
            raise ValueError(f"{value!r}: give the tag here and the digest in 'digest'")
        return value

    @property
    def repository(self) -> str:
        """The ref without its tag (registry/name), for <repository>@<digest>."""
        return repository_of(self.ref)

    @property
    def by_digest(self) -> str:
        return f"{self.repository}@{self.digest}"


def repository_of(ref: str) -> str:
    """registry/name of an image ref, without its tag or digest."""
    ref = ref.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        ref = ref[: len(ref) - len(last)] + last.split(":", 1)[0]
    return ref


class IndexEntry(BaseModel):
    id: str = Field(pattern=AGENT_ID_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: str = ""
    manifest_url: str
    # The published images and their digests: hb runs exactly these (see runtime).
    images: list[ImagePin] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_images(self) -> IndexEntry:
        refs = [pin.ref for pin in self.images]
        dupes = sorted({r for r in refs if refs.count(r) > 1})
        if dupes:
            raise ValueError(f"images lists {', '.join(dupes)} more than once")
        return self

    @field_validator("name", "difficulty", "manifest_url")
    @classmethod
    def _single_line(cls, value: str) -> str:
        if has_control_chars(value):
            raise ValueError("contains a control character")
        return value

    @field_validator("description")
    @classmethod
    def _text(cls, value: str) -> str:
        if has_control_chars(value, multiline=True):
            raise ValueError("contains a control character")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        if any(has_control_chars(tag) for tag in value):
            raise ValueError("a tag contains a control character")
        return value


class Index(BaseModel):
    schema_version: int
    min_hb_version: str | None = None
    generated_at: str | None = None
    agents: list[IndexEntry] = Field(default_factory=list)


@dataclass
class LoadedIndex:
    index: Index
    location: str  # resolved index.json location, the base for relative manifest_url
    stale: bool  # served from cache because the (same) URL was unreachable


def version_key(version: str) -> tuple[int, int, int]:
    parts = []
    for piece in version.split(".")[:3]:
        match = re.match(r"\d+", piece)
        parts.append(int(match.group()) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def index_location() -> str:
    return os.environ.get("HB_ARENA_INDEX") or paths.DEFAULT_INDEX_URL


@dataclass(frozen=True)
class Provenance:
    """Where an installed agent's manifest came from: the index location and the images (with
    digests) its index entry listed. Written by hb at install time, next to the arena.yaml."""

    index: str
    images: tuple[ImagePin, ...] = ()


def read_provenance(agent_dir: Path) -> Provenance | None:
    """None when the record is missing, unreadable or invalid (e.g. an install from an
    older hb): such an install is fetched again, or treated as untrusted."""
    try:
        data = json.loads((Path(agent_dir) / PROVENANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    index, images = data.get("index"), data.get("images", [])
    if not isinstance(index, str) or not isinstance(images, list):
        return None
    try:
        pins = tuple(ImagePin.model_validate(item) for item in images)
    except (ValidationError, TypeError):
        return None
    return Provenance(index, pins)


def trusted(provenance: Provenance | None) -> bool:
    """An agent is trusted only when it was installed from the default catalog
    (paths.DEFAULT_INDEX_URL). Nothing a manifest or an index entry says changes that."""
    return provenance is not None and provenance.index == paths.DEFAULT_INDEX_URL


def is_trusted(agent_dir: Path) -> bool:
    return trusted(read_provenance(agent_dir))


def _is_url(location: str) -> bool:
    return location.startswith(("http://", "https://"))


def _too_large(location: str, limit: int) -> CatalogError:
    return CatalogError(f"{location} is too large (over {limit // 1024} KB)")


def _fetch_url(url: str, limit: int) -> str:
    """GET an http(s) URL: at most `limit` bytes, and redirects only within the same scheme
    (never https → http, never to another kind of URL)."""
    with httpx.Client(
        timeout=FETCH_TIMEOUT_S, follow_redirects=False, transport=_transport
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    target = urljoin(url, resp.headers.get("Location", ""))
                    if urlsplit(target).scheme != urlsplit(url).scheme:
                        raise CatalogError(
                            f"refusing the redirect from {url} to {target}: it changes the scheme"
                        )
                    url = target
                    continue
                resp.raise_for_status()
                try:
                    declared = int(resp.headers.get("Content-Length", ""))
                except ValueError:
                    declared = 0
                if declared > limit:
                    raise _too_large(url, limit)
                data = bytearray()
                for chunk in resp.iter_bytes():
                    data += chunk
                    if len(data) > limit:
                        raise _too_large(url, limit)
                return data.decode("utf-8")
    raise CatalogError(f"too many redirects fetching {url}")


def _read_text(location: str, *, limit: int = MAX_MANIFEST_BYTES) -> str:
    if _is_url(location):
        return _fetch_url(location, limit)
    with open(location, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise _too_large(location, limit)
    return data.decode("utf-8")


def _join(base: str, relative: str) -> str:
    """Resolve `relative` against `base`. A URL base never yields a local path.

    With a URL base the result must be an http(s) URL (urljoin keeps `C:/x` and `file:x`
    as-is, and they would be read from disk), and an https base never downgrades to http.
    """
    if _is_url(base):
        joined = urljoin(base, relative)
        parts = urlsplit(joined)
        if not _is_url(joined) or parts.scheme not in ("http", "https") or not parts.netloc:
            raise CatalogError(f"{relative!r} (relative to {base}) is not an http(s) URL")
        if base.startswith("https://") and parts.scheme != "https":
            raise CatalogError(f"{relative!r} would downgrade {base} from https to http")
        return joined
    if _is_url(relative) or Path(relative).is_absolute():
        return relative
    return str(Path(base).parent / relative)


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder + os.replace: never a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _cache_file() -> Path:
    return arena_dir() / "cache" / "index.json"


def _too_deep(text: str, limit: int = MAX_INDEX_DEPTH) -> bool:
    """JSON text nests arrays and objects more than `limit` levels deep (brackets inside
    strings don't count)."""
    depth = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _parse_index(text: str, loc: str) -> Index:
    try:
        if _too_deep(text):
            raise RecursionError
        return Index.model_validate(json.loads(text))
    except RecursionError:
        raise CatalogError(f"the arena catalog at {loc} is invalid: nested too deeply") from None
    except (ValueError, ValidationError) as e:
        reason = str(e).splitlines()[0][:200]
        raise CatalogError(f"the arena catalog at {loc} is invalid: {reason}") from None


def _load_cached_index(loc: str) -> Index | None:
    try:
        cached = json.loads(_cache_file().read_text(encoding="utf-8"))
        if cached["location"] != loc:
            return None
        return Index.model_validate(cached["index"])
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        KeyError,
        TypeError,
        ValidationError,
        RecursionError,
    ):
        return None


def load_index(location: str | None = None) -> LoadedIndex:
    loc = location or index_location()
    if not _is_url(loc) and Path(loc).is_dir():
        loc = str(Path(loc) / "index.json")
    try:
        text = _read_text(loc, limit=MAX_INDEX_BYTES)
    except (httpx.HTTPError, OSError, UnicodeDecodeError) as e:
        cached = _load_cached_index(loc) if _is_url(loc) else None
        if cached is not None:
            return LoadedIndex(cached, loc, True)
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
    if _is_url(loc):  # the cache only serves unreachable URLs; local paths aren't cached
        ensure_arena_dir()
        cache = _cache_file()
        cache.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(cache, json.dumps({"location": loc, "index": index.model_dump(mode="json")}))
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


def check_compose_path(value: str) -> None:
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or ":" in value or "\\" in value:
        raise CatalogError(
            f"source.compose must be a relative path inside the agent folder, got {value!r}"
        )


def _fetch_and_validate(entry: IndexEntry, index_loc: str) -> tuple[ArenaManifest, str, str]:
    manifest_loc = _join(index_loc, entry.manifest_url)
    try:
        text = _read_text(manifest_loc)
    except (httpx.HTTPError, OSError, UnicodeDecodeError) as e:
        raise CatalogError(f"cannot fetch the manifest for {entry.id}: {e}") from None
    manifest = parse_manifest(load_yaml(text, f"the manifest for {entry.id}"))
    if (manifest.id, manifest.version) != (entry.id, entry.version):
        raise CatalogError(
            f"catalog/manifest mismatch: the index lists {entry.id}:{entry.version} but its "
            f"manifest says {manifest.id}:{manifest.version}"
        )
    if manifest.source.compose:
        check_compose_path(manifest.source.compose)
    return manifest, text, manifest_loc


def read_manifest(entry: IndexEntry, index_loc: str) -> ArenaManifest:
    """Fetch and validate an agent's manifest without installing (no disk writes)."""
    return _fetch_and_validate(entry, index_loc)[0]


def fetch_manifest(entry: IndexEntry, index_loc: str) -> tuple[ArenaManifest, Path]:
    """Install: cache an agent's arena.yaml (and compose file).

    Each file is replaced atomically, and arena.yaml (what `installed` looks for) goes last,
    so a failure never leaves a half-written or half-installed agent. The provenance record
    (index location + the entry's images and digests) is written before it.
    """
    manifest, text, manifest_loc = _fetch_and_validate(entry, index_loc)
    compose_text = None
    if manifest.source.compose:
        try:
            compose_text = _read_text(_join(manifest_loc, manifest.source.compose))
        except (httpx.HTTPError, OSError, UnicodeDecodeError) as e:
            raise CatalogError(f"cannot fetch the compose file for {entry.id}: {e}") from None
    ensure_arena_dir()
    target = agent_dir(manifest.id, manifest.version)
    target.mkdir(parents=True, exist_ok=True)
    if compose_text is not None:
        _write_atomic(target / COMPOSE_FILE, compose_text)
    else:
        (target / COMPOSE_FILE).unlink(missing_ok=True)
    provenance = {
        "index": index_loc,
        "images": [pin.model_dump(mode="json") for pin in entry.images],
    }
    _write_atomic(target / PROVENANCE_FILE, json.dumps(provenance))
    _write_atomic(target / "arena.yaml", text)
    return manifest, target


def not_running_message(agent_id: str) -> str:
    """What to tell someone who named an agent that is not running. Only an installed
    agent is worth pointing at `hb arena run`: any other id may not exist at all."""
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
        return (
            f"{agent_id!r} is not a valid agent id (lowercase letters, digits and dashes) "
            "→ hb arena ls lists the catalog"
        )
    if (arena_dir() / "agents" / agent_id).is_dir():
        return f"{agent_id} is not running → hb arena run {agent_id}"
    return f"{agent_id} is not running, and it is not installed → hb arena ls lists the catalog"


def installed(agent_id: str, version: str | None = None) -> tuple[ArenaManifest, Path] | None:
    """The cached manifest for an agent (highest version unless one is given)."""
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
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
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        try:
            found = installed(p.name)
        except ManifestError:
            continue
        if found is not None:
            out.append(found[0])
    return out


def remove_installed(agent_id: str) -> bool:
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
        raise CatalogError(f"invalid agent id {agent_id!r}")
    base = arena_dir() / "agents" / agent_id
    if not base.exists():
        return False
    shutil.rmtree(base)
    return True
