# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the ollama pinger's error reporting."""

import socket
from unittest.mock import patch

import pytest

openai = pytest.importorskip("openai")
httpx = pytest.importorskip("httpx")

from humanbound_cli.engine.llm.ollama import LLM_PING_TIMEOUT, LLMPinger  # noqa: E402

ENDPOINT = "http://127.0.0.1:11434"
REQUEST = httpx.Request("POST", f"{ENDPOINT}/v1/chat/completions")


def _pinger():
    return LLMPinger({"integration": {"model": "m", "endpoint": ENDPOINT}})


def _connection_error(cause):
    err = openai.APIConnectionError(request=REQUEST)
    err.__cause__ = cause
    return err


def _status_error(cls, code, message):
    response = httpx.Response(code, request=REQUEST)
    return cls(f"Error code: {code} - {message}", response=response, body=None)


def _ping_raising(err):
    p = _pinger()
    with patch.object(p._client.chat.completions, "create", side_effect=err) as create:
        with patch("humanbound_cli.engine.llm.ollama.time.sleep"):
            with pytest.raises(Exception) as exc:
                p.ping("s", "u")
    return str(exc.value), create.call_count


def test_refused_connection_says_ollama_is_not_running():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{s.getsockname()[1]}"
    p = LLMPinger({"integration": {"model": "m", "endpoint": endpoint}})
    p._client = p._client.with_options(max_retries=0)
    with pytest.raises(Exception) as exc:
        p.ping("s", "u")
    assert str(exc.value) == (
        f"Cannot connect to ollama at {endpoint}. Is ollama running? Start it with: ollama serve"
    )


def test_status_error_mentioning_connection_reports_the_server_error():
    err = _status_error(openai.InternalServerError, 500, "GPU pool busy: connection overloaded")
    msg, calls = _ping_raising(err)
    assert "Is ollama running" not in msg
    assert "500" in msg and "GPU pool busy" in msg
    assert calls == 1


def test_dropped_connection_is_not_reported_as_server_down():
    msg, _ = _ping_raising(
        _connection_error(
            httpx.RemoteProtocolError("Server disconnected without sending a response.")
        )
    )
    assert "Is ollama running" not in msg
    assert "Server disconnected" in msg


def test_timeout_reports_the_timeout():
    msg, _ = _ping_raising(openai.APITimeoutError(request=REQUEST))
    assert "Is ollama running" not in msg
    assert f"{LLM_PING_TIMEOUT}s" in msg


def test_rate_limit_is_retried_then_reported():
    msg, calls = _ping_raising(_status_error(openai.RateLimitError, 429, "slow down"))
    assert msg == "502/Rate limit error."
    assert calls == 4


def test_error_text_containing_rate_is_not_retried():
    msg, calls = _ping_raising(_status_error(openai.InternalServerError, 500, "failed to generate"))
    assert calls == 1
    assert "failed to generate" in msg
