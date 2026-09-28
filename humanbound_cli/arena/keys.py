# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""LLM keys and other env vars that arena agents need.

Stored in ~/.humanbound/arena/arena.env (0600). These are the *agents'* keys; hb's own
credentials (HB_*, HUMANBOUND_*, hb login) are never read, stored or passed here.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .manifest import RESERVED_ENV_PREFIXES
from .paths import arena_dir, ensure_arena_dir

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The only names ever read from the shell, and only for agents from the default catalog: LLM
# provider keys and endpoints. Anything else an agent declares comes from arena.env or
# --env-file, so an exported secret is never handed to an agent by accident.
SHELL_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "OLLAMA_HOST",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
    }
)
_FORBIDDEN_CHARS = ("\n", "\r", "\0")


def is_valid_name(name: str) -> bool:
    return bool(_KEY_RE.fullmatch(name or ""))


def is_reserved(name: str) -> bool:
    return (name or "").upper().startswith(RESERVED_ENV_PREFIXES)


def config_file() -> Path:
    return arena_dir() / "arena.env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not is_valid_name(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Atomically write KEY=VALUE lines readable only by the user (docker --env-file compatible)."""
    for key, value in values.items():
        if not is_valid_name(key):
            raise ValueError(f"invalid key name: {key!r}")
        if any(c in value for c in _FORBIDDEN_CHARS):
            raise ValueError(f"value for {key} contains a newline or NUL")
    path = Path(path)
    if arena_dir() in path.parents:
        ensure_arena_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".env")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_config() -> dict[str, str]:
    path = config_file()
    return parse_env_file(path) if path.exists() else {}


def set_value(key: str, value: str) -> None:
    if not is_valid_name(key):
        raise ValueError(f"invalid key name: {key!r}")
    if is_reserved(key):
        raise ValueError(f"{key} is reserved for hb's own credentials")
    if any(c in value for c in _FORBIDDEN_CHARS):
        raise ValueError("values cannot contain newlines")
    if value != value.strip():
        raise ValueError("values cannot start or end with whitespace")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        raise ValueError("don't wrap the value in quotes")
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
    required: list[str],
    optional: list[str],
    env_file: Path | None = None,
    *,
    allow_shell: bool,
) -> tuple[dict[str, str], list[str]]:
    """Collect the declared keys. Later sources win: arena.env < process env (only if
    allow_shell, and only SHELL_KEYS names) < --env-file. Reserved names are never resolved.

    Raises ValueError (naming the key, never the value) when a resolved value contains a
    newline, carriage return or NUL, since it couldn't be passed to the container intact."""
    sources = [read_config()]
    if allow_shell:
        sources.append({k: v for k, v in os.environ.items() if k in SHELL_KEYS})
    if env_file:
        sources.append(parse_env_file(env_file))
    env: dict[str, str] = {}
    for key in [*required, *optional]:
        if is_reserved(key):
            continue
        for source in sources:
            if source.get(key):
                env[key] = source[key]
    for key, value in env.items():
        if any(c in value for c in _FORBIDDEN_CHARS):
            raise ValueError(
                f"cannot use key {key}: its value contains a newline, carriage return or NUL"
            )
    missing = [k for k in required if k not in env]
    return env, missing
