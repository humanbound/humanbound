# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Walker: directory traversal + language classification."""

from pathlib import Path

import pytest

from humanbound_cli.extractors.capabilities.walker import classify_language, walk_repo

FIXTURES = Path(__file__).parent.parent / "fixtures" / "capabilities"


def test_classify_language_by_suffix():
    assert classify_language(Path("a.py")) == "python"
    assert classify_language(Path("a.ts")) == "typescript"
    assert classify_language(Path("a.tsx")) == "typescript"
    assert classify_language(Path("a.js")) == "typescript"  # we group js with ts
    assert classify_language(Path("a.mjs")) == "typescript"
    assert classify_language(Path("a.md")) is None
    assert classify_language(Path("a.txt")) is None


def test_walk_empty_dir_returns_no_files():
    files = list(walk_repo(FIXTURES / "empty"))
    assert files == []


def test_walk_mixed_repo_yields_only_supported_languages():
    files = list(walk_repo(FIXTURES / "mixed"))
    names = sorted(p.name for p, _lang in files)
    assert names == ["agent.py", "server.ts"]  # README.md excluded
    langs = {p.name: lang for p, lang in files}
    assert langs["agent.py"] == "python"
    assert langs["server.ts"] == "typescript"


def test_walk_respects_gitignore():
    files = list(walk_repo(FIXTURES / "gitignore_excludes"))
    names = sorted(p.name for p, _lang in files)
    assert names == ["included.py"]  # excluded.py and build/ both filtered out
