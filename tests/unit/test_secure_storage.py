# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for owner-only secure file writes (config.write_secure_file).

These cover the credential/provider-key storage hardening: secret files must be
created atomically with 0600 permissions so they are never world-readable, even
on first creation.
"""

import os
import stat

import pytest

from humanbound_cli.config import write_secure_file


def test_write_secure_file_writes_content(tmp_path):
    target = tmp_path / "nested" / "credentials.json"
    write_secure_file(target, '{"api_token": "secret"}')
    assert target.read_text() == '{"api_token": "secret"}'


def test_write_secure_file_overwrites_and_leaves_no_temp(tmp_path):
    target = tmp_path / "config.yaml"
    write_secure_file(target, "first")
    write_secure_file(target, "second")
    assert target.read_text() == "second"
    # The atomic replace must not leave temp artifacts behind.
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_write_secure_file_is_owner_only(tmp_path):
    target = tmp_path / "credentials.json"
    write_secure_file(target, "x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
