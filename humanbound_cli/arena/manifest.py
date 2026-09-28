# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena.yaml manifest.

Arena fields sit at the top level; the agent's Humanbound agent.yaml is embedded
unchanged under `agent:`, so `manifest.agent_yaml()` is itself a valid agent.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..extractors.capabilities.types import CAPABILITY_KEYS
from . import egress as _egress

SCHEMA_VERSION = 1
AGENT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
AGENT_ID_RE = re.compile(AGENT_ID_PATTERN)
VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_ENV_PREFIXES = ("HB_", "HUMANBOUND_")
# A conservative docker image reference (registry/repo:tag, optional @sha256:digest).
# It can't start with '-', so it is never read as a `docker run`/`pull` flag.
IMAGE_REF_RE = re.compile(r"[a-z0-9][A-Za-z0-9._/:@-]{0,254}")
# A git commit id (full SHA-1) and an SPDX license id or simple expression (MIT,
# Apache-2.0, GPL-3.0-or-later, "MIT OR Apache-2.0", "GPL-2.0-only WITH Classpath-exception-2.0").
_GIT_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
_SPDX_ID = r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}"
_SPDX_RE = re.compile(rf"{_SPDX_ID}(?: (?:AND|OR|WITH) {_SPDX_ID}){{0,7}}")
MAX_TIMEOUT_S = 600

# Limits for every YAML document hb reads for the arena (arena.yaml, compose files).
MAX_YAML_BYTES = 256 * 1024
MAX_YAML_NODES = 50_000
MAX_YAML_DEPTH = 64
# C0 controls (except tab and newline), DEL and C1 controls: they can rewrite the terminal
# (ANSI escapes) or smuggle content past a reader. Short fields refuse tab/newline too.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_CONTROL_STRICT_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class ManifestError(ValueError):
    """arena.yaml is unreadable or invalid. The message is ready to show to the user."""


def has_control_chars(text: str, *, multiline: bool = False) -> bool:
    """C0/C1 control characters (with multiline=True, tab and newline are allowed)."""
    return bool((_CONTROL_RE if multiline else _CONTROL_STRICT_RE).search(text))


# ── YAML with limits ──


class _LimitedLoader(yaml.SafeLoader):
    """SafeLoader without anchors/aliases (no "billion laughs"), with node and depth caps."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._nodes = 0
        self._depth = 0

    def _refuse(self, why: str, event: Any) -> None:
        raise yaml.composer.ComposerError(None, None, why, event.start_mark)

    def compose_node(self, parent: Any, index: Any) -> Any:
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent):
            self._refuse("YAML aliases (*name) are not allowed", event)
        if getattr(event, "anchor", None) is not None:
            self._refuse("YAML anchors (&name) are not allowed", event)
        self._nodes += 1
        if self._nodes > MAX_YAML_NODES:
            self._refuse(f"the document is too large (more than {MAX_YAML_NODES} nodes)", event)
        self._depth += 1
        if self._depth > MAX_YAML_DEPTH:
            self._refuse(f"the document is nested more than {MAX_YAML_DEPTH} levels deep", event)
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


def load_yaml(text: str, what: str = "the YAML document") -> Any:
    """Parse untrusted YAML safely. Raises ManifestError (ready to show)."""
    if len(text.encode("utf-8", "surrogatepass")) > MAX_YAML_BYTES:
        raise ManifestError(f"{what} is too large (over {MAX_YAML_BYTES // 1024} KB)")
    loader = _LimitedLoader(text)
    try:
        return loader.get_single_data()
    except yaml.YAMLError as e:
        raise ManifestError(f"cannot parse {what}: {e}") from None
    except RecursionError:
        raise ManifestError(f"cannot parse {what}: it is nested too deeply") from None
    finally:
        loader.dispose()


def read_text_limited(path: str | Path, limit: int = MAX_YAML_BYTES) -> str:
    """Read a UTF-8 file, refusing one over `limit` bytes (OSError / UnicodeDecodeError /
    ManifestError)."""
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ManifestError(f"{path} is too large (over {limit // 1024} KB)")
    return data.decode("utf-8")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _starts_with_slash(value: str, what: str) -> str:
    if not value.startswith("/"):
        raise ValueError(f"{what} must start with '/'")
    return value


def _contains_prompt(item: Any) -> bool:
    if isinstance(item, str):
        return item.lower() == "$prompt"
    if isinstance(item, dict):
        return any(_contains_prompt(v) for v in item.values())
    if isinstance(item, list):
        return any(_contains_prompt(v) for v in item)
    return False


# ── agent: the Humanbound agent.yaml (extra keys such as settings:/tools: are kept) ──


class AgentScope(BaseModel):
    model_config = ConfigDict(extra="allow")
    business: str
    more_info: str = ""


class AgentIntents(BaseModel):
    model_config = ConfigDict(extra="allow")
    permitted: list[str] = Field(default_factory=list)
    restricted: list[str] = Field(default_factory=list)


class AgentBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = "1.0"
    scope: AgentScope
    intents: AgentIntents
    capabilities: list[str] | None = None

    @field_validator("capabilities")
    @classmethod
    def _known_capabilities(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = sorted(set(value) - set(CAPABILITY_KEYS))
        if unknown:
            raise ValueError(
                f"unknown capability key(s): {', '.join(unknown)}. Valid: {', '.join(CAPABILITY_KEYS)}"
            )
        dupes = sorted({v for v in value if value.count(v) > 1})
        if dupes:
            raise ValueError(f"duplicate capability key(s): {', '.join(dupes)}")
        return value


# ── arena fields ──


def _http_url(value: str, what: str) -> str:
    """An absolute http(s) URL with a host and no whitespace."""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or any(c.isspace() for c in value):
        raise ValueError(f"{what} must be an http(s) URL, got {value!r}")
    return value


class Developer(_Strict):
    """Who built and maintains the agent, shown to users before a first run."""

    name: str
    url: str
    contact: str | None = None  # e.g. an email address or an issue tracker

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("developer.name can't be empty")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _http_url(v, "developer.url")

    @field_validator("contact")
    @classmethod
    def _contact(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("developer.contact can't be empty (leave it out instead)")
        return v


class Upstream(_Strict):
    """The upstream project an agent packages (optional)."""

    repo: str
    ref: str  # the full commit SHA the image was built from
    license: str | None = None  # SPDX id of the upstream project, shown to users

    @field_validator("repo")
    @classmethod
    def _repo(cls, v: str) -> str:
        return _http_url(v, "source.upstream.repo")

    @field_validator("ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        if not _GIT_SHA_RE.fullmatch(v):
            raise ValueError(
                f"source.upstream.ref must be a full 40-character commit SHA, got {v!r}"
            )
        return v

    @field_validator("license")
    @classmethod
    def _license(cls, v: str | None) -> str | None:
        if v is not None and not _SPDX_RE.fullmatch(v):
            raise ValueError(
                f"source.upstream.license must be an SPDX license id (e.g. MIT, Apache-2.0), got {v!r}"
            )
        return v


class Source(_Strict):
    image: str | None = None
    compose: str | None = None
    service: str | None = None
    upstream: Upstream | None = None

    @field_validator("image")
    @classmethod
    def _image_ref(cls, v: str | None) -> str | None:
        if v is not None and not IMAGE_REF_RE.fullmatch(v):
            raise ValueError(
                f"{v!r} is not an image reference (lowercase letter or digit first, then "
                "letters, digits and . _ / : @ -)"
            )
        return v

    @model_validator(mode="after")
    def _one_kind(self) -> Source:
        if bool(self.image) == bool(self.compose):
            raise ValueError("source needs exactly one of 'image' or 'compose'")
        if self.compose and not self.service:
            raise ValueError("source.compose needs 'service' (the compose service to talk to)")
        return self


class Health(_Strict):
    path: str = "/health"
    timeout_s: int = Field(default=60, gt=0, le=MAX_TIMEOUT_S)

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return _starts_with_slash(v, "runtime.health.path")


class EnvSpec(_Strict):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)

    @field_validator("required", "optional")
    @classmethod
    def _names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not _ENV_NAME_RE.fullmatch(name):
                raise ValueError(f"runtime.env: invalid variable name {name!r}")
            if name.upper().startswith(RESERVED_ENV_PREFIXES):
                raise ValueError(f"runtime.env: {name} is reserved for hb's own credentials")
            if name in _egress.PROXY_NAMES:
                raise ValueError(
                    f"runtime.env: {name} is set by hb (an agent's web traffic goes through "
                    "hb's proxy); list what the agent must reach under runtime.egress"
                )
        return names


class Runtime(_Strict):
    port: int = Field(ge=1, le=65535)
    health: Health = Field(default_factory=Health)
    env: EnvSpec = Field(default_factory=EnvSpec)
    timeout_s: int = Field(default=120, gt=0, le=MAX_TIMEOUT_S)
    # What the agent may reach besides its model: exact host names, "host" (port 443) or
    # "host:port". Everything else is blocked (see egress.py).
    egress: list[str] | None = Field(default=None, min_length=1, max_length=_egress.MAX_EGRESS)

    @field_validator("egress")
    @classmethod
    def _egress_entries(cls, entries: list[str] | None) -> list[str] | None:
        if entries is None:
            return None
        seen: set[tuple[str, int]] = set()
        for entry in entries:
            where = _egress.parse_entry(entry)
            if where in seen:
                raise ValueError(f"runtime.egress: {entry!r} is listed twice")
            seen.add(where)
        return entries


class HttpCall(_Strict):
    endpoint: str
    headers: dict[str, str] = Field(default_factory=dict)
    payload: Any = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str) -> str:
        return _starts_with_slash(v, "endpoint")


class ResponseMap(_Strict):
    text: str
    tool_calls: str | None = None


class Integration(_Strict):
    type: Literal["http", "a2a"] = "http"
    path: str = "/"  # type a2a: the agent's own JSON-RPC endpoint
    thread_init: HttpCall | None = None
    chat_completion: HttpCall | None = None
    response: ResponseMap | None = None
    history: Literal["none", "gateway", "agent"] = "none"

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return _starts_with_slash(v, "integration.path")

    @model_validator(mode="after")
    def _http_needs_calls(self) -> Integration:
        if self.type == "http":
            if self.chat_completion is None or self.response is None:
                raise ValueError("integration type 'http' needs 'chat_completion' and 'response'")
            if not _contains_prompt(self.chat_completion.payload):
                raise ValueError("chat_completion.payload must contain $PROMPT")
        return self


class ToolCalled(_Strict):
    name: str
    arg_regex: str | None = None


class SuccessCondition(_Strict):
    """Exactly one kind per entry."""

    reply_contains: str | None = None
    reply_regex: str | None = None
    tool_called: ToolCalled | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> SuccessCondition:
        kinds = [
            k
            for k in ("reply_contains", "reply_regex", "tool_called")
            if getattr(self, k) is not None
        ]
        if len(kinds) != 1:
            raise ValueError(
                "each success condition needs exactly one of reply_contains, reply_regex, tool_called"
            )
        return self


# A reference to a published standard, e.g. owasp-llm:LLM02 or atlas:AML.T0051.000. Only the
# shape is checked here: which ids exist is for the catalog to decide, so a standard that
# gains an entry needs no new hb.
REFERENCE_RE = re.compile(r"[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9.]*")


class GroundTruth(_Strict):
    category: str
    description: str
    title: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    vector: Literal["direct", "indirect", "tool-output", "memory", "multi-agent"] | None = None
    success: list[SuccessCondition] | None = None
    references: list[str] | None = Field(default=None, min_length=1)

    @field_validator("references")
    @classmethod
    def _references(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        bad = [r for r in value if not REFERENCE_RE.fullmatch(r)]
        if bad:
            raise ValueError(
                f"each reference must look like <standard>:<id> (e.g. owasp-llm:LLM02), got "
                f"{', '.join(repr(r) for r in bad)}"
            )
        dupes = sorted({r for r in value if value.count(r) > 1})
        if dupes:
            raise ValueError(f"duplicate reference(s): {', '.join(dupes)}")
        return value


class ArenaManifest(_Strict):
    schema_version: int = Field(ge=1, le=SCHEMA_VERSION, strict=False)
    id: str = Field(pattern=AGENT_ID_PATTERN)
    name: str
    version: str = Field(pattern=VERSION_PATTERN)
    developer: Developer
    description: str
    tags: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    agent: AgentBlock
    source: Source
    runtime: Runtime
    integration: Integration
    context: str = Field(default="", max_length=1500)
    ground_truth: dict[str, GroundTruth] = Field(default_factory=dict)

    def agent_yaml(self) -> dict:
        """The embedded agent: block exactly as authored (no injected defaults)."""
        return self.agent.model_dump(mode="json", exclude_unset=True)


def _multiline_ok(path: tuple) -> bool:
    """Long free-text fields where tab and newline are fine."""
    if not path:
        return False
    head = path[0]
    if head in ("description", "context", "agent"):
        return True
    if head == "ground_truth" and len(path) >= 3:
        return path[2] in ("description", "title", "success")
    if head == "integration" and len(path) >= 3:
        return path[2] == "payload"
    return False


def _control_problems(node: Any, path: tuple = ()) -> list[str]:
    where = ".".join(str(p) for p in path) or "<root>"
    if isinstance(node, str):
        if has_control_chars(node, multiline=_multiline_ok(path)):
            return [f"  {where}: contains a control character"]
        return []
    problems: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and has_control_chars(key):
                problems.append(f"  {where}: a key contains a control character")
                continue
            problems += _control_problems(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            problems += _control_problems(value, (*path, i))
    return problems


def parse_manifest(data: Any) -> ArenaManifest:
    if not isinstance(data, dict):
        raise ManifestError("arena.yaml must be a YAML mapping")
    problems = _control_problems(data)
    if problems:
        raise ManifestError("invalid arena.yaml:\n" + "\n".join(problems))
    raw = data.get("schema_version")
    if raw is not None and not isinstance(raw, bool):
        try:
            version = int(raw)
        except (TypeError, ValueError):
            version = None
        if version is not None and version > SCHEMA_VERSION:
            raise ManifestError(
                f"this agent needs a newer hb (manifest schema {version}, this hb reads "
                f"{SCHEMA_VERSION}) → pip install -U humanbound"
            )
    try:
        return ArenaManifest.model_validate(data)
    except ValidationError as e:
        lines = [
            f"  {'.'.join(str(p) for p in err['loc']) or '<root>'}: "
            f"{err['msg'].removeprefix('Value error, ')}"
            for err in e.errors()
        ]
        raise ManifestError("invalid arena.yaml:\n" + "\n".join(lines)) from None


def load_manifest(path: str | Path) -> ArenaManifest:
    path = Path(path)
    try:
        text = read_text_limited(path)
    except (OSError, UnicodeDecodeError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from None
    return parse_manifest(load_yaml(text, str(path)))
