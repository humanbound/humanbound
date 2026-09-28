# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Default models for the local engine's LLM provider (`_resolve_provider`)."""

from unittest.mock import patch

import pytest

from humanbound_cli.engine import local_runner
from humanbound_cli.engine.local_runner import DEFAULT_MODELS, _resolve_provider

CONFIG_PATCH = "humanbound_cli.engine.local_runner._read_config_file"


def _resolve(env: dict, config: dict | None = None):
    with (
        patch.dict("os.environ", env, clear=True),
        patch(CONFIG_PATCH, return_value=config or {}),
    ):
        return _resolve_provider()


def test_default_models_table():
    assert DEFAULT_MODELS == {"openai": "gpt-4.1", "ollama": "llama3.1:8b"}
    assert local_runner.DEFAULT_MODELS is DEFAULT_MODELS


@pytest.mark.parametrize("name", ["openai", "OpenAI", " OPENAI "])
def test_openai_defaults_to_gpt_4_1(name):
    provider = _resolve({"HB_PROVIDER": name, "HB_API_KEY": "sk-test"})
    assert provider["integration"]["model"] == "gpt-4.1"
    assert provider["integration"]["api_key"] == "sk-test"


def test_ollama_defaults_to_llama():
    provider = _resolve({"HB_PROVIDER": "ollama"})
    assert provider["integration"]["model"] == "llama3.1:8b"


def test_env_model_wins():
    provider = _resolve({"HB_PROVIDER": "openai", "HB_API_KEY": "k", "HB_MODEL": "gpt-4o-mini"})
    assert provider["integration"]["model"] == "gpt-4o-mini"


def test_config_model_wins():
    provider = _resolve({}, {"provider": "openai", "api_key": "k", "model": "gpt-5"})
    assert provider["integration"]["model"] == "gpt-5"


def test_config_provider_gets_default_model():
    provider = _resolve({}, {"provider": "ollama"})
    assert provider["integration"]["model"] == "llama3.1:8b"


@pytest.mark.parametrize(
    "name,canonical",
    [
        ("claude", "claude"),
        ("anthropic", "claude"),
        ("gemini", "gemini"),
        ("grok", "grok"),
        ("azureopenai", "azureopenai"),
    ],
)
def test_providers_without_default_require_a_model(name, canonical):
    with pytest.raises(ValueError) as exc:
        _resolve({"HB_PROVIDER": name, "HB_API_KEY": "k"})
    msg = str(exc.value)
    assert f"No model configured for the {canonical} provider." in msg
    assert "export HB_MODEL=<model id" in msg
    assert "hb config set model <model id>" in msg
    if canonical == "azureopenai":
        assert "e.g. your deployment name" in msg
        assert "i.e." not in msg
    else:
        assert "deployment name" not in msg


def test_no_provider_error_unchanged():
    with pytest.raises(ValueError, match="No LLM provider configured"):
        _resolve({})


@pytest.mark.parametrize("env", [{"HB_PROVIDER": "foo"}, {"HB_PROVIDER": "foo", "HB_MODEL": "m"}])
def test_unsupported_provider_is_reported_before_model_defaults(env):
    with pytest.raises(ValueError) as exc:
        _resolve(env)
    msg = str(exc.value)
    assert "Unsupported LLM provider: foo" in msg
    assert "No model configured" not in msg


def test_unsupported_provider_from_config_file():
    with pytest.raises(ValueError, match="Unsupported LLM provider: nope"):
        _resolve({}, {"provider": "nope"})
