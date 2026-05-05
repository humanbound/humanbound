# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""AST-level verifier for Python pattern matches.

Two responsibilities:

1. ``is_real_code_at_line`` — given source + 1-indexed line, return False
   if that line is entirely inside a string literal or a comment. Used
   to reject regex hits that fired on decorator-like text inside docstrings.

2. ``has_use_site`` — given source and an import name, return True if
   the source contains at least one usage (attribute access, call, or
   decorator reference) of the imported symbol. Used to reject
   capability hits that come from a lone import without any use site.
   (Added in Task 7.)
"""

from __future__ import annotations

import ast
import io
import tokenize


def is_real_code_at_line(source: str, line: int) -> bool:
    """Return True if the given 1-indexed line is real code (not in a
    string literal or comment)."""
    try:
        ast.parse(source)
    except SyntaxError:
        return True  # pattern-only fallback

    # Build a set of lines that fall inside string literal nodes
    # (multiline strings, docstrings).
    string_lines: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True

    # Only suppress lines that are INSIDE a multiline string body — not the
    # opening or closing line. A line like `model="o1-preview"` has a string
    # literal but is also real code (the string is just a value); the regex
    # should be allowed to match. A line like `@tool` *inside* a multiline
    # docstring (between the opening and closing triple-quote lines) IS the
    # string's content and should be suppressed.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", start)
            if start and end and end > start:
                for ln in range(start + 1, end):
                    string_lines.add(ln)

    if line in string_lines:
        return False

    # Comment detection via tokenize.
    try:
        toks = tokenize.tokenize(io.BytesIO(source.encode("utf-8")).readline)
        for tok in toks:
            if tok.type == tokenize.COMMENT and tok.start[0] == line:
                # If the comment is the only thing on this line, treat as
                # not-real-code. If there's also code on the line we'd
                # accept — but for our use case (decorator at column 0)
                # this is fine.
                stripped = source.splitlines()[line - 1].lstrip()
                if stripped.startswith("#"):
                    return False
    except tokenize.TokenizeError:
        pass

    return True


def has_use_site(source: str, name: str) -> bool:
    """Return True if ``name`` appears in the source as something other
    than the import statement itself.

    Considers attribute access (``name.foo``), calls (``name(...)``),
    and decorator references (``@name``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Pattern-only fallback: presence anywhere counts as use.
        return name in source

    use_count = 0
    import_lines: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name).split(".")[0] == name:
                    import_lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    import_lines.add(node.lineno)

    for node in ast.walk(tree):
        # Decorator reference: @name or @name.something
        if hasattr(node, "decorator_list"):
            for dec in getattr(node, "decorator_list", []):
                if _references_name(dec, name):
                    use_count += 1
        # Attribute access on the name: name.foo
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            use_count += 1
        # Bare call or reference: name(...) or name as expression
        if isinstance(node, ast.Name) and node.id == name and node.lineno not in import_lines:
            use_count += 1

    return use_count > 0


def _references_name(node, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id == name
    if isinstance(node, ast.Call):
        return _references_name(node.func, name)
    return False
