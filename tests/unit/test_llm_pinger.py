# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the LLM pinger factory: provider name resolution and aliases."""

from unittest.mock import MagicMock, patch

import pytest

from humanbound_cli.engine.llm import (
    PROVIDER_ALIASES,
    SUPPORTED_PROVIDERS,
    get_llm_pinger,
    resolve_provider_name,
)


class TestResolveProviderName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("anthropic", "claude"),  # the alias (#53)
            ("Anthropic", "claude"),  # case-insensitive
            ("ANTHROPIC", "claude"),
            (" anthropic ", "claude"),  # env vars carry stray whitespace
            ("claude", "claude"),  # canonical names pass through
            ("OpenAI", "openai"),
            ("ollama", "ollama"),
            ("bogus", "bogus"),  # unknown passes through for the error path
            ("", ""),
            (None, ""),
        ],
    )
    def test_resolution(self, raw, expected):
        assert resolve_provider_name(raw) == expected

    def test_every_alias_targets_a_supported_provider(self):
        for alias, canonical in PROVIDER_ALIASES.items():
            assert canonical in SUPPORTED_PROVIDERS
            assert alias not in SUPPORTED_PROVIDERS  # alias must not shadow a real name


class TestGetLlmPinger:
    def test_unsupported_provider_raises_with_alias_hint(self):
        with pytest.raises(ValueError, match=r"Unsupported LLM provider: not-real") as exc:
            get_llm_pinger({"name": "not-real", "integration": {}})
        assert "anthropic -> claude" in str(exc.value)

    def test_error_reports_the_original_input(self):
        # The message must show what the user typed, not a normalized form.
        with pytest.raises(ValueError, match=r"Unsupported LLM provider: Not-Real"):
            get_llm_pinger({"name": "Not-Real", "integration": {}})

    def test_anthropic_alias_is_not_rejected_as_unsupported(self):
        # Building the pinger may fail if the anthropic SDK isn't installed,
        # but the alias must never be rejected as an unsupported provider.
        try:
            get_llm_pinger({"name": "anthropic", "integration": {"api_key": "x"}})
        except ValueError as e:
            pytest.fail(f"alias was rejected: {e}")
        except Exception:
            pass  # missing SDK etc. — the alias resolved, which is what we test


class TestAliasReachesClaudePinger:
    def test_anthropic_returns_the_claude_pinger(self):
        pytest.importorskip("anthropic")  # SDK ships in the [engine] extra
        pinger = get_llm_pinger({"name": "anthropic", "integration": {"api_key": "x"}})
        assert type(pinger).__module__ == "humanbound_cli.engine.llm.claude"


class TestPingersDisableRedirects:
    """Credential-bearing ``requests.post`` calls must not follow redirects.

    ``requests`` strips only ``Authorization`` on a cross-host redirect, not custom
    headers such as ``Api-Key`` / ``x-hb-key-internal``, so a redirecting endpoint
    could re-send the provider key to another host. Mirrors the bot HTTP/SSE
    reject-redirect behavior (see ``test_engine_bot.py``).
    """

    @staticmethod
    def _resp(payload):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = payload
        return r

    def test_azure_pinger_disables_redirects(self):
        pytest.importorskip("openai")  # azureopenai imports the openai SDK ([engine] extra)
        from humanbound_cli.engine.llm.azureopenai import LLMPinger

        provider = {
            "integration": {
                "api_key": "k",
                "model": "gpt-4o",
                "endpoint": "https://user.example/chat",
            }
        }
        completion = {"choices": [{"message": {"content": "hi"}}], "usage": {}}
        with patch("humanbound_cli.engine.llm.azureopenai.requests.post") as post:
            post.return_value = self._resp(completion)
            LLMPinger(provider).ping("sys", "usr")
        assert post.call_args.kwargs.get("allow_redirects") is False

    def test_embeddings_extractor_disables_redirects(self):
        pytest.importorskip("openai")
        from humanbound_cli.engine.llm.azureopenai import EmbeddingsExtractor

        provider = {"integration": {"api_key": "k", "endpoint": "https://user.example/embed"}}
        with patch("humanbound_cli.engine.llm.azureopenai.requests.post") as post:
            post.return_value = self._resp({"data": [{"embedding": [0.1, 0.2]}]})
            EmbeddingsExtractor(provider).encode(["a"])
        assert post.call_args.kwargs.get("allow_redirects") is False

    def test_openai_pinger_disables_redirects(self):
        pytest.importorskip("openai")
        from humanbound_cli.engine.llm.openai import LLMPinger

        provider = {"integration": {"api_key": "k", "model": "gpt-4o"}}
        completion = {"choices": [{"message": {"content": "hi"}}], "usage": {}}
        with patch("humanbound_cli.engine.llm.openai.requests.post") as post:
            post.return_value = self._resp(completion)
            LLMPinger(provider).ping("sys", "usr")
        assert post.call_args.kwargs.get("allow_redirects") is False
