# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for RepoScanner."""

import logging
from pathlib import Path

from humanbound_cli.extractors.repo import RepoScanner


def test_repo_scanner_logs_malformed_tools_json(tmp_path: Path, caplog):
    """Test that malformed tools.json logs a warning with the file name."""
    tool_file = tmp_path / "tools.json"
    tool_file.write_text("{malformed: json", encoding="utf-8")

    scanner = RepoScanner(tmp_path)

    with caplog.at_level(logging.WARNING):
        scanner.scan()

    assert "Failed to extract tools from tools.json" in caplog.text


def test_repo_scanner_logs_malformed_tools_yaml(tmp_path: Path, caplog):
    """Test that malformed tools.yaml logs a warning with the file name."""
    tool_file = tmp_path / "tools.yaml"
    tool_file.write_text("malformed: \n  - yaml: [", encoding="utf-8")

    scanner = RepoScanner(tmp_path)

    with caplog.at_level(logging.WARNING):
        scanner.scan()

    assert "Failed to extract tools from tools.yaml" in caplog.text
