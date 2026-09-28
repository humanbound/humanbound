"""Unit tests for PlatformTestRunner — mocked client, no live API."""

from unittest.mock import MagicMock

import pytest

from humanbound_cli.engine.platform_runner import PlatformTestRunner
from humanbound_cli.exceptions import APIError


def _runner(get):
    client = MagicMock()
    client.project_id = "proj-456"
    client.get.side_effect = get
    client.list_findings.return_value = {"total": 3}
    client.get_posture_trends.return_value = {"data_points": []}
    return PlatformTestRunner(client)


def test_get_posture_reads_score_from_posture_field():
    posture = _runner(lambda *a, **k: {"posture": 62.68, "grade": "C"}).get_posture()
    assert posture.overall_score == 62.68
    assert posture.grade == "C"
    assert posture.finding_count == 3


def test_get_posture_surfaces_api_errors():
    with pytest.raises(APIError):
        _runner(APIError("Internal Server Error", status_code=500)).get_posture()
