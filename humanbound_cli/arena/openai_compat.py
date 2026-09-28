# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OpenAI-compatible chat-completions façade for arena agents.

Each request is a fresh conversation: there is no server-side session tied to a
`chat/completions` call. System messages are ignored, and there is no streaming.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

__all__ = ["parse_chat_request", "chat_response"]


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return ""


def parse_chat_request(body: Any) -> tuple[str, str, list[dict]]:
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")

    model = body.get("model")
    if not isinstance(model, str) or not model.startswith("arena/"):
        raise ValueError("model must be 'arena/<id>'")
    agent_id = model[len("arena/") :]

    if body.get("stream") is True:
        raise ValueError("stream is not supported")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")

    last_user_index = None
    for i, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            last_user_index = i

    if last_user_index is None:
        raise ValueError("messages must contain at least one user message")

    prompt = _message_text(messages[last_user_index]).strip()
    if not prompt:
        raise ValueError("the last user message must have non-empty text")

    history = [
        m
        for m in messages[:last_user_index]
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]

    return agent_id, prompt, history


def chat_response(agent_id: str, text: str, metadata: dict) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"arena/{agent_id}",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "humanbound": metadata,
    }
