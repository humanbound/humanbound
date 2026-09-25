# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""LLM keys and other env vars that arena agents need.

Stored in ~/.humanbound/arena/arena.env (0600). These are the *agents'* keys; the
CLI's own credentials (HB_API_KEY, hb login) are never read or reused here.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

from .paths import arena_dir

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_RE = re.compile(r"^(HB_|HUMANBOUND_)", re.IGNORECASE)
_BAD_VALUE_CHARS = ("\n", "\r", "\0")


def is_valid_name(name: str) -> bool:
    return bool(_KEY_RE.match(name))


def is_reserved(name: str) -> bool:
    """True for env names that belong to hb itself (HB_*, HUMANBOUND_*), never to agents."""
    return bool(_RESERVED_RE.match(name))


def config_file() -> Path:
    return arena_dir() / "arena.env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Atomically write KEY=VALUE lines readable only by the user (docker --env-file format)."""
    for key, value in values.items():
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid key name: {key!r}")
        if any(c in value for c in _BAD_VALUE_CHARS):
            raise ValueError(f"value for {key} cannot contain newlines or NUL bytes")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    os.chmod(path, 0o600)


def read_config() -> dict[str, str]:
    path = config_file()
    return parse_env_file(path) if path.exists() else {}


def set_value(key: str, value: str) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(f"invalid key name: {key!r}")
    if any(c in value for c in _BAD_VALUE_CHARS):
        raise ValueError("values cannot contain newlines or NUL bytes")
    if value != value.strip():
        raise ValueError("values cannot start or end with whitespace")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        raise ValueError("don't wrap the value in quotes; pass it bare")
    values = read_config()
    values[key] = value
    write_env_file(config_file(), values)


def unset_value(key: str) -> bool:
    values = read_config()
    if key not in values:
        return False
    del values[key]
    write_env_file(config_file(), values)
    return True


def mask(value: str) -> str:
    return "****" if len(value) < 12 else f"{value[:3]}…{value[-4:]}"


def resolve_env(
    required: list[str], optional: list[str], env_file: Path | None = None
) -> tuple[dict[str, str], list[str]]:
    """Collect the declared keys. Later sources win: arena.env < process env < --env-file.

    hb's own credentials (HB_*, HUMANBOUND_*) are never handed out, even if asked for.
    """
    sources = [read_config(), dict(os.environ), parse_env_file(env_file) if env_file else {}]
    env: dict[str, str] = {}
    for key in [*required, *optional]:
        if is_reserved(key):
            continue
        for source in sources:
            if source.get(key):
                env[key] = source[key]
    missing = [k for k in required if k not in env]
    return env, missing
