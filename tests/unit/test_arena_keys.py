# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
import stat

import pytest

from humanbound_cli.arena import keys


def test_set_get_unset_round_trip_with_0600(arena_home):
    keys.set_value("OPENAI_API_KEY", "sk-test-1234567890")
    assert keys.read_config() == {"OPENAI_API_KEY": "sk-test-1234567890"}
    mode = stat.S_IMODE(keys.config_file().stat().st_mode)
    assert mode == 0o600
    assert keys.unset_value("OPENAI_API_KEY") is True
    assert keys.read_config() == {}
    assert keys.unset_value("OPENAI_API_KEY") is False


@pytest.mark.parametrize("key, value", [("1BAD", "x"), ("OK", "multi\nline")])
def test_set_rejects_bad_keys_and_newlines(arena_home, key, value):
    with pytest.raises(ValueError):
        keys.set_value(key, value)


def test_parse_env_file_handles_comments_export_and_quotes(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("# comment\n\nexport A=1\nB=\"two words\"\nC='3'\nnot a line\n")
    assert keys.parse_env_file(f) == {"A": "1", "B": "two words", "C": "3"}


def test_resolve_env_precedence_and_missing(arena_home, tmp_path, monkeypatch):
    keys.set_value("A", "from-config")
    keys.set_value("B", "from-config")
    monkeypatch.setenv("B", "from-process")
    monkeypatch.setenv("C", "from-process")
    env_file = tmp_path / "run.env"
    env_file.write_text("C=from-file\n")
    monkeypatch.setenv("HB_API_KEY", "never-used")

    env, missing = keys.resolve_env(["A", "B", "C", "D"], ["E"], env_file)

    assert env == {"A": "from-config", "B": "from-process", "C": "from-file"}
    assert missing == ["D"]


def test_mask_hides_most_of_the_value():
    assert keys.mask("short") == "****"
    assert keys.mask("sk-abcdefghijklmnop") == "sk-…mnop"


@pytest.mark.parametrize(
    "values",
    [
        {"1BAD": "x"},
        {"A-B": "x"},
        {"OK": "multi\nline"},
        {"OK": "carriage\rreturn"},
        {"OK": "nul\0byte"},
    ],
)
def test_write_env_file_rejects_bad_keys_and_control_chars(tmp_path, values):
    with pytest.raises(ValueError):
        keys.write_env_file(tmp_path / "d" / "x.env", values)
    assert not (tmp_path / "d" / "x.env").exists()


def test_write_env_file_is_atomic_and_private(tmp_path, monkeypatch):
    target = tmp_path / "d" / "x.env"
    keys.write_env_file(target, {"A": "old"})
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(keys.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        keys.write_env_file(target, {"A": "new"})
    assert target.read_text() == "A=old\n"
    assert [p.name for p in target.parent.iterdir()] == ["x.env"]


def test_write_env_file_replaces_content(tmp_path):
    target = tmp_path / "x.env"
    keys.write_env_file(target, {"A": "1", "B": "2"})
    keys.write_env_file(target, {"C": "3"})
    assert target.read_text() == "C=3\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("value", [" lead", "trail ", "\tx", '"quoted"', "'quoted'", "nul\0"])
def test_set_rejects_values_that_would_not_round_trip(arena_home, value):
    with pytest.raises(ValueError):
        keys.set_value("OK", value)


def test_set_accepts_inner_quotes_and_spaces(arena_home):
    keys.set_value("OK", 'a "b" c\'')
    assert keys.read_config() == {"OK": 'a "b" c\''}


def test_resolve_env_never_returns_hb_credentials(arena_home, tmp_path, monkeypatch):
    monkeypatch.setenv("HB_API_KEY", "hb-secret")
    monkeypatch.setenv("humanbound_token", "hb-token")
    env_file = tmp_path / "run.env"
    env_file.write_text("HB_API_KEY=from-file\n")

    env, missing = keys.resolve_env(["HB_API_KEY"], ["humanbound_token"], env_file)

    assert env == {}
    assert missing == ["HB_API_KEY"]
