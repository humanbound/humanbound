# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the OpenAI-compatible chat-completions façade helpers."""

from __future__ import annotations

import pytest

from humanbound_cli.arena.openai_compat import chat_response, parse_chat_request


def test_parse_chat_request_happy_path_with_history():
    body = {
        "model": "arena/echo",
        "messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "how are you"},
        ],
    }
    agent_id, prompt, history = parse_chat_request(body)
    assert agent_id == "echo"
    assert prompt == "how are you"
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_parse_chat_request_content_parts_list():
    body = {
        "model": "arena/echo",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
            },
        ],
    }
    _, prompt, _ = parse_chat_request(body)
    assert prompt == "hello world"


def test_parse_chat_request_no_history():
    body = {"model": "arena/echo", "messages": [{"role": "user", "content": "hi"}]}
    agent_id, prompt, history = parse_chat_request(body)
    assert agent_id == "echo"
    assert prompt == "hi"
    assert history == []


@pytest.mark.parametrize(
    "body",
    [
        "not a dict",
        {"model": "echo", "messages": [{"role": "user", "content": "hi"}]},
        {"model": "arena/echo", "messages": []},
        {"model": "arena/echo", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        {"model": "arena/echo", "messages": "not a list"},
        {"model": "arena/echo", "messages": [{"role": "user", "content": ""}]},
        {"model": "arena/echo", "messages": [{"role": "system", "content": "only system"}]},
        {"model": "arena/echo", "messages": [{"role": "user", "content": "   "}]},
    ],
)
def test_parse_chat_request_rejections(body):
    with pytest.raises(ValueError):
        parse_chat_request(body)


def test_parse_chat_request_stream_non_true_is_ignored():
    body = {
        "model": "arena/echo",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": "false",
    }
    agent_id, prompt, history = parse_chat_request(body)
    assert agent_id == "echo"
    assert prompt == "hi"


def test_chat_response_shape():
    resp = chat_response("echo", "hello back", {"latency_ms": 12})
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "arena/echo"
    assert resp["id"].startswith("chatcmpl-")
    assert resp["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello back"},
            "finish_reason": "stop",
        }
    ]
    assert resp["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert resp["humanbound"] == {"latency_ms": 12}
    assert isinstance(resp["created"], int)
