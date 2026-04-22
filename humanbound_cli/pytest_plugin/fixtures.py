# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound pytest fixtures and test client."""

import time
from dataclasses import dataclass, field

from ..client import HumanboundClient
from ..exceptions import APIError, NotAuthenticatedError

# Test categories available
TEST_CATEGORIES = [
    "adversarial",
    "behavioral",
    "owasp_single_turn",
    "owasp_multi_turn",
    "owasp_agentic_multi_turn",
]

# Severity levels in order
SEVERITY_LEVELS = ["critical", "high", "medium", "low", "info"]


@dataclass
class Finding:
    """Represents a security finding."""

    category: str
    severity: str
    title: str
    description: str
    log_id: str | None = None
    attack_pattern: str | None = None

    def __str__(self):
        return f"[{self.severity.upper()}] {self.category}: {self.title}"


@dataclass
class TestResult:
    """Result of a Humanbound security test."""

    category: str
    passed: bool
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    findings: list[Finding] = field(default_factory=list)
    experiment_id: str | None = None
    duration_seconds: float = 0.0
    posture_score: float | None = None

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100

    def has_severity(self, min_severity: str) -> bool:
        """Check if any finding meets minimum severity threshold."""
        if not self.findings:
            return False

        min_index = SEVERITY_LEVELS.index(min_severity)
        for finding in self.findings:
            finding_index = SEVERITY_LEVELS.index(finding.severity.lower())
            if finding_index <= min_index:
                return True
        return False

    def compare(self, baseline: dict) -> list[Finding]:
        """Compare results to baseline and return regressions."""
        regressions = []
        baseline_fingerprints = set(baseline.get("fingerprints", []))

        for finding in self.findings:
            # Simple fingerprint based on category and title
            fingerprint = f"{finding.category}:{finding.title}"
            if fingerprint not in baseline_fingerprints:
                regressions.append(finding)

        return regressions

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "category": self.category,
            "passed": self.passed,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                }
                for f in self.findings
            ],
            "fingerprints": [f"{f.category}:{f.title}" for f in self.findings],
            "experiment_id": self.experiment_id,
            "duration_seconds": self.duration_seconds,
            "posture_score": self.posture_score,
        }


class HumanboundTestClient:
    """Test client for running Humanbound security tests in pytest."""

    def __init__(
        self,
        project_id: str | None = None,
        testing_level: str = "unit",
        fail_on: str = "high",
    ):
        self.client = HumanboundClient()
        self.project_id = project_id or self.client.project_id
        self.testing_level = testing_level
        self.fail_on = fail_on

        if not self.client.is_authenticated():
            raise NotAuthenticatedError("Not authenticated. Run 'hb login' first.")

        if not self.project_id:
            raise ValueError("No project selected. Use --hb-project or run 'hb projects use <id>'")

    def test(
        self,
        category: str,
        testing_level: str | None = None,
        wait: bool = True,
        timeout: int = 3600,
    ) -> TestResult:
        """Run a security test for the given category.

        Args:
            category: Test category (e.g., "llm001", "adversarial")
            testing_level: Override testing level
            wait: Wait for completion
            timeout: Max wait time in seconds

        Returns:
            TestResult with findings and statistics
        """
        level = testing_level or self.testing_level
        start_time = time.time()

        # Map short codes to full category names
        category_map = {
            "llm001": "owasp_single_turn",
            "llm002": "owasp_single_turn",
            "llm006": "owasp_single_turn",
            "llm007": "owasp_single_turn",
            "llm009": "owasp_single_turn",
            "t15": "adversarial",
        }

        test_category = category_map.get(category, category)
        if test_category not in TEST_CATEGORIES:
            test_category = "owasp_single_turn"

        # Create experiment
        try:
            experiment = self.client.create_experiment(
                test_category=test_category,
                testing_level=level,
                name=f"pytest-{category}-{int(time.time())}",
            )
            experiment_id = experiment.get("id")
        except APIError as e:
            return TestResult(
                category=category,
                passed=False,
                findings=[
                    Finding(
                        category="error",
                        severity="critical",
                        title="Failed to create experiment",
                        description=str(e),
                    )
                ],
            )

        if not wait:
            return TestResult(
                category=category,
                passed=True,  # Unknown until complete
                experiment_id=experiment_id,
            )

        # Wait for completion
        result = self._wait_for_completion(experiment_id, timeout)
        result.duration_seconds = time.time() - start_time

        # Determine pass/fail based on fail_on threshold
        result.passed = not result.has_severity(self.fail_on)

        return result

    def _wait_for_completion(self, experiment_id: str, timeout: int) -> TestResult:
        """Wait for experiment to complete and return results."""
        start_time = time.time()
        poll_interval = 5

        while time.time() - start_time < timeout:
            try:
                experiment = self.client.get_experiment(experiment_id)
                status = experiment.get("status", "")

                if status == "completed":
                    return self._parse_results(experiment)
                elif status in ("failed", "terminated"):
                    return TestResult(
                        category=experiment.get("test_category", "unknown"),
                        passed=False,
                        experiment_id=experiment_id,
                        findings=[
                            Finding(
                                category="error",
                                severity="critical",
                                title=f"Experiment {status}",
                                description=experiment.get("error_message", "Unknown error"),
                            )
                        ],
                    )

                time.sleep(poll_interval)

            except APIError as e:
                return TestResult(
                    category="unknown",
                    passed=False,
                    experiment_id=experiment_id,
                    findings=[
                        Finding(
                            category="error",
                            severity="critical",
                            title="API error while waiting",
                            description=str(e),
                        )
                    ],
                )

        # Timeout
        return TestResult(
            category="unknown",
            passed=False,
            experiment_id=experiment_id,
            findings=[
                Finding(
                    category="error",
                    severity="high",
                    title="Experiment timeout",
                    description=f"Experiment did not complete within {timeout} seconds",
                )
            ],
        )

    def _parse_results(self, experiment: dict) -> TestResult:
        """Parse experiment results into TestResult."""
        results = experiment.get("results", {})
        stats = results.get("stats", {})
        insights = results.get("insights", [])

        findings = []
        for insight in insights:
            findings.append(
                Finding(
                    category=insight.get("category", "unknown"),
                    severity=insight.get("severity", "medium"),
                    title=insight.get("title", insight.get("explanation", "")[:100]),
                    description=insight.get("explanation", ""),
                    attack_pattern=insight.get("attack_pattern"),
                )
            )

        return TestResult(
            category=experiment.get("test_category", "unknown"),
            passed=len(findings) == 0,
            total_tests=stats.get("total", 0),
            passed_tests=stats.get("pass", 0),
            failed_tests=stats.get("fail", 0),
            findings=findings,
            experiment_id=experiment.get("id"),
        )

    def get_posture(self) -> dict:
        """Get current security posture for the project."""
        try:
            response = self.client.get(
                f"projects/{self.project_id}/posture",
                include_project=True,
            )
            return response
        except APIError:
            # Fallback: calculate from recent experiments
            return self._calculate_posture_fallback()

    def _calculate_posture_fallback(self) -> dict:
        """Calculate posture from recent experiments when endpoint unavailable."""
        try:
            response = self.client.list_experiments(page=1, size=5)
            experiments = response.get("data", [])

            if not experiments:
                return {"score": 0, "grade": "F", "message": "No experiments found"}

            # Simple calculation from pass rates
            total_pass = 0
            total_tests = 0

            for exp in experiments:
                stats = exp.get("results", {}).get("stats", {})
                total_pass += stats.get("pass", 0)
                total_tests += stats.get("total", 0)

            if total_tests > 0:
                score = (total_pass / total_tests) * 100
            else:
                score = 0

            return {
                "score": round(score, 1),
                "grade": self._score_to_grade(score),
                "experiments_analyzed": len(experiments),
            }

        except APIError as e:
            return {"score": 0, "grade": "F", "error": str(e)}

    @staticmethod
    def _score_to_grade(score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def quick_scan(self, categories: list[str] | None = None) -> TestResult:
        """Run a quick security scan across multiple categories.

        Args:
            categories: Categories to test (default: top 5 OWASP)

        Returns:
            Combined TestResult
        """
        if categories is None:
            categories = ["llm001", "llm006", "llm007"]

        all_findings = []
        total_tests = 0
        passed_tests = 0

        for cat in categories:
            result = self.test(cat, testing_level="unit", wait=True, timeout=300)
            all_findings.extend(result.findings)
            total_tests += result.total_tests
            passed_tests += result.passed_tests

        combined = TestResult(
            category="quick_scan",
            passed=not any(f.severity in ["critical", "high"] for f in all_findings),
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_tests=total_tests - passed_tests,
            findings=all_findings,
        )

        return combined
