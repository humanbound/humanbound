# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Scanner orchestration: walker + patterns + AST verifier."""

import re
from pathlib import Path

import pytest

from humanbound_cli.extractors.capabilities import patterns as patterns_module
from humanbound_cli.extractors.capabilities import scan_capabilities
from humanbound_cli.extractors.capabilities.patterns import Pattern
from humanbound_cli.extractors.capabilities.python_ast import has_use_site

FIXTURES = Path(__file__).parent.parent / "fixtures" / "capabilities"


@pytest.fixture
def single_tools_pattern(monkeypatch):
    """Replace the registry with one pattern: detect @tool from langchain."""
    pat = Pattern(
        capability="tools",
        language="python",
        regex=re.compile(r"^\s*@tool\b", re.MULTILINE),
        signal="@tool decorator",
        ast_verify=lambda src: has_use_site(src, "tool"),
    )
    monkeypatch.setattr(patterns_module, "PATTERNS", [pat])


def test_scan_empty_repo_returns_all_false(single_tools_pattern):
    result = scan_capabilities(FIXTURES / "empty")
    assert result.capabilities == {
        "tools": False,
        "memory": False,
        "inter_agent": False,
        "reasoning_model": False,
    }
    assert result.evidence == []
    assert result.files_scanned == 0


def test_scan_tools_only_repo_detects_tools(single_tools_pattern):
    result = scan_capabilities(FIXTURES / "tools_only_py")
    assert result.capabilities["tools"] is True
    assert result.capabilities["memory"] is False
    assert any(ev.signal == "@tool decorator" for ev in result.evidence)
    assert result.files_scanned == 1
    assert result.languages_scanned == {"python": 1}


def test_lone_import_does_not_trigger_capability(single_tools_pattern):
    result = scan_capabilities(FIXTURES / "lone_imports_py")
    # @tool is imported but never used → AST evidence-of-use suppresses the hit
    assert result.capabilities["tools"] is False
    assert result.evidence == []


def test_broken_python_falls_back_pattern_only(single_tools_pattern):
    # Pattern itself doesn't fire (no @tool in this file), but the scan
    # must not crash on syntax errors.
    result = scan_capabilities(FIXTURES / "broken_python")
    assert result.files_scanned == 1  # scanned despite syntax error


def test_huge_file_is_skipped(single_tools_pattern, tmp_path):
    big = tmp_path / "big.py"
    big.write_text("# pad\n" * 200_000)  # ~1.2 MB
    result = scan_capabilities(tmp_path)
    assert result.files_scanned == 0  # >1MB skipped


def test_all_signals_repo_detects_all_four_capabilities():
    # Note: NO monkeypatch — uses the real registry from Task 10.
    result = scan_capabilities(FIXTURES / "all_signals_py")
    assert result.capabilities == {
        "tools": True,
        "memory": True,
        "inter_agent": True,
        "reasoning_model": True,
    }
