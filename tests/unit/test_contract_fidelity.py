# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Contract fidelity: every API fixture validates against its mirror schema.

This test guards the test suite against a specific class of bug: a mock
response fixture that no longer matches the actual Humanbound API
contract. When it fails, the fail message tells you precisely which
fixture, which schema, and which field is wrong.

Likely causes when this test starts failing:

1. **API contract change.** A mirror in ``tests/unit/_contract/schemas.py``
   added a required field or changed a type. Update the offending fixture
   to match the new mirror.

2. **Fixture drift.** The fixture was authored against an older version of
   the contract and never updated. Rewrite it to match the current mirror.

3. **Real bug in the CLI client.** The client is parsing a field that is
   not actually in the contract. Fix the client code.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.unit._contract.schemas import (
    ApiKeyResponse,
    ExperimentsResponse,
    ExperimentsResponseStatus,
    FindingsResponse,
    GuardrailsExportHumanbound,
    OKMessage,
    OrganisationResponse,
    PaginationResponseApiKeys,
    PaginationResponseExperiments,
    PaginationResponseLogs,
    PaginationResponseProjects,
    ProjectPostureResponse,
    ProjectsResponse,
    ProvidersResponse,
)

# Minimal canonical fixtures. Each is constructed via its mirror schema so
# the default values are guaranteed to be contract-valid. Tests that need
# to override fields do so explicitly — these defaults are the floor.

CONTRACT_CASES = [
    # (label, fixture-builder, schema)
    (
        "ProjectPosture",
        lambda: ProjectPostureResponse(posture=72.5, grade="C").model_dump(),
        ProjectPostureResponse,
    ),
    (
        "PostureDimensions nested",
        lambda: ProjectPostureResponse(
            posture=72.5,
            grade="C",
            dimensions={
                "security": {
                    "posture": 65.0,
                    "grade": "C",
                    "findings": {"open": 3, "critical": 1, "high": 2, "regressed": 0},
                },
                "quality": {"posture": 80.0, "grade": "B"},
            },
        ).model_dump(),
        ProjectPostureResponse,
    ),
    (
        "GuardrailsExport humanbound",
        lambda: GuardrailsExportHumanbound(
            project_id="proj-456",
            source="project_scope",
            source_id="proj-456",
            generated_at="2026-04-21T10:00:00Z",
            scope={
                "overall_business_scope": "Retail banking customer support",
                "intents": {"permitted": ["balance"], "restricted": ["approve_loan"]},
                "more_info": "",
            },
        ).model_dump(),
        GuardrailsExportHumanbound,
    ),
    (
        "Findings page (empty)",
        lambda: FindingsResponse(data=[], total=0, has_next_page=False).model_dump(),
        FindingsResponse,
    ),
    (
        "Findings page (one)",
        lambda: FindingsResponse(
            data=[
                {
                    "id": "find-1",
                    "project_id": "proj-456",
                    "title": "Prompt injection risk",
                    "description": "...",
                    "category": "adversarial",
                    "threat_class": "prompt_injection",
                    "severity": 75.0,
                    "severity_label": "high",
                    "confidence": 0.9,
                    "status": "open",
                    "occurrence_count": 3,
                    "delegation_status": "unassigned",
                }
            ],
            total=1,
            page=1,
            size=50,
            has_next_page=False,
        ).model_dump(),
        FindingsResponse,
    ),
    (
        "Logs page",
        lambda: PaginationResponseLogs(
            data=[
                {
                    "id": "log-1",
                    "result": "fail",
                    "prompt": "...",
                    "severity": "high",
                    "fail_category": "prompt_injection",
                }
            ],
            total=1,
            page=1,
            size=50,
            has_next_page=False,
        ).model_dump(),
        PaginationResponseLogs,
    ),
    (
        "Experiments page",
        lambda: PaginationResponseExperiments(
            data=[
                {
                    "id": "exp-abc",
                    "name": "quick",
                    "status": "Finished",
                    "test_category": "owasp_agentic",
                    "testing_level": "unit",
                }
            ],
            total=1,
            page=1,
            size=50,
            has_next_page=False,
        ).model_dump(),
        PaginationResponseExperiments,
    ),
    (
        "Projects page",
        lambda: PaginationResponseProjects(
            data=[{"id": "proj-456", "name": "Demo", "description": "", "archived": False}],
            total=1,
            page=1,
            size=50,
            has_next_page=False,
        ).model_dump(),
        PaginationResponseProjects,
    ),
    (
        "Experiment single",
        lambda: ExperimentsResponse(
            id="exp-abc",
            name="quick",
            status="Finished",
            test_category="owasp_agentic",
            testing_level="unit",
        ).model_dump(),
        ExperimentsResponse,
    ),
    (
        "Experiment status",
        lambda: ExperimentsResponseStatus(
            id="exp-abc", status="Running", progress=0.42
        ).model_dump(),
        ExperimentsResponseStatus,
    ),
    (
        "Project single",
        lambda: ProjectsResponse(id="proj-456", name="Demo", description="").model_dump(),
        ProjectsResponse,
    ),
    (
        "Provider single",
        lambda: ProvidersResponse(
            id="prov-1", name="openai", integration={"api_key": "sk-..."}
        ).model_dump(),
        ProvidersResponse,
    ),
    (
        "Organisation single",
        lambda: OrganisationResponse(id="org-123", name="Acme").model_dump(),
        OrganisationResponse,
    ),
    (
        "ApiKey single",
        lambda: ApiKeyResponse(
            id="key-1", name="CI", key_prefix="hbk_abc12", status="active"
        ).model_dump(),
        ApiKeyResponse,
    ),
    (
        "ApiKeys page",
        lambda: PaginationResponseApiKeys(
            data=[{"id": "key-1", "name": "CI", "key_prefix": "hbk_abc12", "status": "active"}],
            total=1,
            has_next_page=False,
        ).model_dump(),
        PaginationResponseApiKeys,
    ),
    ("OK envelope", lambda: OKMessage(message="OK").model_dump(), OKMessage),
]


@pytest.mark.parametrize(
    "label, builder, schema",
    CONTRACT_CASES,
    ids=[c[0] for c in CONTRACT_CASES],
)
def test_fixture_matches_contract(label, builder, schema):
    """Each fixture round-trips through its mirror schema."""
    instance = builder()
    try:
        schema.model_validate(instance)
    except ValidationError as e:
        pytest.fail(
            f"Contract drift for {label} against {schema.__name__} "
            f"(mirrors {schema.__upstream_source__}):\n\n{e}\n\n"
            "Fix: update the mirror in tests/unit/_contract/schemas.py "
            "and/or this fixture to match the current API contract."
        )


def test_every_mirror_declares_upstream_source():
    """Every mirror schema must document its upstream-contract identifier.

    This marker is used by the maintainer sync process — a mirror without
    it cannot be automatically checked against upstream.
    """
    from pydantic import BaseModel

    import tests.unit._contract.schemas as mirrors

    missing = []
    for name in mirrors.__all__:
        obj = getattr(mirrors, name, None)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            if not getattr(obj, "__upstream_source__", None):
                missing.append(name)

    assert not missing, (
        f"Contract mirrors missing __upstream_source__: {missing}. "
        "Every mirror must declare its upstream-contract identifier."
    )
