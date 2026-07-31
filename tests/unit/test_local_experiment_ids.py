# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Regression tests for collision-safe local experiment allocation."""

import re
import uuid
from unittest.mock import patch

from humanbound_cli.engine.local_runner import LocalTestRunner, _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig


def _config():
    return _TestConfig(endpoint={"chat_completion": {"endpoint": "http://example.test"}})


def test_starts_in_same_second_get_distinct_ids_and_result_directories(tmp_path, monkeypatch):
    """Concurrent-in-time starts reserve separate slots before their threads run."""
    monkeypatch.chdir(tmp_path)

    with (
        patch("humanbound_cli.engine.local_runner.time.strftime", return_value="20260731-205300"),
        patch.object(_LocalRun, "execute", return_value=None),
    ):
        runner = LocalTestRunner()
        first_id = runner.start(_config())
        second_id = runner.start(_config())

    for run in runner._runs.values():
        run.thread.join(timeout=1)

    assert first_id != second_id
    assert set(runner._runs) == {first_id, second_id}
    assert re.fullmatch(r"exp-20260731-205300-[0-9a-f]{8}", first_id)
    assert re.fullmatch(r"exp-20260731-205300-[0-9a-f]{8}", second_id)

    results_root = tmp_path / ".humanbound" / "results"
    assert (results_root / first_id).is_dir()
    assert (results_root / second_id).is_dir()
    assert {directory.name for directory in results_root.iterdir()} == {first_id, second_id}


def test_start_retries_when_uuid_result_directory_already_exists(tmp_path, monkeypatch):
    """Exclusive directory creation prevents an unlikely UUID collision."""
    monkeypatch.chdir(tmp_path)
    timestamp = "20260731-205300"
    results_root = tmp_path / ".humanbound" / "results"
    existing_id = f"exp-{timestamp}-00000001"
    (results_root / existing_id).mkdir(parents=True)

    with (
        patch("humanbound_cli.engine.local_runner.time.strftime", return_value=timestamp),
        patch(
            "humanbound_cli.engine.local_runner.uuid.uuid4",
            side_effect=[
                uuid.UUID("00000001-0000-0000-0000-000000000000"),
                uuid.UUID("00000002-0000-0000-0000-000000000000"),
            ],
        ),
        patch.object(_LocalRun, "execute", return_value=None),
    ):
        experiment_id = LocalTestRunner().start(_config())

    assert experiment_id == f"exp-{timestamp}-00000002"
    assert (results_root / existing_id).is_dir()
    assert (results_root / experiment_id).is_dir()
