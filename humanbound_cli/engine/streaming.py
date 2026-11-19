# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Configurable stream replies and kept-open WebSocket connections.

`chat_completion.response` says, for WebSocket and SSE streams, where the reply text
is, which message ends the reply and which messages to skip. `chat_completion.websocket`
keeps one connection per conversation and answers messages such as keep-alive pings.
"""

import asyncio
import json
import threading
from dataclasses import dataclass

from .dot_path import get_path

# A kept-open connection with no turn for this long is closed. Generous, because the
# gap between two turns of one conversation includes the attacker and judge LLM calls.
IDLE_CLOSE_SECONDS = 300

# Between turns, how long to wait for more queued messages before the next send.
DRAIN_WAIT_SECONDS = 0.05


def _setting(bot_config, name):
    """`chat_completion.<name>`, or None. A malformed `chat_completion` is left for the
    transport to report when the request is made."""
    chat_completion = bot_config.get("chat_completion")
    return chat_completion.get(name) if isinstance(chat_completion, dict) else None


def _is_conditions(value):
    return isinstance(value, dict) and bool(value) and all(isinstance(k, str) and k for k in value)


def _matches(message, conditions):
    """The message has every {dot_path: value} of `conditions`."""
    return isinstance(message, dict) and all(
        get_path(message, path) == value for path, value in conditions.items()
    )


def _fill(template, message):
    """Copy of `template` with each "$dot.path" string replaced by that value of `message`."""
    if isinstance(template, dict):
        return {k: _fill(v, message) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, message) for v in template]
    if isinstance(template, str) and template.startswith("$") and len(template) > 1:
        return get_path(message, template[1:])
    return template


@dataclass(frozen=True)
class StreamRules:
    """Validated `chat_completion.response`."""

    text_path: str | None = None
    complete_when: dict | None = None
    ignore_when: dict | None = None

    @classmethod
    def from_config(cls, bot_config):
        rules = _setting(bot_config, "response")
        if rules is None:
            return cls()
        if not isinstance(rules, dict):
            raise ValueError("'chat_completion.response' must be an object.")
        text_path = rules.get("text_path")
        if text_path is not None and (not isinstance(text_path, str) or not text_path.strip()):
            raise ValueError("'chat_completion.response.text_path' must be a dot path string.")
        for name in ("complete_when", "ignore_when"):
            if rules.get(name) is not None and not _is_conditions(rules[name]):
                raise ValueError(
                    f"'chat_completion.response.{name}' must be a non-empty object of "
                    '{"dot.path": value}, e.g. {"type": "message.done"}.'
                )
        return cls(text_path, rules.get("complete_when"), rules.get("ignore_when"))

    def skips(self, message):
        return bool(self.ignore_when) and _matches(message, self.ignore_when)

    def completes(self, message):
        return bool(self.complete_when) and _matches(message, self.complete_when)


@dataclass(frozen=True)
class WebSocketOptions:
    """Validated `chat_completion.websocket`."""

    keep_open: bool = False
    auto_reply: tuple = ()

    @classmethod
    def from_config(cls, bot_config):
        opts = _setting(bot_config, "websocket")
        if opts is None:
            return cls()
        if not isinstance(opts, dict):
            raise ValueError("'chat_completion.websocket' must be an object.")
        keep_open = opts.get("keep_open", False)
        if not isinstance(keep_open, bool):
            raise ValueError("'chat_completion.websocket.keep_open' must be true or false.")
        auto_reply = opts.get("auto_reply") or []
        valid = isinstance(auto_reply, list) and all(
            isinstance(rule, dict)
            and _is_conditions(rule.get("when"))
            and isinstance(rule.get("send"), (dict, list, str))
            for rule in auto_reply
        )
        if not valid:
            raise ValueError(
                "'chat_completion.websocket.auto_reply' must be a list of "
                '{"when": {"dot.path": value}, "send": {...}}, e.g. '
                '{"when": {"type": "ping"}, "send": {"type": "pong", "id": "$ping.id"}}.'
            )
        return cls(keep_open, tuple(auto_reply))

    async def answer(self, socket, message):
        """Send the auto_reply for `message`, if one matches. True if one was sent."""
        for rule in self.auto_reply:
            if _matches(message, rule["when"]):
                reply = _fill(rule["send"], message)
                await socket.send(
                    reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
                )
                return True
        return False

    async def drain(self, socket):
        """Before the next turn on a kept-open connection: answer what arrived since the
        last reply (pings), drop the rest. False if the agent closed the connection."""
        from websockets.exceptions import ConnectionClosed

        if not _is_open(socket):
            return False
        while True:
            try:
                raw = await asyncio.wait_for(socket.recv(), DRAIN_WAIT_SECONDS)
            except (asyncio.TimeoutError, TimeoutError):
                return True
            except ConnectionClosed:
                return False
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            await self.answer(socket, message)


async def close_quietly(socket):
    try:
        await asyncio.wait_for(socket.close(), 5)
    except Exception:
        pass


def _is_open(socket):
    return getattr(getattr(socket, "state", None), "name", None) == "OPEN"


class KeptOpenConnections:
    """Idle kept-open connections, one per (event loop, conversation id).

    A Bot is shared by an orchestrator's threads, each running its own event loop, and
    a connection only works on the loop that opened it. While idle, each connection has
    a watcher task that closes it after IDLE_CLOSE_SECONDS, or when its event loop shuts
    down (asyncio.run() cancels pending tasks), so callers never have to close it.
    """

    def __init__(self):
        self._idle = {}  # (loop, conversation id) -> (socket, watcher task)
        self._lock = threading.Lock()

    def take(self, conversation_id):
        """This conversation's idle connection on the running loop, or None. The caller
        owns it until it is handed back with put()."""
        key = (asyncio.get_running_loop(), conversation_id)
        with self._lock:
            entry = self._idle.pop(key, None)
        if entry is None:
            return None
        socket, watcher = entry
        watcher.cancel()
        return socket

    def put(self, conversation_id, socket):
        key = (asyncio.get_running_loop(), conversation_id)
        watcher = asyncio.get_running_loop().create_task(self._close_when_idle(key, socket))
        with self._lock:
            self._idle[key] = (socket, watcher)

    async def _close_when_idle(self, key, socket):
        try:
            await asyncio.sleep(IDLE_CLOSE_SECONDS)
        finally:
            # still idle (not taken back for a turn): idle timeout or loop shutdown
            with self._lock:
                idle = self._idle.get(key, (None,))[0] is socket
                if idle:
                    del self._idle[key]
            if idle:
                await close_quietly(socket)
