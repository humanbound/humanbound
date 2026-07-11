# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the Ollama pinger. It must talk to Ollama over httpx (a core dep),
so the air-gapped path works without the `[engine]` extra / the openai SDK."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from humanbound_cli.engine.llm.ollama import LLMPinger


def test_builds_openai_compatible_url():
    p = LLMPinger({"integration": {"model": "m", "endpoint": "http://host:1234/"}})
    assert p._url == "http://host:1234/v1/chat/completions"


def test_ping_parses_content_and_sends_expected_body():
    p = LLMPinger({"integration": {"model": "llama3.1:8b", "endpoint": "http://host:1234"}})
    fake = MagicMock(status_code=200)
    fake.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    fake.raise_for_status.return_value = None
    with patch("humanbound_cli.engine.llm.ollama.httpx.post", return_value=fake) as post:
        out = p.ping("system prompt", "user prompt", max_tokens=128, temperature=0)
    assert out == "hello"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "llama3.1:8b"
    assert body["messages"][0] == {"role": "system", "content": "system prompt"}
    assert body["messages"][1] == {"role": "user", "content": "user prompt"}


def test_ping_none_content_returns_placeholder():
    p = LLMPinger({"integration": {"model": "m", "endpoint": "http://host:1"}})
    fake = MagicMock(status_code=200)
    fake.json.return_value = {"choices": [{"message": {"content": None}}]}
    fake.raise_for_status.return_value = None
    with patch("humanbound_cli.engine.llm.ollama.httpx.post", return_value=fake):
        assert p.ping("s", "u") == "[No content in LLM response]"


def test_ping_connection_error_is_actionable():
    p = LLMPinger({"integration": {"model": "m", "endpoint": "http://host:1"}})
    with patch(
        "humanbound_cli.engine.llm.ollama.httpx.post",
        side_effect=httpx.ConnectError("refused"),
    ):
        with pytest.raises(Exception, match="Is ollama running"):
            p.ping("s", "u")
