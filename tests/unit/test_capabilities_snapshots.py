# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Narrow snapshot coverage: just the two new UX surfaces."""

from pathlib import Path

from rich.console import Console

from humanbound_cli.extractors.capabilities import (
    CapabilityEvidence,
    CapabilityScanResult,
)
from humanbound_cli.extractors.capabilities.display import print_detected_capabilities

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _normalize(s: str) -> str:
    # Strip trailing whitespace per line; rich pads to console width.
    return "\n".join(line.rstrip() for line in s.splitlines()).strip() + "\n"


def test_snapshot_detected_capabilities_block():
    result = CapabilityScanResult(
        capabilities={
            "tools": True,
            "memory": False,
            "inter_agent": True,
            "reasoning_model": False,
        },
        evidence=[
            CapabilityEvidence("tools", "@mcp.tool decorator", "agent/server.py", 42, "@mcp.tool"),
            CapabilityEvidence(
                "tools", "Tool(...) instantiation", "agent/runtime.py", 117, "Tool(...)"
            ),
            CapabilityEvidence(
                "inter_agent", "langgraph add_node call", "agent/graph.py", 23, ".add_node"
            ),
        ],
        files_scanned=4,
        languages_scanned={"python": 4},
    )
    console = Console(record=True, width=100, force_terminal=False)
    print_detected_capabilities(result, console)
    actual = _normalize(console.export_text())
    expected = _normalize((SNAPSHOTS / "capabilities_detected_block.txt").read_text())
    assert actual == expected, f"\nEXPECTED:\n{expected}\nACTUAL:\n{actual}"


def test_snapshot_archive_warning_text():
    """The exact archive-warning string used in confirm prompts."""
    from humanbound_cli.engine.capabilities_writer import _ARCHIVE_WARNING

    expected = (SNAPSHOTS / "capabilities_archive_warning.txt").read_text().strip()
    assert _ARCHIVE_WARNING.strip() == expected
