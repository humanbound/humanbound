# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""TestRunner abstraction — unified interface for test execution.

Two implementations:
- PlatformTestRunner: executes via Humanbound API (requires login)
- LocalTestRunner: executes in-process, results to local files
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TestConfig:
    """Canonical test configuration — identical shape for both runners."""

    test_category: str | None = None  # backend applies its default if None
    testing_level: str | None = None  # unit | system | acceptance — backend defaults if None
    lang: str | None = None  # backend defaults to english if None
    name: str = ""
    description: str = ""
    provider_id: str = ""
    endpoint: dict | None = None  # bot integration config (--endpoint)
    context: str = ""
    auto_start: bool = True
    # Scope sources (local mode only)
    repo_path: str | None = None
    prompt_path: str | None = None
    scope_path: str | None = None
    # Output modes
    debug: bool = False  # single-threaded, full sequential output
    verbose: bool = False  # threaded, Rich Live dashboard


@dataclass
class TestStatus:
    """Canonical status shape — what the CLI polls."""

    experiment_id: str
    status: str  # Created | Generating | Running | Finished | Failed | Terminated
    log_count: int = 0


@dataclass
class TestResult:
    """Canonical result shape — what the CLI renders."""

    experiment_id: str
    name: str
    status: str
    test_category: str = ""
    testing_level: str = ""
    stats: dict = field(default_factory=dict)  # {pass, fail, total, ...}
    insights: list = field(default_factory=list)  # [{result, category, severity, explanation}]
    posture: dict = field(default_factory=dict)  # {posture, grade, defense_rate, ...}
    exec_t: dict = field(default_factory=dict)  # {max_t, min_t, avg_t}


@dataclass
class Posture:
    """Canonical posture shape."""

    overall_score: float | None = None
    grade: str | None = None
    dimensions: dict = field(default_factory=dict)
    recommendations: list = field(default_factory=list)
    last_tested: str | None = None
    # Extended fields (populated when logged in)
    finding_count: int | None = None
    previous_grade: str | None = None
    previous_score: float | None = None


@dataclass
class PaginatedLogs:
    """Canonical paginated log response."""

    data: list = field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 50
    has_next_page: bool = False


class TestRunner(ABC):
    """The CLI talks ONLY to this interface. Never to the engine or API directly."""

    @abstractmethod
    def start(self, config: TestConfig) -> str:
        """Start a test run. Returns experiment_id."""

    @abstractmethod
    def get_status(self, experiment_id: str) -> TestStatus:
        """Poll current status + log count."""

    @abstractmethod
    def get_result(self, experiment_id: str) -> TestResult:
        """Get final results (call after status is terminal)."""

    @abstractmethod
    def get_logs(
        self, experiment_id: str, result: str | None = None, page: int = 1, size: int = 50
    ) -> PaginatedLogs:
        """Get conversation logs (paginated)."""

    @abstractmethod
    def get_posture(self, experiment_id: str | None = None) -> Posture:
        """Get posture score. If no experiment_id, use latest."""

    @abstractmethod
    def terminate(self, experiment_id: str) -> None:
        """Request early termination."""

    @abstractmethod
    def list_experiments(self, page: int = 1, size: int = 50) -> dict:
        """List past experiments."""
