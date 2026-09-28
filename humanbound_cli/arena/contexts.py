# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""In-memory conversation contexts, keyed by `(agent_id, contextId)`.

Each context holds its `thread_init` state and, for `history: gateway` only, the turn
history. A per-context lock lets the gateway run `thread_init` exactly once, even under
concurrency. The same `contextId` used against two agents gives two separate contexts.
The store is an LRU so a long-running gateway doesn't grow without bound.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

__all__ = ["Context", "ContextStore"]


@dataclass
class Context:
    agent_id: str
    state: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    started: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ContextStore:
    def __init__(self, max_items: int = 10_000) -> None:
        self.max_items = max_items
        self._items: OrderedDict[tuple[str, str], Context] = OrderedDict()

    def get_or_create(self, agent_id: str, context_id: str | None) -> tuple[str, Context]:
        cid = context_id or uuid.uuid4().hex
        key = (agent_id, cid)
        if key in self._items:
            self._items.move_to_end(key)
            return cid, self._items[key]
        ctx = Context(agent_id=agent_id)
        self._items[key] = ctx
        if len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return cid, ctx

    def drop_agent(self, agent_id: str) -> None:
        for key in [key for key in self._items if key[0] == agent_id]:
            del self._items[key]

    def __len__(self) -> int:
        return len(self._items)
