# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Regression tests for collision-safe local experiment IDs."""

import re
from unittest.mock import patch

from humanbound_cli.engine.local_runner import LocalTestRunner, _LocalRun
from humanbound_cli.engine.runner import TestConfig as _TestConfig


def _config():
    return _TestConfig(endpoint={"chat_completion": {"endpoint": "http://example.test"}})


def test_starts_in_same_second_get_distinct_ids(tmp_path, monkeypatch):
    """Two start() calls in the same second must not share an experiment ID."""
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
