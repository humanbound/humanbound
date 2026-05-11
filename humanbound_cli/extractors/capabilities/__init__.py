# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Deterministic capability scanner.

Scans an agent repository for evidence of:
  - tools (function-call decorators, MCP tool defs, OpenAI tool schemas, ...)
  - memory (RAG indices, vector DBs, kv stores)
  - inter_agent (multi-agent topologies, agent-to-agent calls)
  - reasoning_model (o1/o3/extended-thinking flags)

Results feed scope.capabilities on the project (per BE PR #34).
"""

from .scanner import scan_capabilities
from .types import CAPABILITY_KEYS, CapabilityEvidence, CapabilityScanResult

__all__ = [
    "CAPABILITY_KEYS",
    "CapabilityEvidence",
    "CapabilityScanResult",
    "scan_capabilities",
]
