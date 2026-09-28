# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Retry behaviour of the requests-based OpenAI / Azure OpenAI LLM pingers."""

import importlib
from unittest.mock import MagicMock, patch

import pytest
import requests


def _azure_importable() -> bool:
    try:
        importlib.import_module("humanbound_cli.engine.llm.azureopenai")
    except ImportError:
        return False
    return True


PROVIDERS = [
    pytest.param(
        "humanbound_cli.engine.llm.openai",
        {"api_key": "sk-test", "model": "gpt-4.1"},
        id="openai",
    ),
    pytest.param(
        "humanbound_cli.engine.llm.azureopenai",
        {
            "api_key": "az-test",
            "model": "my-deployment",
            "endpoint": "https://x.openai.azure.com/openai/deployments/d/chat/completions"
            "?api-version=2025-01-01-preview",
        },
        id="azureopenai",
        marks=pytest.mark.skipif(not _azure_importable(), reason="azure module not importable"),
    ),
]


def _resp(status: int, content: str = "hello"):
    r = MagicMock()
    r.status_code = status
    r.text = f"status {status}"
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def _ping(module_name, integration, responses):
    module = importlib.import_module(module_name)
    pinger = module.LLMPinger({"name": "x", "integration": dict(integration)})
    with (
        patch("requests.post", side_effect=responses) as post,
        patch.object(module.time, "sleep") as sleep,
    ):
        try:
            return pinger.ping("sys", "user"), post, sleep, None
        except Exception as e:  # noqa: BLE001 - the tests inspect it
            return None, post, sleep, e


@pytest.mark.parametrize("module_name,integration", PROVIDERS)
def test_503_then_200_succeeds(module_name, integration):
    out, post, sleep, err = _ping(module_name, integration, [_resp(503), _resp(503), _resp(200)])
    assert err is None
    assert out == "hello"
    assert post.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("module_name,integration", PROVIDERS)
def test_persistent_503_fails_after_all_attempts(module_name, integration):
    module = importlib.import_module(module_name)
    attempts = module.MAX_RETRY_COUNTER + 1
    out, post, _, err = _ping(module_name, integration, [_resp(503)] * attempts)
    assert out is None
    assert post.call_count == attempts
    assert str(err) == "502/Error while pinging the LLM - 503/status 503"


@pytest.mark.parametrize("module_name,integration", PROVIDERS)
def test_network_error_retries_then_succeeds(module_name, integration):
    out, post, sleep, err = _ping(
        module_name,
        integration,
        [requests.exceptions.Timeout("read timed out"), _resp(200)],
    )
    assert err is None
    assert out == "hello"
    assert post.call_count == 2
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize("module_name,integration", PROVIDERS)
def test_persistent_network_error_fails(module_name, integration):
    module = importlib.import_module(module_name)
    attempts = module.MAX_RETRY_COUNTER + 1
    out, post, _, err = _ping(
        module_name,
        integration,
        [requests.exceptions.ConnectionError("refused")] * attempts,
    )
    assert out is None
    assert post.call_count == attempts
    assert str(err) == "502/Error while pinging the LLM - request failed: refused"


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize("module_name,integration", PROVIDERS)
def test_4xx_not_retried(module_name, integration, status):
    out, post, sleep, err = _ping(module_name, integration, [_resp(status), _resp(200)])
    assert out is None
    assert str(status) in str(err)
    assert post.call_count == 1
    sleep.assert_not_called()
