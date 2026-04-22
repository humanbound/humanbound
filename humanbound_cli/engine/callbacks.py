# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Engine callbacks — injected into the orchestrator to decouple from external I/O.

These callbacks abstract the I/O layer so the engine can run in any environment.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class EngineCallbacks:
    """Injected into the orchestrator to replace external I/O."""

    on_logs: Callable[[list], None] = lambda logs: None
    """Called when a batch of logs is ready."""

    on_complete: Callable[[str], None] = lambda status: None
    """Called when the orchestrator finishes."""

    is_terminated: Callable[[], bool] = lambda: False
    """Check if experiment was cancelled."""

    on_error: Callable[[str, dict], None] = lambda title, details: None
    """Called on non-fatal errors for error logging."""

    get_strategies: Callable[[str], list] = lambda project_id: []
    """Get cross-session attack strategies."""

    on_turn: Callable[[dict], None] = lambda turn_info: None
    """Called after each conversation turn (debug mode). turn_info dict has: category, turn, total_turns, user_msg, bot_response, score."""

    on_verdict: Callable[[dict], None] = lambda verdict_info: None
    """Called after each conversation is judged. verdict_info dict has: category, strategy, result, severity, confidence, explanation, turns, exec_t."""

    max_workers: int = 0
    """Override max thread workers. 0 = use default. 1 = single-threaded (debug mode)."""
