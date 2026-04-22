# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound pytest reporter for terminal output."""

import json
from pathlib import Path

from .fixtures import SEVERITY_LEVELS, Finding, TestResult


class HumanboundReporter:
    """Reporter for Humanbound test results in pytest."""

    def __init__(self, config):
        self.config = config
        self.results: list[TestResult] = []
        self.findings: list[Finding] = []

    def add_result(self, result: TestResult):
        """Add a test result to the report."""
        self.results.append(result)
        self.findings.extend(result.findings)

    def terminal_summary(self, terminalreporter):
        """Print Humanbound summary to terminal."""
        if not self.results and not self.findings:
            return

        tr = terminalreporter
        tr.ensure_newline()
        tr.section("Humanbound Security Summary", sep="=", bold=True)

        # Overall statistics
        total_tests = sum(r.total_tests for r in self.results)
        passed_tests = sum(r.passed_tests for r in self.results)
        failed_tests = sum(r.failed_tests for r in self.results)

        if total_tests > 0:
            pass_rate = (passed_tests / total_tests) * 100
            tr.write_line(f"Tests: {passed_tests}/{total_tests} passed ({pass_rate:.1f}%)")

        # Findings by severity
        if self.findings:
            tr.write_line("")
            tr.write_line("Findings by Severity:")

            severity_counts = {s: 0 for s in SEVERITY_LEVELS}
            for finding in self.findings:
                sev = finding.severity.lower()
                if sev in severity_counts:
                    severity_counts[sev] += 1

            severity_icons = {
                "critical": "!!",
                "high": "! ",
                "medium": "- ",
                "low": ". ",
                "info": "  ",
            }

            for severity in SEVERITY_LEVELS:
                count = severity_counts[severity]
                if count > 0:
                    icon = severity_icons.get(severity, "  ")
                    tr.write_line(f"  {icon} {severity.upper()}: {count}")

        # Top findings
        if self.findings:
            tr.write_line("")
            tr.write_line("Top Findings:")

            # Sort by severity
            sorted_findings = sorted(
                self.findings, key=lambda f: SEVERITY_LEVELS.index(f.severity.lower())
            )

            for finding in sorted_findings[:5]:
                tr.write_line(
                    f"  [{finding.severity.upper()}] {finding.category}: {finding.title[:60]}"
                )

        # Posture score if available
        posture_scores = [r.posture_score for r in self.results if r.posture_score]
        if posture_scores:
            avg_posture = sum(posture_scores) / len(posture_scores)
            tr.write_line("")
            tr.write_line(f"Security Posture: {avg_posture:.0f}/100")

        # Save baseline if requested
        baseline_path = self.config.getoption("--hb-save-baseline")
        if baseline_path:
            self._save_baseline(baseline_path)
            tr.write_line("")
            tr.write_line(f"Baseline saved to: {baseline_path}")

        tr.write_line("")

    def _save_baseline(self, path: str):
        """Save current results as baseline."""
        baseline = {
            "fingerprints": [],
            "results": [],
        }

        for result in self.results:
            baseline["results"].append(result.to_dict())
            for finding in result.findings:
                fingerprint = f"{finding.category}:{finding.title}"
                if fingerprint not in baseline["fingerprints"]:
                    baseline["fingerprints"].append(fingerprint)

        Path(path).write_text(json.dumps(baseline, indent=2))


def format_finding_short(finding: Finding) -> str:
    """Format a finding for short display."""
    return f"[{finding.severity.upper()}] {finding.category}: {finding.title}"


def format_finding_full(finding: Finding) -> str:
    """Format a finding for full display."""
    lines = [
        f"Category: {finding.category}",
        f"Severity: {finding.severity.upper()}",
        f"Title: {finding.title}",
    ]
    if finding.description:
        lines.append(f"Description: {finding.description}")
    if finding.attack_pattern:
        lines.append(f"Attack Pattern: {finding.attack_pattern}")
    return "\n".join(lines)
