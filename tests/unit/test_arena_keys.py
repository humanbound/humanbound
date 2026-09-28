# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Tests for the arena key store (arena.env) and env resolution."""

import os

import pytest

from humanbound_cli.arena import keys
from humanbound_cli.arena.keys import (
    is_reserved,
    is_valid_name,
    mask,
    parse_env_file,
    read_config,
    resolve_env,
    set_value,
    unset_value,
    write_env_file,
)

from .arena_testing import mode_of


def test_set_read_unset_round_trip(arena_home):
    set_value("OPENAI_API_KEY", "sk-abc")
    set_value("OTHER", "x=y")
    path = arena_home / "arena.env"
    assert keys.config_file() == path
    assert read_config() == {"OPENAI_API_KEY": "sk-abc", "OTHER": "x=y"}
    assert mode_of(path) == 0o600
    assert mode_of(arena_home) == 0o700
    assert unset_value("OPENAI_API_KEY") is True
    assert unset_value("OPENAI_API_KEY") is False
    assert read_config() == {"OTHER": "x=y"}
    assert mode_of(path) == 0o600


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("1BAD", "v"),
        ("HB_API_KEY", "v"),
        ("humanbound_token", "v"),
        ("K", "a\nb"),
        ("K", "a\rb"),
        ("K", "a\0b"),
        ("K", " v"),
        ("K", "v "),
        ("K", '"v"'),
        ("K", "'v'"),
    ],
)
def test_set_value_rejects(arena_home, key, value):
    with pytest.raises(ValueError):
        set_value(key, value)
    assert not (arena_home / "arena.env").exists()


def test_parse_env_file(tmp_path):
    path = tmp_path / "x.env"
    path.write_text(
        "# comment\n\nA=one\nexport B=\"two words\"\nC='three'\nnot a line\n1BAD=x\nD=é\n",
        encoding="utf-8",
    )
    assert parse_env_file(path) == {"A": "one", "B": "two words", "C": "three", "D": "é"}


def test_parse_env_file_non_utf8(tmp_path):
    path = tmp_path / "x.env"
    path.write_bytes(b"A=\xff\xfe\n")
    with pytest.raises(UnicodeDecodeError):
        parse_env_file(path)


@pytest.mark.parametrize("values", [{"1BAD": "v"}, {"K": "a\nb"}, {"K": "a\rb"}, {"K": "a\0b"}])
def test_write_env_file_rejects(tmp_path, values):
    with pytest.raises(ValueError):
        write_env_file(tmp_path / "x.env", values)
    assert list(tmp_path.iterdir()) == []


def test_write_env_file_atomic_and_0600(tmp_path, monkeypatch):
    path = tmp_path / "run" / "a.env"
    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((os.path.dirname(src), os.path.basename(src), dst))
        return real_replace(src, dst)

    monkeypatch.setattr(keys.os, "replace", spy)
    write_env_file(path, {"A": "1", "B": "two"})
    assert path.read_text() == "A=1\nB=two\n"
    assert mode_of(path) == 0o600
    assert len(replaced) == 1
    src_dir, src_name, dst = replaced[0]
    assert src_dir == str(path.parent) and src_name.startswith(".tmp-")
    assert str(dst) == str(path)


def test_write_env_file_failure_leaves_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "a.env"
    path.write_text("OLD=1\n")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(keys.os, "replace", boom)
    with pytest.raises(OSError):
        write_env_file(path, {"A": "1"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.env"]
    assert path.read_text() == "OLD=1\n"


def test_resolve_env_requires_allow_shell_keyword(arena_home):
    with pytest.raises(TypeError):
        resolve_env(["A"], [])  # type: ignore[call-arg]


@pytest.fixture
def three_sources(arena_home, tmp_path, monkeypatch):
    set_value("A", "from-config")
    set_value("B", "from-config")
    set_value("C", "from-config")
    monkeypatch.setenv("B", "from-shell")
    monkeypatch.setenv("C", "from-shell")
    monkeypatch.setenv("E", "from-shell")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("D", raising=False)
    env_file = tmp_path / "extra.env"
    env_file.write_text("C=from-file\n")
    return env_file


@pytest.mark.parametrize("allow_shell", [True, False])
def test_resolve_env_reads_only_llm_names_from_the_shell(three_sources, allow_shell):
    # B, C and E are in the shell but aren't LLM key names: never read from it
    env, missing = resolve_env(["A", "B", "C", "D"], ["E"], three_sources, allow_shell=allow_shell)
    assert env == {"A": "from-config", "B": "from-config", "C": "from-file"}
    assert missing == ["D"]


def test_resolve_env_precedence_with_shell(arena_home, tmp_path, monkeypatch):
    set_value("OPENAI_API_KEY", "from-config")
    set_value("OPENAI_MODEL", "from-config")
    set_value("ANTHROPIC_API_KEY", "from-config")
    monkeypatch.setenv("OPENAI_MODEL", "from-shell")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.setenv("GROQ_API_KEY", "from-shell")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_file = tmp_path / "extra.env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
    env, missing = resolve_env(
        ["OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY"],
        ["GROQ_API_KEY"],
        env_file,
        allow_shell=True,
    )
    assert env == {
        "OPENAI_API_KEY": "from-config",
        "OPENAI_MODEL": "from-shell",
        "ANTHROPIC_API_KEY": "from-file",
        "GROQ_API_KEY": "from-shell",
    }
    assert missing == ["MISTRAL_API_KEY"]


def test_shell_key_allowlist():
    from humanbound_cli.arena.keys import SHELL_KEYS

    assert SHELL_KEYS == frozenset(
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


def test_resolve_env_never_resolves_reserved(arena_home, tmp_path, monkeypatch):
    monkeypatch.setenv("HB_API_KEY", "secret")
    monkeypatch.setenv("HUMANBOUND_TOKEN", "secret")
    env_file = tmp_path / "extra.env"
    env_file.write_text("HB_API_KEY=secret\n")
    env, missing = resolve_env(["HB_API_KEY"], ["HUMANBOUND_TOKEN"], env_file, allow_shell=True)
    assert env == {}
    assert missing == ["HB_API_KEY"]
    env, _ = resolve_env([], [], env_file, allow_shell=True)
    assert "HB_API_KEY" not in env


def test_mask():
    assert mask("short") == "****"
    assert mask("sk-abcdefghijklmnop") == "sk-…mnop"


def test_helpers():
    assert is_valid_name("OK_1")
    assert not is_valid_name("1BAD")
    assert not is_valid_name("")
    assert not is_valid_name("OK\n")
    assert is_reserved("hb_x")
    assert is_reserved("HUMANBOUND_X")
    assert not is_reserved("OPENAI_API_KEY")


@pytest.mark.parametrize("bad", ["a\nb", "a\rb"])
def test_resolve_env_rejects_control_chars_from_shell(arena_home, monkeypatch, bad):
    monkeypatch.setenv("OPENAI_API_KEY", bad)
    with pytest.raises(ValueError, match="OPENAI_API_KEY") as e:
        resolve_env(["OPENAI_API_KEY"], [], allow_shell=True)
    assert bad not in str(e.value)


def test_resolve_env_rejects_nul_from_env_file(arena_home, tmp_path):
    env_file = tmp_path / "k.env"
    env_file.write_bytes(b"OPT=sec\x00ret\n")
    with pytest.raises(ValueError, match="cannot use key OPT") as e:
        resolve_env([], ["OPT"], env_file, allow_shell=False)
    assert "sec" not in str(e.value)


def test_resolve_env_ignores_bad_values_of_undeclared_keys(arena_home, monkeypatch):
    monkeypatch.setenv("NOT_DECLARED", "a\nb")
    assert resolve_env([], [], allow_shell=True) == ({}, [])
