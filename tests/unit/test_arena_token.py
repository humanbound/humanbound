# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""The gateway access token: one per owner, in arena_dir()/gateway.token (0600)."""

from __future__ import annotations

import os
import sys

import pytest

from humanbound_cli.arena import paths

from .arena_testing import mode_of


def test_token_is_created_on_first_need(arena_home):
    assert not (arena_home / "gateway.token").exists()
    token = paths.gateway_token()
    assert len(token) >= 40
    assert (arena_home / "gateway.token").read_text(encoding="utf-8").strip() == token
    assert paths.token_file() == arena_home / "gateway.token"


def test_token_is_stable(arena_home):
    assert paths.gateway_token() == paths.gateway_token()


def test_token_differs_per_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "a"))
    first = paths.gateway_token()
    monkeypatch.setenv("HOME", str(tmp_path / "b"))
    assert paths.gateway_token() != first


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_file_is_private(arena_home):
    paths.gateway_token()
    assert mode_of(arena_home / "gateway.token") == 0o600
    assert mode_of(arena_home) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_file_permissions_are_tightened(arena_home):
    token = paths.gateway_token()
    os.chmod(arena_home / "gateway.token", 0o644)
    assert paths.gateway_token() == token
    assert mode_of(arena_home / "gateway.token") == 0o600


@pytest.mark.parametrize("content", ["", "  \n", "short", "has space in it and is long enough!!"])
def test_corrupt_token_is_replaced(arena_home, content):
    paths.ensure_arena_dir()
    (arena_home / "gateway.token").write_text(content, encoding="utf-8")
    token = paths.gateway_token()
    assert token != content.strip()
    assert paths.TOKEN_RE.fullmatch(token)
    assert paths.gateway_token() == token


def test_read_only_lookup_never_creates(arena_home):
    assert paths.gateway_token(create=False) is None
    assert not (arena_home / "gateway.token").exists()
    token = paths.gateway_token()
    assert paths.gateway_token(create=False) == token


def test_auth_headers(arena_home):
    token = paths.gateway_token()
    assert paths.auth_headers() == {"Authorization": f"Bearer {token}"}
