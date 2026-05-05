# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Capability detection display block."""

from rich.console import Console

from humanbound_cli.extractors.capabilities import (
    CapabilityEvidence,
    CapabilityScanResult,
)
from humanbound_cli.extractors.capabilities.display import print_detected_capabilities


def test_display_shows_check_for_true_and_cross_for_false():
    result = CapabilityScanResult(
        capabilities={
            "tools": True,
            "memory": False,
            "inter_agent": False,
            "reasoning_model": False,
        },
        evidence=[CapabilityEvidence("tools", "@mcp.tool decorator", "agent.py", 1, "@mcp.tool")],
        files_scanned=1,
    )
    console = Console(record=True, width=120)
    print_detected_capabilities(result, console)
    out = console.export_text()
    assert "✓ tools" in out
    assert "✗ memory" in out
    assert "@mcp.tool decorator" in out
    assert "agent.py:1" in out


def test_display_summarises_extra_evidence_with_plus_n_more():
    evidence = [
        CapabilityEvidence("tools", f"signal {i}", "f.py", i, f"line {i}")
        for i in range(1, 6)  # 5 hits
    ]
    result = CapabilityScanResult(
        capabilities={
            "tools": True,
            "memory": False,
            "inter_agent": False,
            "reasoning_model": False,
        },
        evidence=evidence,
    )
    console = Console(record=True, width=120)
    print_detected_capabilities(result, console)
    out = console.export_text()
    assert "+2 more" in out  # show 3, summarize remainder


from humanbound_cli.extractors.capabilities.display import (
    prompt_empty_scan_choice,
)


def test_prompt_default_leaves_unset():
    """Default [1] returns None — keep scope.capabilities unset."""
    result = prompt_empty_scan_choice(
        console=Console(record=True),
        choice_callback=lambda: "1",
        bool_callback=lambda _key: False,
    )
    assert result is None


def test_prompt_explicit_set_walks_four_bool_prompts():
    answers = iter([True, False, True, False])
    result = prompt_empty_scan_choice(
        console=Console(record=True),
        choice_callback=lambda: "2",
        bool_callback=lambda _key: next(answers),
    )
    assert result == {
        "tools": True,
        "memory": False,
        "inter_agent": True,
        "reasoning_model": False,
    }


def test_prompt_cancel_raises_systemexit():
    import pytest

    with pytest.raises(SystemExit):
        prompt_empty_scan_choice(
            console=Console(record=True),
            choice_callback=lambda: "3",
            bool_callback=lambda _key: False,
        )
