# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Pydantic models for the engine.

These models define the data structures for experiments, logs, and posture scoring.
Field names, types, and nesting follow the API schema for compatibility.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Enums ─────────────────────────────────────────────────────────────────


class TestingLevel(str, Enum):
    Unit = "unit"
    System = "system"
    Acceptance = "acceptance"


class Status(str, Enum):
    Created = "Created"
    Generating = "Generating Dataset"
    Generated = "Dataset Generated"
    Running = "Running"
    Completed = "Completed"
    Analysing = "Analysing Results"
    Finished = "Finished"
    Failed = "Failed"


# ── Scoring Constants ─────────────────────────────────────────────────────

GRADE_BOUNDARIES = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (40, "D"),
    (0, "F"),
]

SEVERITY_LABEL_BOUNDARIES = [
    (75, "critical"),
    (50, "high"),
    (25, "medium"),
    (1, "low"),
    (0, "info"),
]


def score_to_grade(score: float) -> str:
    for threshold, grade in GRADE_BOUNDARIES:
        if score >= threshold:
            return grade
    return "F"


def severity_to_label(severity: float) -> str:
    for threshold, label in SEVERITY_LABEL_BOUNDARIES:
        if severity >= threshold:
            return label
    return "info"


# ── Log Models ────────────────────────────────────────────────────────────


class Turn(BaseModel):
    """A single conversation turn."""

    u: str = ""
    a: str = ""


class LogEntry(BaseModel):
    """Public log entry — 10-field schema for export."""

    thread_id: str = ""
    conversation: list[Turn] = []
    result: str = ""  # pass | fail | error
    gen_category: str = ""
    fail_category: str = ""
    explanation: str = ""
    severity: float = 0
    confidence: float = 0
    exec_t: float = 0
    meta: dict | None = {}  # telemetry data (flattened)


class LogsAnonymous(BaseModel):
    """Internal log entry — used by the orchestrator during execution. Converted to LogEntry on export."""

    thread_id: str = ""
    conversation: list = []
    prompt: str = ""
    response: str = ""
    result: str = ""
    gen_category: str = ""
    fail_category: str = ""
    explanation: str = ""
    severity: float = 0
    confidence: float = 0
    meta: list[dict] | None = []
    exec_t: float = 0
    attack_trace: list[str] | None = None

    def to_public(self) -> LogEntry:
        """Convert to public LogEntry (strip internal fields, flatten meta)."""
        merged_meta = {}
        for item in self.meta or []:
            if isinstance(item, dict):
                merged_meta.update(item)
        return LogEntry(
            thread_id=self.thread_id,
            conversation=[Turn(**t) if isinstance(t, dict) else t for t in self.conversation],
            result=self.result,
            gen_category=self.gen_category,
            fail_category=self.fail_category,
            explanation=self.explanation,
            severity=self.severity,
            confidence=self.confidence,
            exec_t=self.exec_t,
            meta=merged_meta,
        )


# ── Results Models ────────────────────────────────────────────────────────


class ExecT(BaseModel):
    """Execution time statistics."""

    max_t: float = 0
    min_t: float = 0
    avg_t: float = 0


class Stats(BaseModel):
    """Experiment statistics. Uses 'pass' alias for Python keyword."""

    model_config = ConfigDict(populate_by_name=True)

    reliability: float = 0
    pass_: int = Field(alias="pass", default=0)
    fail: int = 0
    total: int = 0
    error: int = 0
    fail_impact: float = 0
    total_perfomance_index: float | None = 0

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return super().model_dump(by_alias=True, **kwargs)


class Insight(BaseModel):
    """Per-experiment analysis insight."""

    result: str = ""
    category: str | None = ""
    severity: float | str | None = 0
    explanation: str | None = ""
    examples: list | None = []
    count: int | None = None  # local-only: number of logs in this category


# ── Posture Models ────────────────────────────────────────────────────────


class PostureDimension(BaseModel):
    """Score for a single dimension (security or quality)."""

    posture: float = 0.0
    grade: str = "F"


class PostureDimensions(BaseModel):
    """Container for dimension-level posture scores."""

    security: PostureDimension | None = None
    quality: PostureDimension | None = None


class ExperimentPosture(BaseModel):
    """Experiment-level posture computed from ASR."""

    posture: float = 0
    grade: str = "F"
    tests: int = 0
    defense_rate: float = 0
    confidence: str = "low"
    domain: str = "security"
    breach_breadth: float = 0
    breached: list[str] = []
    defended: list[str] = []


# ── Experiment Results ─────────────────────────────────────────────────────


class ExperimentResults(BaseModel):
    """Complete experiment results — output of the presenter."""

    stats: Stats = Stats()
    insights: list[Insight] = []
    posture: ExperimentPosture | None = None
    exec_t: ExecT = ExecT()

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return super().model_dump(by_alias=True, **kwargs)


# ── Experiment Meta ───────────────────────────────────────────────────────


class ExperimentMeta(BaseModel):
    """Experiment output — meta.json schema."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str = ""
    status: str = "Created"
    test_category: str = ""
    testing_level: str = ""
    lang: str = "english"
    results: ExperimentResults = ExperimentResults()
    created_at: str = ""
    completed_at: str | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Always dump with aliases (pass_ → pass) for API compatibility."""
        return super().model_dump(by_alias=True, **kwargs)
