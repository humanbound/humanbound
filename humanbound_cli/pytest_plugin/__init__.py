# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound pytest plugin for AI agent security testing.

This plugin provides pytest integration for running Humanbound security tests
as part of your test suite.

Usage:
    # Install with pytest support
    pip install humanbound-cli[pytest]

    # Run security tests
    pytest --hb tests/
    pytest -m hb
    pytest --hb-category=adversarial

    # In your test files
    import pytest

    @pytest.mark.hb
    def test_prompt_injection(hb):
        result = hb.test("llm001")
        assert result.passed, f"Failed: {result.findings}"
"""

import pytest
from typing import Optional
import json
import sys

from .fixtures import HumanboundTestClient
from .report import HumanboundReporter


def pytest_addoption(parser):
    """Add Humanbound command line options."""
    group = parser.getgroup("hb", "Humanbound security testing")

    group.addoption(
        "--hb",
        action="store_true",
        default=False,
        help="Enable Humanbound security tests",
    )

    group.addoption(
        "--hb-category",
        action="store",
        default=None,
        metavar="CATEGORY",
        help="Test category to run (e.g., adversarial, behavioral)",
    )

    group.addoption(
        "--hb-level",
        action="store",
        default="unit",
        metavar="LEVEL",
        choices=["unit", "system", "acceptance"],
        help="Testing level (default: unit)",
    )

    group.addoption(
        "--hb-project",
        action="store",
        default=None,
        metavar="PROJECT_ID",
        help="Project ID to test against (uses config if not specified)",
    )

    group.addoption(
        "--hb-fail-on",
        action="store",
        default="high",
        metavar="SEVERITY",
        choices=["critical", "high", "medium", "low", "any"],
        help="Fail tests on findings at or above this severity (default: high)",
    )

    group.addoption(
        "--hb-baseline",
        action="store",
        default=None,
        metavar="FILE",
        help="Baseline file for regression detection",
    )

    group.addoption(
        "--hb-save-baseline",
        action="store",
        default=None,
        metavar="FILE",
        help="Save current results as baseline",
    )


def pytest_configure(config):
    """Configure pytest with Humanbound markers and settings."""
    # Register markers
    config.addinivalue_line(
        "markers",
        "hb: mark test as a Humanbound security test"
    )
    config.addinivalue_line(
        "markers",
        "hb_category(name): mark test for a specific category (e.g., adversarial)"
    )
    config.addinivalue_line(
        "markers",
        "hb_skip_ci: skip this test in CI environments"
    )

    # Initialize reporter if Humanbound is enabled
    if config.getoption("--hb"):
        config._hb_reporter = HumanboundReporter(config)


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on Humanbound options."""
    if not config.getoption("--hb"):
        # Skip all hb-marked tests if --hb not provided
        skip_hb = pytest.mark.skip(reason="need --hb option to run")
        for item in items:
            if "hb" in item.keywords:
                item.add_marker(skip_hb)
        return

    # Filter by category if specified
    category_filter = config.getoption("--hb-category")
    if category_filter:
        for item in items:
            if "hb" in item.keywords:
                # Check if test has matching category marker
                category_marker = item.get_closest_marker("hb_category")
                if category_marker:
                    if category_marker.args[0] != category_filter:
                        item.add_marker(pytest.mark.skip(
                            reason=f"filtered by --hb-category={category_filter}"
                        ))


def pytest_sessionstart(session):
    """Called before test collection."""
    if session.config.getoption("--hb"):
        # Print Humanbound banner
        print("\n" + "=" * 60)
        print("  Humanbound Security Testing")
        print("=" * 60)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Add Humanbound summary to test report."""
    if not config.getoption("--hb"):
        return

    reporter = getattr(config, "_hb_reporter", None)
    if reporter:
        reporter.terminal_summary(terminalreporter)


@pytest.fixture
def hb(request) -> HumanboundTestClient:
    """Fixture providing Humanbound test client.

    Usage:
        def test_security(hb):
            result = hb.test("llm001")
            assert result.passed
    """
    config = request.config

    return HumanboundTestClient(
        project_id=config.getoption("--hb-project"),
        testing_level=config.getoption("--hb-level"),
        fail_on=config.getoption("--hb-fail-on"),
    )


@pytest.fixture
def hb_baseline(request) -> Optional[dict]:
    """Fixture providing baseline results for regression detection.

    Usage:
        def test_no_regressions(hb, hb_baseline):
            result = hb.test("llm001")
            if hb_baseline:
                regressions = result.compare(hb_baseline)
                assert not regressions
    """
    baseline_path = request.config.getoption("--hb-baseline")
    if not baseline_path:
        return None

    try:
        with open(baseline_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        pytest.fail(f"Invalid baseline file: {baseline_path}")


@pytest.fixture
def hb_posture(hb) -> dict:
    """Fixture providing current security posture.

    Usage:
        def test_posture_threshold(hb_posture):
            assert hb_posture["score"] >= 70, "Posture too low"
    """
    return hb.get_posture()
