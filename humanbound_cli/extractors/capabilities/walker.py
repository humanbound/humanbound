# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Repository walker: yields (path, language) pairs.

Skips: .git/, node_modules/, __pycache__/, dist/, build/, venv/, .venv/
Skips: files >1MB
Honors: .gitignore via pathspec (added in Task 5)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Optional

# Suffix → language label
_SUFFIX_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".mjs": "typescript",
    ".cjs": "typescript",
}

_EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", "venv", ".venv"}

_MAX_FILE_BYTES = 1_000_000  # 1 MB


def classify_language(path: Path) -> str | None:
    return _SUFFIX_LANG.get(path.suffix.lower())


def walk_repo(repo_path: Path) -> Iterator[tuple[Path, str]]:
    """Yield (path, language) for each supported source file under repo_path.

    Filters out excluded directories, files >1MB, and any path matching
    the repo's top-level .gitignore.
    """
    spec = _load_gitignore(repo_path)
    for entry in _iter_files(repo_path, repo_path, spec):
        lang = classify_language(entry)
        if lang is None:
            continue
        try:
            if entry.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield entry, lang


def _load_gitignore(repo_path: Path):
    """Parse .gitignore at the repo root (best-effort).

    Returns a pathspec.PathSpec, or None if no gitignore (or parse failed).
    """
    import pathspec

    gitignore = repo_path / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        return pathspec.PathSpec.from_lines(
            "gitwildmatch",
            gitignore.read_text(encoding="utf-8", errors="ignore").splitlines(),
        )
    except Exception:
        return None


def _iter_files(root: Path, repo_root: Path, spec) -> Iterator[Path]:
    for child in root.iterdir():
        rel = child.relative_to(repo_root).as_posix()
        if child.is_dir():
            if child.name in _EXCLUDED_DIRS:
                continue
            if spec is not None and spec.match_file(rel + "/"):
                continue
            yield from _iter_files(child, repo_root, spec)
        elif child.is_file():
            if spec is not None and spec.match_file(rel):
                continue
            yield child
