# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Where arena state lives and where the gateway listens."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

from ..config import get_humanbound_dir

DEFAULT_GATEWAY_PORT = 11500
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/humanbound/humanbound-arena/main/index.json"
# Host headers / bind hosts that count as "this machine only".
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")
TOKEN_FILE = "gateway.token"
# What secrets.token_urlsafe(32) produces (43 chars); anything else in the file is replaced.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def arena_dir() -> Path:
    """~/.humanbound/arena, resolved at call time so tests can move HOME."""
    return get_humanbound_dir() / "arena"


def ensure_arena_dir() -> Path:
    """arena_dir(), created if needed and made private to the user (0700 on POSIX)."""
    path = arena_dir()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path, 0o700)
    return path


def owner_of(directory: Path) -> str:
    """The owner id for an arena directory: 12 hex chars of sha256 of its resolved path
    (case-folded on macOS and Windows, whose file systems usually ignore case, so HOME=/Users/Me
    and HOME=/users/me are one owner)."""
    path = str(Path(directory).resolve())
    if sys.platform in ("darwin", "win32"):
        path = path.casefold()
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]


def arena_owner() -> str:
    """Who owns this arena: one id per arena_dir(), so two HOMEs (users, sandboxes, CI jobs)
    sharing one Docker daemon get separate containers, networks and gateways."""
    return owner_of(arena_dir())


def gateway_port() -> int:
    raw = os.environ.get("HB_ARENA_PORT")
    if not raw:
        return DEFAULT_GATEWAY_PORT
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError(f"HB_ARENA_PORT must be a port number between 1 and 65535, got '{raw}'")
    return port


def gateway_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port if port is not None else gateway_port()}"


# ── the gateway access token ──


def token_file() -> Path:
    return arena_dir() / TOKEN_FILE


def _read_token(path: Path) -> str | None:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token if TOKEN_RE.fullmatch(token) else None


def gateway_token(*, create: bool = True) -> str | None:
    """This owner's gateway access token, from arena_dir()/gateway.token (0600).

    Created on first need (with `create`); an unreadable or malformed file is replaced.
    Two processes creating it at once agree on one token: the file is published with a
    hard link, which never overwrites a token another process wrote first.
    """
    path = token_file()
    token = _read_token(path)
    if token is not None:
        if os.name != "nt":
            try:
                if path.stat().st_mode & 0o077:
                    os.chmod(path, 0o600)
            except OSError:
                pass
        return token
    if not create:
        return None
    ensure_arena_dir()
    token = secrets.token_urlsafe(32)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{TOKEN_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if os.name != "nt":
                os.fchmod(fh.fileno(), 0o600)
            fh.write(token + "\n")
        existing = path.exists()
        if existing:
            os.replace(tmp, path)  # a malformed token: replace it
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass  # another process won: use its token
            except OSError:
                os.replace(tmp, path)  # no hard links on this file system
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return _read_token(path) or token


def auth_headers(token: str | None = None) -> dict[str, str]:
    """The header hb sends to its own gateway."""
    return {"Authorization": f"Bearer {token or gateway_token()}"}
