# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Engine package — TestRunner abstraction for test execution.

Usage:
    from humanbound_cli.engine import get_runner
    runner = get_runner()
    eid = runner.start(config)
"""

from .runner import PaginatedLogs, Posture, TestConfig, TestResult, TestRunner, TestStatus


def get_runner(force_local: bool = False) -> TestRunner:
    """Select runner based on auth state. This is the ONLY decision point.

    - force_local=True → always LocalTestRunner (--local flag)
    - Headless API key (HUMANBOUND_API_KEY) → always PlatformTestRunner, never a
      silent local fallback: an invalid key/selection surfaces as the backend's
      401/403 instead of quietly running locally.
    - OAuth-authenticated with a selected project → PlatformTestRunner
    - Otherwise → LocalTestRunner
    """
    if force_local:
        from .local_runner import LocalTestRunner

        return LocalTestRunner()

    from ..client import HumanboundClient

    client = HumanboundClient()
    if client.api_key or (client.is_authenticated() and client.project_id):
        from .platform_runner import PlatformTestRunner

        return PlatformTestRunner(client)

    # Not authenticated or no project → local mode
    from .local_runner import LocalTestRunner

    return LocalTestRunner()
