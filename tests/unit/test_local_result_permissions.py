# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Local test results must not be world-readable.

Local runs write meta.json / logs.jsonl under .humanbound/results/. Those files
contain attack prompts and the agent's raw replies — they must be created with
the same owner-only (0600 / 0700) contract as credentials.json.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from humanbound_cli.engine.local_runner import _ensure_private_dir, _LocalRun
from humanbound_cli.engine.runner import TestConfig


@pytest.fixture
def umask_022():
    """Pin a permissive umask so permission tests fail against the unfixed path."""
    old = os.umask(0o022)
    yield
    os.umask(old)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_ensure_private_dir_is_owner_only(tmp_path, monkeypatch, umask_022):
    monkeypatch.chdir(tmp_path)
    target = Path(".humanbound/results/exp-demo")
    _ensure_private_dir(target)
    assert target.is_dir()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(".humanbound/results").stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(".humanbound").stat().st_mode) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_save_results_writes_owner_only_artifacts(tmp_path, monkeypatch, umask_022):
    monkeypatch.chdir(tmp_path)
    config = TestConfig(
        name="perm-test",
        endpoint={"url": "https://example.test/chat"},
        test_category="owasp/llm",
        testing_level="unit",
    )
    run = _LocalRun("exp-perm-test", config)
    run.status = "Finished"
    run.results = {
        "stats": {},
        "insights": [],
        "posture": None,
        "exec_t": {},
    }
    run.logs = [
        {
            "thread_id": "t1",
            "conversation": [{"u": "secret prompt", "a": "model reply"}],
            "result": "pass",
            "gen_category": "test",
        }
    ]
    run._save_results()

    results_dir = Path(".humanbound/results/exp-perm-test")
    meta = results_dir / "meta.json"
    logs = results_dir / "logs.jsonl"
    assert meta.exists()
    assert logs.exists()
    assert json.loads(meta.read_text())["id"] == "exp-perm-test"
    assert "secret prompt" in logs.read_text()
    assert stat.S_IMODE(meta.stat().st_mode) == 0o600
    assert stat.S_IMODE(logs.stat().st_mode) == 0o600
    assert stat.S_IMODE(results_dir.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_naive_write_text_would_be_world_readable(tmp_path, monkeypatch, umask_022):
    """Document the pre-fix failure mode: umask 022 makes write_text world-readable."""
    monkeypatch.chdir(tmp_path)
    leaky = Path("leaky.json")
    leaky.write_text("{}")
    mode = stat.S_IMODE(leaky.stat().st_mode)
    # On a typical umask 022 this is 0644 — group/other readable.
    assert mode & stat.S_IROTH, f"expected other-readable under umask 022, got {oct(mode)}"
