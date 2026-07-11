# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the LLM pinger factory and its provider aliases."""

import pytest

from humanbound_cli.engine.llm import PROVIDER_ALIASES, get_llm_pinger


def test_anthropic_is_alias_for_claude():
    assert PROVIDER_ALIASES["anthropic"] == "claude"


def test_unsupported_provider_raises_clear_error():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_llm_pinger({"name": "not-a-real-provider", "integration": {}})


def test_anthropic_alias_is_not_rejected_as_unsupported():
    # "anthropic" must resolve to the "claude" pinger. Building it may still fail
    # if the anthropic SDK isn't installed, but it must NOT be rejected as an
    # unsupported provider.
    try:
        get_llm_pinger({"name": "anthropic", "integration": {"api_key": "x"}})
    except ValueError as e:  # pragma: no cover - only if the alias regresses
        assert "Unsupported LLM provider" not in str(e)
    except Exception:
        # ImportError (missing SDK) or similar is fine: the alias resolved.
        pass
