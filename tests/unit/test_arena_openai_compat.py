# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import pytest

from humanbound_cli.arena.openai_compat import chat_response, parse_chat_request


def test_parses_model_last_user_message_and_prior_history():
    agent_id, prompt, history = parse_chat_request(
        {
            "model": "arena/echo",
            "messages": [
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "echo: one"},
                {"role": "user", "content": [{"type": "text", "text": "two"}]},
            ],
        }
    )
    assert agent_id == "echo"
    assert prompt == "two"
    assert history == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "echo: one"},
    ]


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]}, "arena/<agent-id>"),
        ({"model": "arena/echo", "messages": []}, "user message"),
        (
            {"model": "arena/echo", "stream": True, "messages": [{"role": "user", "content": "x"}]},
            "stream",
        ),
        ("nope", "JSON object"),
        ({"model": "arena/echo", "messages": "nope"}, "messages must be a list"),
        (
            {"model": "arena/echo", "messages": [{"role": "user", "content": ""}]},
            "non-empty",
        ),
        (
            {"model": "arena/echo", "messages": [{"role": "user", "content": []}]},
            "non-empty",
        ),
    ],
)
def test_rejects_bad_requests(body, fragment):
    with pytest.raises(ValueError, match=fragment):
        parse_chat_request(body)


@pytest.mark.parametrize("stream_value", ["true", 1, "yes", False, None])
def test_stream_only_rejected_when_exactly_true(stream_value):
    agent_id, prompt, _ = parse_chat_request(
        {
            "model": "arena/echo",
            "stream": stream_value,
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert agent_id == "echo" and prompt == "hi"


def test_chat_response_shape():
    body = chat_response("echo", "hi", {"latency_ms": 3})
    assert body["object"] == "chat.completion"
    assert body["model"] == "arena/echo"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "hi"}
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["humanbound"] == {"latency_ms": 3}
