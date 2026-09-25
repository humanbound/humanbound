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
