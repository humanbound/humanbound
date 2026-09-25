# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Where arena state lives and where the gateway listens."""

from __future__ import annotations

import os
from pathlib import Path

from ..config import get_humanbound_dir

DEFAULT_GATEWAY_PORT = 11500
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/humanbound/humanbound-arena/main/index.json"


def arena_dir() -> Path:
    """~/.humanbound/arena, resolved at call time so tests can move HOME."""
    return get_humanbound_dir() / "arena"


def gateway_port() -> int:
    raw = os.environ.get("HB_ARENA_PORT")
    return int(raw) if raw else DEFAULT_GATEWAY_PORT


def gateway_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or gateway_port()}"
