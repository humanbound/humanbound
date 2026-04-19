"""Engine package — TestRunner abstraction for test execution.

Usage:
    from humanbound_cli.engine import get_runner
    runner = get_runner()
    eid = runner.start(config)
"""

from .runner import TestRunner, TestConfig, TestStatus, TestResult, Posture, PaginatedLogs


def get_runner(force_local: bool = False) -> TestRunner:
    """Select runner based on auth state. This is the ONLY decision point.

    - force_local=True → always LocalTestRunner (--local flag)
    - Authenticated → PlatformTestRunner
    - Not authenticated → LocalTestRunner
    """
    if force_local:
        from .local_runner import LocalTestRunner
        return LocalTestRunner()

    from ..client import HumanboundClient
    client = HumanboundClient()
    if client.is_authenticated() and client.project_id:
        from .platform_runner import PlatformTestRunner
        return PlatformTestRunner(client)

    # Not authenticated or no project → local mode
    from .local_runner import LocalTestRunner
    return LocalTestRunner()
