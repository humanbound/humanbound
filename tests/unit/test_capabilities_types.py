# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Smoke test for capability extractor type definitions."""

from humanbound_cli.extractors.capabilities import (
    CapabilityEvidence,
    CapabilityScanResult,
)


def test_capability_evidence_is_dataclass_with_expected_fields():
    ev = CapabilityEvidence(
        capability="tools",
        signal="@mcp.tool decorator",
        file="agent/server.py",
        line=42,
        snippet="@mcp.tool",
    )
    assert ev.capability == "tools"
    assert ev.line == 42


def test_capability_scan_result_defaults():
    result = CapabilityScanResult(
        capabilities={
            "tools": False,
            "memory": False,
            "inter_agent": False,
            "reasoning_model": False,
        },
        evidence=[],
        files_scanned=0,
        languages_scanned={},
        skipped_files=0,
    )
    assert result.capabilities["tools"] is False
    assert result.evidence == []
