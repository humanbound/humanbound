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

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ..extractors.capabilities.types import CAPABILITY_KEYS
from .keys import is_reserved, is_valid_name

SCHEMA_VERSION = 1
# The one definition of a valid agent id (manifest, catalog index, arena:// targets).
AGENT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
AGENT_ID_RE = re.compile(AGENT_ID_PATTERN)


class ManifestError(ValueError):
    """arena.yaml is unreadable or invalid. The message is ready to show to the user."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
        duplicates = sorted({v for v in value if value.count(v) > 1})
        if duplicates:
            raise ValueError(f"duplicate capability key(s): {', '.join(duplicates)}")
        unknown = sorted(set(value) - set(CAPABILITY_KEYS))
        if unknown:
            raise ValueError(
                f"unknown capability key(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(CAPABILITY_KEYS)}"
            )
        return value


# ── arena fields ──


class Upstream(_Strict):
    repo: str
    ref: str


class Source(_Strict):
    image: str | None = None
    compose: str | None = None
    service: str | None = None
    upstream: Upstream | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Source:
        if bool(self.image) == bool(self.compose):
            raise ValueError("source needs exactly one of 'image' or 'compose'")
        if self.compose and not self.service:
            raise ValueError("source.compose needs 'service' (the compose service to talk to)")
        return self


class Health(_Strict):
    path: str = "/health"
    timeout_s: int = Field(default=60, gt=0)

    @field_validator("path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("must start with '/'")
        return value


class EnvSpec(_Strict):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)

    @field_validator("required", "optional")
    @classmethod
    def _safe_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not is_valid_name(name):
                raise ValueError(f"invalid env var name {name!r}")
            if is_reserved(name):
                raise ValueError(f"{name} is reserved for hb's own credentials")
        return value


class Runtime(_Strict):
    port: int = Field(ge=1, le=65535)
    health: Health = Field(default_factory=Health)
    env: EnvSpec = Field(default_factory=EnvSpec)
    timeout_s: int = Field(default=120, gt=0)


def _contains_prompt_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "$prompt"
    if isinstance(value, dict):
        return any(_contains_prompt_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_prompt_placeholder(v) for v in value)
    return False


class HttpCall(_Strict):
    endpoint: str
    headers: dict[str, str] = Field(default_factory=dict)
    payload: Any = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def _absolute_endpoint(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("endpoint must start with '/'")
        return value


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
    def _absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("integration.path must start with '/'")
        return value

    @model_validator(mode="after")
    def _http_needs_calls(self) -> Integration:
        if self.type == "http" and (self.chat_completion is None or self.response is None):
            raise ValueError("integration type 'http' needs 'chat_completion' and 'response'")
        if self.type == "http" and self.chat_completion is not None:
            if not _contains_prompt_placeholder(self.chat_completion.payload):
                raise ValueError("chat_completion.payload must contain $PROMPT")
        return self


class GroundTruth(_Strict):
    category: str
    description: str


class ArenaManifest(_Strict):
    schema_version: int = Field(ge=1, le=SCHEMA_VERSION, strict=False)
    id: str = Field(pattern=AGENT_ID_PATTERN)
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    origin: Literal["first-party", "community"]
    description: str
    tags: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    agent: AgentBlock
    source: Source
    runtime: Runtime
    integration: Integration
    context: str = Field(default="", max_length=1500)
    ground_truth: dict[str, GroundTruth] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _community_pins_upstream(self) -> ArenaManifest:
        if self.origin == "community" and self.source.upstream is None:
            raise ValueError("community agents must pin source.upstream {repo, ref}")
        return self

    def agent_yaml(self) -> dict:
        """The embedded agent: block as a standalone agent.yaml document."""
        return self.agent.model_dump(mode="json", exclude_unset=True)


def parse_manifest(data: Any) -> ArenaManifest:
    if not isinstance(data, dict):
        raise ManifestError("arena.yaml must be a YAML mapping")
    version = data.get("schema_version")
    if version is not None and not isinstance(version, bool):
        try:
            version_int = int(version)
        except (TypeError, ValueError):
            version_int = None
        if version_int is not None and version_int > SCHEMA_VERSION:
            raise ManifestError(
                f"this agent needs a newer hb (manifest schema {version_int}, this hb reads "
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
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from None
    return parse_manifest(data)
