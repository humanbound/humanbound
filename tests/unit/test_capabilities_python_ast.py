# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""AST verifier: confirms or rejects regex hits on Python source."""

from humanbound_cli.extractors.capabilities.python_ast import (
    is_real_code_at_line,
)


def test_real_code_at_decorator_line():
    src = "from langchain.tools import tool\n\n@tool\ndef my_tool(): pass\n"
    assert is_real_code_at_line(src, 3) is True  # @tool decorator line


def test_inside_string_literal_is_not_real_code():
    src = "doc = '''\n@tool\ndef example(): pass\n'''\n"
    assert is_real_code_at_line(src, 2) is False


def test_inside_comment_is_not_real_code():
    src = "# @tool\nx = 1\n"
    assert is_real_code_at_line(src, 1) is False


def test_syntax_error_falls_back_to_pattern_only():
    src = "@tool\ndef broken(:\n"  # SyntaxError
    # On parse failure we cannot verify; choose to accept the hit (pattern-only).
    assert is_real_code_at_line(src, 1) is True


from humanbound_cli.extractors.capabilities.python_ast import has_use_site


def test_lone_import_has_no_use_site():
    src = "import chromadb\n\nprint('hi')\n"
    assert has_use_site(src, "chromadb") is False


def test_import_with_attribute_access_counts():
    src = "import chromadb\nchromadb.PersistentClient()\n"
    assert has_use_site(src, "chromadb") is True


def test_from_import_with_call_counts():
    src = "from langchain.tools import tool\n@tool\ndef x(): pass\n"
    assert has_use_site(src, "tool") is True


def test_from_import_unused_does_not_count():
    src = "from langchain.tools import tool\nx = 1\n"
    assert has_use_site(src, "tool") is False
