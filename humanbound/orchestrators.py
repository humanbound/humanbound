# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Orchestrators — the standard contract for attack campaigns.

Built-in orchestrators and the `OrchestratorModule` ABC for authoring
custom ones. Plugin authors inherit from `OrchestratorModule`.
"""
from humanbound_cli.engine.orchestrators.base import OrchestratorModule  # noqa: F401
from humanbound_cli.engine.orchestrators import owasp_agentic as _oa
from humanbound_cli.engine.orchestrators import owasp_single_turn as _ost
from humanbound_cli.engine.orchestrators import behavioral_qa as _bqa


# Built-ins exposed as modules (callers use orchestrator_generate / orchestrator_run).
OwaspAgentic = _oa
OwaspSingleTurn = _ost
BehavioralQA = _bqa


__all__ = [
    "OrchestratorModule",
    "OwaspAgentic",
    "OwaspSingleTurn",
    "BehavioralQA",
]
