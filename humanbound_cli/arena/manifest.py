# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The arena.yaml manifest.

Arena fields sit at the top level; the agent's Humanbound agent.yaml is embedded
unchanged under `agent:`, so `manifest.agent_yaml()` is itself a valid agent.yaml.
"""

from __future__ import annotations

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

SCHEMA_VERSION = 1


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
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def _known_capabilities(cls, value: list[str]) -> list[str]:
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
    timeout_s: int = 60


class EnvSpec(_Strict):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class Runtime(_Strict):
    port: int = Field(ge=1, le=65535)
    health: Health = Field(default_factory=Health)
    env: EnvSpec = Field(default_factory=EnvSpec)
    timeout_s: int = 120


class HttpCall(_Strict):
    endpoint: str
    headers: dict[str, str] = Field(default_factory=dict)
    payload: Any = Field(default_factory=dict)


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

    @model_validator(mode="after")
    def _http_needs_calls(self) -> Integration:
        if self.type == "http" and (self.chat_completion is None or self.response is None):
            raise ValueError("integration type 'http' needs 'chat_completion' and 'response'")
        return self


class GroundTruth(_Strict):
    category: str
    description: str


class ArenaManifest(_Strict):
    schema_version: int
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
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
    context: str = ""
    ground_truth: dict[str, GroundTruth] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _community_pins_upstream(self) -> ArenaManifest:
        if self.origin == "community" and self.source.upstream is None:
            raise ValueError("community agents must pin source.upstream {repo, ref}")
        return self

    def agent_yaml(self) -> dict:
        """The embedded agent: block as a standalone agent.yaml document."""
        return self.agent.model_dump(mode="json", exclude_none=True)


def parse_manifest(data: Any) -> ArenaManifest:
    if not isinstance(data, dict):
        raise ManifestError("arena.yaml must be a YAML mapping")
    version = data.get("schema_version")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise ManifestError(
            f"this agent needs a newer hb (manifest schema {version}, this hb reads "
            f"{SCHEMA_VERSION}) → pip install -U humanbound"
        )
    try:
        return ArenaManifest.model_validate(data)
    except ValidationError as e:
        lines = [
            f"  {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in e.errors()
        ]
        raise ManifestError("invalid arena.yaml:\n" + "\n".join(lines)) from None


def load_manifest(path: str | Path) -> ArenaManifest:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from None
    return parse_manifest(data)
