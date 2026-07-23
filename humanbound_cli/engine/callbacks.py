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

    flush_every_log: bool = False
    """Flush each completed conversation to on_logs immediately, even after
    termination. Set by in-process runners so an interrupt keeps finished work."""

    def should_flush_every(self) -> bool:
        """Flush per conversation instead of buffering (local sinks, debug runs)."""
        return self.flush_every_log or self.max_workers == 1

    def deliver_logs(self, logs: list) -> None:
        """Hand completed logs to on_logs. Cancellation stops new work, not
        delivery of finished work; batched sinks still suppress post-cancel."""
        if not logs:
            return
        if self.is_terminated() and not self.flush_every_log:
            return
        self.on_logs(list(logs))


def log_buffer_len(callbacks: EngineCallbacks | None, default: int) -> int:
    """Orchestrator log-batching size: 0 (flush every log) when the sink asks
    for it, else the orchestrator's default."""
    return 0 if callbacks and callbacks.should_flush_every() else default
