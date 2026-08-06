# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Pattern registry shape tests."""

import re

from humanbound_cli.extractors.capabilities.patterns import (
    PATTERNS,
    Pattern,
)
from humanbound_cli.extractors.capabilities.types import CAPABILITY_KEYS


def test_pattern_has_required_fields():
    p = Pattern(
        capability="tools",
        language="python",
        regex=re.compile(r"@tool\b"),
        signal="@tool decorator",
        ast_verify=None,
    )
    assert p.capability == "tools"
    assert p.language == "python"
    assert p.regex.pattern == r"@tool\b"


def test_registry_is_iterable_and_contains_patterns_for_each_capability():
    # After Task 10 the registry is fully populated; for now we only assert
    # the shape and that the registry is iterable.
    assert isinstance(PATTERNS, list)
    for p in PATTERNS:
        assert p.capability in CAPABILITY_KEYS
        assert p.language in {"python", "typescript"}
        assert isinstance(p.regex, re.Pattern)
        assert isinstance(p.signal, str) and p.signal
