"""PlatformTestRunner — wraps existing HumanboundClient into TestRunner interface.

This is a thin adapter. No new logic — just translates between the TestRunner
canonical shapes and the existing API responses. The platform backend is unchanged.
"""

from typing import Optional

from .runner import TestRunner, TestConfig, TestStatus, TestResult, Posture, PaginatedLogs


class PlatformTestRunner(TestRunner):
    """Wraps HumanboundClient for platform execution. Same HTTP calls as current CLI."""

    def __init__(self, client):
        """
        Args:
            client: Authenticated HumanboundClient instance with project selected.
        """
        self.client = client

    def start(self, config: TestConfig) -> str:
        experiment_data = {
            "name": config.name,
            "description": config.description,
            "test_category": config.test_category,
            "testing_level": config.testing_level,
            "lang": config.lang,
            "auto_start": config.auto_start,
        }

        if config.provider_id:
            experiment_data["provider_id"] = config.provider_id

        configuration = {}
        if config.endpoint:
            configuration["integration"] = config.endpoint
        if config.context:
            configuration["context"] = config.context
        if configuration:
            experiment_data["configuration"] = configuration

        response = self.client.post(
            "experiments",
            data=experiment_data,
            include_project=True,
        )
        return response.get("id", "")

    def get_status(self, experiment_id: str) -> TestStatus:
        status_resp = self.client.get_experiment_status(experiment_id)
        # Also fetch log count from experiment results
        try:
            exp = self.client.get_experiment(experiment_id)
            stats = exp.get("results", {}).get("stats", {})
            log_count = stats.get("total", 0)
        except Exception:
            log_count = 0

        return TestStatus(
            experiment_id=experiment_id,
            status=status_resp.get("status", "Unknown"),
            log_count=log_count,
        )

    def get_result(self, experiment_id: str) -> TestResult:
        exp = self.client.get_experiment(experiment_id)
        results = exp.get("results", {})

        return TestResult(
            experiment_id=experiment_id,
            name=exp.get("name", ""),
            status=exp.get("status", "Unknown"),
            test_category=exp.get("test_category", ""),
            testing_level=exp.get("testing_level", ""),
            stats=results.get("stats", {}),
            insights=results.get("insights", []),
            posture=results.get("posture", {}),
            exec_t=results.get("exec_t", {}),
        )

    def get_logs(self, experiment_id: str, result: Optional[str] = None,
                 page: int = 1, size: int = 50) -> PaginatedLogs:
        resp = self.client.get_experiment_logs(
            experiment_id, page=page, size=size, result=result,
        )
        return PaginatedLogs(
            data=resp.get("data", []),
            total=resp.get("total", 0),
            page=resp.get("page", page),
            size=resp.get("size", size),
            has_next_page=resp.get("has_next_page", False),
        )

    def get_posture(self, experiment_id: Optional[str] = None) -> Posture:
        project_id = self.client.project_id
        if not project_id:
            return Posture()

        try:
            resp = self.client.get(
                f"projects/{project_id}/posture",
                include_project=True,
            )
        except Exception:
            return Posture()

        posture = Posture(
            overall_score=resp.get("overall_score"),
            grade=resp.get("grade"),
            dimensions=resp.get("dimensions", {}),
            recommendations=resp.get("recommendations", []),
            last_tested=resp.get("last_tested"),
        )

        # Fetch open finding count
        try:
            findings_resp = self.client.list_findings(
                project_id, status="open", page=1, size=1,
            )
            if isinstance(findings_resp, dict):
                posture.finding_count = findings_resp.get("total", 0)
        except Exception:
            pass

        # Fetch previous posture for delta
        try:
            trends = self.client.get_posture_trends(project_id)
            data_points = trends.get("data_points", []) if isinstance(trends, dict) else []
            if len(data_points) >= 2:
                prev = data_points[-2]
                posture.previous_grade = prev.get("grade")
                posture.previous_score = prev.get("score")
        except Exception:
            pass

        return posture

    def terminate(self, experiment_id: str) -> None:
        self.client.put(
            f"experiments/{experiment_id}/terminate",
            data={},
            include_project=True,
        )

    def list_experiments(self, page: int = 1, size: int = 50) -> dict:
        return self.client.list_experiments(page=page, size=size)
