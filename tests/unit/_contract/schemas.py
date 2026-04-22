# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Contract mirrors for the Humanbound API responses the CLI consumes.

These are hand-authored Pydantic v2 mirrors of the documented API response
shapes. Each mirror declares:

- ``model_config = ConfigDict(extra="allow")`` so benign upstream additions
  don't fail CLI tests (only removals / type changes / new *required* fields
  do).
- An ``__upstream_source__`` identifier used by the maintainer sync process
  when mirrors need to be refreshed against upstream schema changes.
- Default values chosen so ``Model().model_dump()`` produces a minimally
  valid test fixture.

Paired with ``tests/unit/test_contract_fidelity.py``, these mirrors provide
the contract-validation layer for every API-response fixture in the test
suite.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# ──────────────────────────────────────────────────────────────────────────
# Base / common envelopes
# ──────────────────────────────────────────────────────────────────────────


class OKMessage(BaseModel):
    """Generic success envelope returned from mutating endpoints."""

    __upstream_source__ = "Base.OKMessage"
    model_config = ConfigDict(extra="allow")

    message: str = "OK"


# ──────────────────────────────────────────────────────────────────────────
# Paginated list envelopes
# ──────────────────────────────────────────────────────────────────────────


class PaginationResponseLogs(BaseModel):
    """Paginated response for log listings."""

    __upstream_source__ = "Paginator.PaginationResponse_Logs"
    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]] = []
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


class PaginationResponseExperiments(BaseModel):
    """Paginated response for experiment listings."""

    __upstream_source__ = "Paginator.PaginationResponse_ExperimentsResponse"
    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]] = []
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


class PaginationResponseProjects(BaseModel):
    """Paginated response for project listings."""

    __upstream_source__ = "Paginator.PaginationResponse_ProjectsResponse"
    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]] = []
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


class PaginationResponseApiKeys(BaseModel):
    """Paginated response for API key listings."""

    __upstream_source__ = "Paginator.PaginationResponse_ApiKeysResponse"
    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]] = []
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Posture
# ──────────────────────────────────────────────────────────────────────────


class FindingsSummary(BaseModel):
    """Findings-stats block used at dimension, project, and org levels."""

    __upstream_source__ = "Posture.FindingsSummary"
    model_config = ConfigDict(extra="allow")

    open: int = 0
    critical: int = 0
    high: int = 0
    regressed: int = 0


class PostureDimension(BaseModel):
    """Score for a single dimension (security / quality)."""

    __upstream_source__ = "Posture.PostureDimension"
    model_config = ConfigDict(extra="allow")

    posture: float = 0.0
    grade: str = "F"
    findings: FindingsSummary | None = None


class PostureDimensions(BaseModel):
    """Container for dimension-level posture scores."""

    __upstream_source__ = "Posture.PostureDimensions"
    model_config = ConfigDict(extra="allow")

    security: PostureDimension | None = None
    quality: PostureDimension | None = None


class ProjectPostureResponse(BaseModel):
    """GET /projects/{id}/posture."""

    __upstream_source__ = "Posture.ProjectPosture"
    model_config = ConfigDict(extra="allow")

    posture: float = 0.0
    grade: str = "F"
    dimensions: PostureDimensions | None = None
    stale: bool = False
    evaluated_at: float | None = None
    findings: FindingsSummary | None = None


class OrgPostureResponse(BaseModel):
    """GET /organisations/{id}/posture."""

    __upstream_source__ = "Posture.OrgPosture"
    model_config = ConfigDict(extra="allow")

    posture: float = 0.0
    grade: str = "F"
    dimensions: PostureDimensions | None = None


class PostureTrendSnapshot(BaseModel):
    """Single point on a posture trend line."""

    __upstream_source__ = "PostureSnapshot.PostureTrendSnapshot"
    model_config = ConfigDict(extra="allow")

    captured_at: str = ""
    posture: float = 0.0
    grade: str = "F"


class PostureTrendsResponse(BaseModel):
    """GET /projects/{id}/posture/trends."""

    __upstream_source__ = "PostureSnapshot.PostureTrendsResponse"
    model_config = ConfigDict(extra="allow")

    snapshots: list[PostureTrendSnapshot] = []
    granularity: str = "daily"


# ──────────────────────────────────────────────────────────────────────────
# Findings
# ──────────────────────────────────────────────────────────────────────────


class FindingResponse(BaseModel):
    """A single finding record."""

    __upstream_source__ = "Finding.FindingResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    project_id: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    threat_class: str = ""
    severity: float = 0.0
    severity_label: str = "info"
    confidence: float = 0.0
    status: str = "open"
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    fixed_at: str | None = None
    occurrence_count: int = 0
    assignee_id: str | None = None
    delegation_status: str = "unassigned"


class FindingsResponse(BaseModel):
    """Paginated response for GET /projects/{id}/findings."""

    __upstream_source__ = "Finding.FindingsResponse"
    model_config = ConfigDict(extra="allow")

    data: list[FindingResponse] = []
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Projects
# ──────────────────────────────────────────────────────────────────────────


class ProjectsResponse(BaseModel):
    """Single project record."""

    __upstream_source__ = "Project.ProjectsResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    description: str = ""
    scope: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    api_key_prefix: str | None = None
    archived: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Experiments
# ──────────────────────────────────────────────────────────────────────────


class ExperimentsResponse(BaseModel):
    """Single experiment record."""

    __upstream_source__ = "Experiment.ExperimentsResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    status: str = "Created"
    test_category: str = ""
    testing_level: str = "unit"
    created_at: str | None = None
    updated_at: str | None = None


class ExperimentsResponseStatus(BaseModel):
    """Experiment status polling response."""

    __upstream_source__ = "Experiment.ExperimentsResponseStatus"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    status: str = "Created"
    progress: float = 0.0


# ──────────────────────────────────────────────────────────────────────────
# Providers
# ──────────────────────────────────────────────────────────────────────────


class ProvidersResponse(BaseModel):
    """Single model provider record."""

    __upstream_source__ = "Provider.ProvidersResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    integration: dict[str, Any] = {}


# ──────────────────────────────────────────────────────────────────────────
# API keys
# ──────────────────────────────────────────────────────────────────────────


class ApiKeyResponse(BaseModel):
    """Single API key record (full key returned only on create)."""

    __upstream_source__ = "ApiKey.ApiKeyResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    key_prefix: str = ""
    api_key: str | None = None
    status: str = "active"
    created_at: str | None = None
    expires_at: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# Organisations
# ──────────────────────────────────────────────────────────────────────────


class OrganisationResponse(BaseModel):
    """Single organisation record."""

    __upstream_source__ = "Organisation.OrganisationResponse"
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    created_at: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# Guardrails export
# ──────────────────────────────────────────────────────────────────────────


class GuardrailsExportHumanbound(BaseModel):
    """GET /projects/{id}/guardrails/export/humanbound — native export shape.

    The upstream endpoint declares a generic ``dict`` response type; this
    mirror captures the actual payload shape the CLI relies on.
    """

    __upstream_source__ = "guardrails_export.humanbound"
    model_config = ConfigDict(extra="allow")

    vendor: str = "humanbound"
    framework: str = "humanbound-policy-framework"
    version: str = "1.0"
    project_id: str = ""
    source: str = "project_scope"
    source_id: str = ""
    generated_at: str = ""
    scope: dict[str, Any] = {}


# ──────────────────────────────────────────────────────────────────────────
# Endpoint → response-schema registry
# ──────────────────────────────────────────────────────────────────────────

ENDPOINT_CONTRACTS = {
    "GET /projects/{id}/posture": ProjectPostureResponse,
    "GET /organisations/{id}/posture": OrgPostureResponse,
    "GET /projects/{id}/posture/trends": PostureTrendsResponse,
    "GET /projects/{id}/findings": FindingsResponse,
    "GET /projects/{id}/logs/...": PaginationResponseLogs,
    "GET /experiments": PaginationResponseExperiments,
    "GET /projects": PaginationResponseProjects,
    "GET /experiments/{id}": ExperimentsResponse,
    "GET /experiments/{id}/status": ExperimentsResponseStatus,
    "GET /projects/{id}/guardrails/export/humanbound": GuardrailsExportHumanbound,
    "GET /api-keys": PaginationResponseApiKeys,
    "GET /api-keys/{id}": ApiKeyResponse,
    "GET /providers": ProvidersResponse,
    "GET /organisations/{id}": OrganisationResponse,
    "GET /projects/{id}": ProjectsResponse,
    "generic OK": OKMessage,
}


__all__ = [
    # Envelopes
    "OKMessage",
    "PaginationResponseLogs",
    "PaginationResponseExperiments",
    "PaginationResponseProjects",
    "PaginationResponseApiKeys",
    # Posture
    "FindingsSummary",
    "PostureDimension",
    "PostureDimensions",
    "ProjectPostureResponse",
    "OrgPostureResponse",
    "PostureTrendSnapshot",
    "PostureTrendsResponse",
    # Findings
    "FindingResponse",
    "FindingsResponse",
    # Projects / experiments
    "ProjectsResponse",
    "ExperimentsResponse",
    "ExperimentsResponseStatus",
    # Providers / keys / orgs
    "ProvidersResponse",
    "ApiKeyResponse",
    "OrganisationResponse",
    # Guardrails
    "GuardrailsExportHumanbound",
    # Registry
    "ENDPOINT_CONTRACTS",
]
