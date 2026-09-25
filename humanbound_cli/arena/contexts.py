# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Per-conversation adapter state, keyed by A2A contextId. In memory only."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field


@dataclass
class Context:
    agent_id: str
    state: dict = field(default_factory=dict)  # thread_init output
    history: list[dict] = field(default_factory=list)  # OpenAI-style turns
    started: bool = False
    # Serialises turns on one conversation (thread_init runs once, history stays ordered).
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class ContextStore:
    def __init__(self, max_items: int = 10_000):
        self._items: dict[tuple[str, str], Context] = {}
        self._max = max_items

    def get_or_create(self, agent_id: str, context_id: str | None) -> tuple[str, Context]:
        cid = context_id or uuid.uuid4().hex
        key = (agent_id, cid)
        ctx = self._items.get(key)
        if ctx is None:
            ctx = Context(agent_id)
            self._items[key] = ctx
            while len(self._items) > self._max:
                del self._items[next(iter(self._items))]
        else:
            # Touch on hit: move to the end so it's the most-recently-used entry.
            del self._items[key]
            self._items[key] = ctx
        return cid, ctx

    def drop_agent(self, agent_id: str) -> None:
        for key in [k for k in self._items if k[0] == agent_id]:
            del self._items[key]

    def __len__(self) -> int:
        return len(self._items)
