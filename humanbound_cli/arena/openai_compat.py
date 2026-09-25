# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OpenAI Chat Completions façade, so eval tools (promptfoo, garak, PyRIT) can target
arena agents. Each request is a fresh conversation; multi-turn agents should use A2A.

System messages in `messages` are ignored: the arena agent's own system prompt comes
from its arena.yaml, not from the caller."""

from __future__ import annotations

import time
import uuid
from typing import Any


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def parse_chat_request(body: Any) -> tuple[str, str, list[dict]]:
    """Return (agent_id, prompt, prior user/assistant history)."""
    if not isinstance(body, dict):
        raise ValueError("the request body must be a JSON object")
    model = body.get("model") or ""
    if not isinstance(model, str) or not model.startswith("arena/") or len(model) <= len("arena/"):
        raise ValueError("model must be 'arena/<agent-id>'")
    if body.get("stream") is True:
        raise ValueError("stream=true is not supported yet")
    messages_raw = body.get("messages")
    if messages_raw is None:
        messages_raw = []
    if not isinstance(messages_raw, list):
        raise ValueError("messages must be a list")
    messages = [m for m in messages_raw if isinstance(m, dict)]
    user_indexes = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indexes:
        raise ValueError("messages must contain at least one user message")
    last = user_indexes[-1]
    history = [
        {"role": m["role"], "content": _text(m.get("content"))}
        for m in messages[:last]
        if m.get("role") in ("user", "assistant")
    ]
    prompt = _text(messages[last].get("content"))
    if not prompt:
        raise ValueError("the last user message must have non-empty text")
    return model[len("arena/") :], prompt, history


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
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "humanbound": metadata,
    }
