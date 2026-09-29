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


class TestOpenAICustomEndpoint:
    """The openai provider honours ``integration["endpoint"]`` as an
    OpenAI-compatible base URL (OpenRouter, LiteLLM, vLLM, ...) (#70)."""

    @pytest.mark.parametrize(
        "endpoint,expected",
        [
            (None, "https://api.openai.com/v1/chat/completions"),
            ("", "https://api.openai.com/v1/chat/completions"),
            ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
            ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1/chat/completions"),
            (
                "https://openrouter.ai/api/v1/chat/completions",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            ("http://localhost:4000", "http://localhost:4000/chat/completions"),
        ],
    )
    def test_chat_url(self, endpoint, expected):
        from humanbound_cli.engine.llm.openai import _chat_url

        assert _chat_url(endpoint) == expected

    @staticmethod
    def _ping(integration, payload=None):
        from humanbound_cli.engine.llm.openai import LLMPinger

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload or {"choices": [{"message": {"content": "hi"}}]}
        with patch("humanbound_cli.engine.llm.openai.requests.post") as post:
            post.return_value = resp
            out = LLMPinger({"integration": integration}).ping("sys", "usr")
        return post, out

    def test_custom_endpoint_receives_request_and_key(self):
        post, out = self._ping(
            {
                "api_key": "sk-or-k",
                "model": "anthropic/claude-haiku-4.5",
                "endpoint": "https://openrouter.ai/api/v1",
            }
        )
        assert out == "hi"
        assert post.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-or-k"
        assert post.call_args.kwargs["json"]["model"] == "anthropic/claude-haiku-4.5"
        assert post.call_args.kwargs.get("allow_redirects") is False

    def test_no_endpoint_still_uses_openai(self):
        post, _ = self._ping({"api_key": "k", "model": "gpt-4o"})
        assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"

    def test_error_body_on_200_is_surfaced(self):
        with pytest.raises(Exception, match="No endpoints found"):
            self._ping(
                {"api_key": "k", "model": "x/y", "endpoint": "https://openrouter.ai/api/v1"},
                payload={"error": {"message": "No endpoints found for x/y", "code": 404}},
            )

    def test_resolve_provider_carries_hb_endpoint(self, monkeypatch):
        from humanbound_cli.engine.local_runner import _resolve_provider

        monkeypatch.setenv("HB_PROVIDER", "openai")
        monkeypatch.setenv("HB_API_KEY", "k")
        monkeypatch.setenv("HB_MODEL", "m")
        monkeypatch.setenv("HB_ENDPOINT", "https://openrouter.ai/api/v1")
        provider = _resolve_provider()
        assert provider["integration"]["endpoint"] == "https://openrouter.ai/api/v1"


class TestConfigSetProviderWarnsOnStaleEndpoint:
    """An endpoint left over from another provider (e.g. ollama) is now used by
    openai, so switching provider must say so."""

    @staticmethod
    def _set_provider(existing, value):
        from click.testing import CliRunner

        from humanbound_cli.commands import config_cmd

        with (
            patch.object(config_cmd, "_read_config", return_value=dict(existing)),
            patch.object(config_cmd, "_write_config"),
        ):
            return CliRunner().invoke(config_cmd.config_group, ["set", "provider", value])

    def test_warns_when_endpoint_set(self):
        result = self._set_provider({"endpoint": "http://localhost:11434"}, "openai")
        assert result.exit_code == 0
        assert "Endpoint is still set" in result.output

    def test_silent_without_endpoint(self):
        result = self._set_provider({"api_key": "k"}, "openai")
        assert "Endpoint is still set" not in result.output

    def test_silent_for_providers_that_ignore_endpoint(self):
        result = self._set_provider({"endpoint": "http://localhost:11434"}, "claude")
        assert "Endpoint is still set" not in result.output
