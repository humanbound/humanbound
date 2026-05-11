# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Top-level capability scanner."""

from __future__ import annotations

from pathlib import Path

from . import patterns as patterns_module
from .python_ast import is_real_code_at_line
from .types import CAPABILITY_KEYS, CapabilityEvidence, CapabilityScanResult
from .walker import walk_repo


def scan_capabilities(repo_path: Path) -> CapabilityScanResult:
    repo_path = Path(repo_path).resolve()
    if not repo_path.is_dir():
        raise ValueError(f"Repository path not found or not a directory: {repo_path}")

    capabilities = {key: False for key in CAPABILITY_KEYS}
    evidence: list[CapabilityEvidence] = []
    files_scanned = 0
    languages_scanned: dict[str, int] = {}
    skipped_files = 0

    for path, lang in walk_repo(repo_path):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            skipped_files += 1
            continue

        files_scanned += 1
        languages_scanned[lang] = languages_scanned.get(lang, 0) + 1

        for pattern in patterns_module.PATTERNS:
            if pattern.language != lang:
                continue
            for match in pattern.regex.finditer(source):
                # Count newlines before the match start, then add any leading newlines
                # within the matched text (e.g., from ^\s* capturing leading whitespace)
                line = source.count("\n", 0, match.start()) + 1 + match.group().count("\n")
                if lang == "python":
                    if not is_real_code_at_line(source, line):
                        continue
                    if pattern.ast_verify is not None and not pattern.ast_verify(source):
                        continue
                snippet = source.splitlines()[line - 1].strip()[:120]
                rel = path.relative_to(repo_path).as_posix()
                evidence.append(
                    CapabilityEvidence(
                        capability=pattern.capability,
                        signal=pattern.signal,
                        file=rel,
                        line=line,
                        snippet=snippet,
                    )
                )
                capabilities[pattern.capability] = True

    return CapabilityScanResult(
        capabilities=capabilities,
        evidence=evidence,
        files_scanned=files_scanned,
        languages_scanned=languages_scanned,
        skipped_files=skipped_files,
    )
