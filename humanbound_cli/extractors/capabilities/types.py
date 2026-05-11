# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Public dataclasses for the capability scanner."""

from __future__ import annotations

from dataclasses import dataclass, field

CAPABILITY_KEYS = ("tools", "memory", "inter_agent", "reasoning_model")


@dataclass
class CapabilityEvidence:
    capability: str
    signal: str
    file: str
    line: int
    snippet: str


@dataclass
class CapabilityScanResult:
    capabilities: dict[str, bool]
    evidence: list[CapabilityEvidence] = field(default_factory=list)
    files_scanned: int = 0
    languages_scanned: dict[str, int] = field(default_factory=dict)
    skipped_files: int = 0
