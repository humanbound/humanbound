# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound — open-source red-team engine and SDK.

Public API for authoring orchestrators, driving the engine programmatically,
and integrating Humanbound into pytest / CI / notebooks.

The CLI (`hb test`, `hb report`, etc.) lives in the sibling `humanbound_cli`
module and is considered internal — it may change between releases. Import
from `humanbound` for stability.
"""
from __future__ import annotations

__version__ = "2.0.0"

from humanbound.bot import Bot, ResponseExtractor
from humanbound.schemas import (
    Insight,
    LogEntry,
    LogsAnonymous,
    TestingLevel,
    Turn,
)
from humanbound.callbacks import EngineCallbacks
from humanbound.orchestrators import (
    OrchestratorModule,
    OwaspAgentic,
    OwaspSingleTurn,
    BehavioralQA,
)
from humanbound.runner import LocalRunner

__all__ = [
    "__version__",
    # Target-system adapters
    "Bot",
    "ResponseExtractor",
    # Data contracts
    "Insight",
    "LogEntry",
    "LogsAnonymous",
    "Turn",
    "TestingLevel",
    # Callbacks
    "EngineCallbacks",
    # Runner
    "LocalRunner",
    # Orchestrator ABC + built-ins
    "OrchestratorModule",
    "OwaspAgentic",
    "OwaspSingleTurn",
    "BehavioralQA",
]
