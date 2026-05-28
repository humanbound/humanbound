"""Unit tests for docs/hooks/lint.py."""

import logging
from types import SimpleNamespace

import pytest
from mkdocs.exceptions import PluginError

import lint


@pytest.fixture
def warn_records():
    """Capture records emitted by lint's docs.lint logger.

    lint.py sets `propagate = False` on warn_log so MkDocs strict mode doesn't
    escalate warn-only checks. That same flag prevents pytest's `caplog`
    fixture from seeing the records via the root logger, so we attach our own
    handler for the duration of the test.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    lint.warn_log.addHandler(handler)
    try:
        yield records
    finally:
        lint.warn_log.removeHandler(handler)


class TestFirstBlockKind:
    def test_paragraph_only(self):
        assert lint._first_block_kind("Some words here.\n\nMore words.") == "paragraph"

    def test_h1_then_paragraph_is_paragraph(self):
        # H1 is skipped (universal convention); next block is the paragraph.
        assert lint._first_block_kind("# Title\n\nSome lede paragraph.") == "paragraph"

    def test_h1_then_h2_is_heading(self):
        assert lint._first_block_kind("# Title\n\n## Subheading") == "heading"

    def test_h2_alone_is_heading(self):
        assert lint._first_block_kind("## Subheading") == "heading"

    def test_h1_then_code_is_code(self):
        assert lint._first_block_kind("# Title\n\n```python\ncode\n```") == "code"

    def test_h1_then_admonition_is_admonition(self):
        assert lint._first_block_kind("# Title\n\n!!! note\n    body") == "admonition"

    def test_h1_then_table_is_table(self):
        assert lint._first_block_kind("# Title\n\n| col |\n|-----|") == "table"

    def test_h1_alone_is_empty(self):
        # Only an H1, nothing else.
        assert lint._first_block_kind("# Title") == "empty"

    def test_leading_blank_lines_skipped(self):
        assert lint._first_block_kind("\n\n\nSome words.") == "paragraph"

    def test_empty(self):
        assert lint._first_block_kind("") == "empty"

    def test_whitespace_only(self):
        assert lint._first_block_kind("   \n\n  ") == "empty"


class TestFirstParagraph:
    def test_single_line(self):
        assert lint._first_paragraph("Just one line.") == "Just one line."

    def test_multiline_paragraph(self):
        md = "Line one.\nLine two.\nLine three.\n\nNext paragraph."
        assert lint._first_paragraph(md) == "Line one. Line two. Line three."

    def test_skips_leading_h1(self):
        assert lint._first_paragraph("# Title\n\nReal lede text here.") == "Real lede text here."

    def test_h1_alone_returns_empty(self):
        assert lint._first_paragraph("# Title") == ""

    def test_leading_blanks_stripped(self):
        assert lint._first_paragraph("\n\nHello.") == "Hello."

    def test_stops_at_blank_line(self):
        assert lint._first_paragraph("First.\n\nSecond.") == "First."


class TestSkip:
    def _page(self, lint_skip):
        return SimpleNamespace(meta={"lint_skip": lint_skip} if lint_skip is not None else {})

    def test_skip_matches(self):
        assert lint._skip(self._page(["first_paragraph"]), "first_paragraph") is True

    def test_skip_not_in_list(self):
        assert lint._skip(self._page(["other"]), "first_paragraph") is False

    def test_no_lint_skip(self):
        assert lint._skip(self._page(None), "first_paragraph") is False

    def test_lint_skip_not_a_list(self):
        assert lint._skip(self._page("first_paragraph"), "first_paragraph") is False


class TestCheckDescription:
    def _page(self, desc):
        return SimpleNamespace(
            meta={"description": desc} if desc is not None else {},
            file=SimpleNamespace(src_path="foo.md"),
        )

    def test_present_passes(self):
        lint._check_description(self._page("A description."))  # no exception

    def test_missing_raises(self):
        with pytest.raises(PluginError, match="missing required frontmatter 'description:'"):
            lint._check_description(self._page(None))

    def test_empty_raises(self):
        with pytest.raises(PluginError, match="missing required frontmatter"):
            lint._check_description(self._page("   "))


class TestCheckFirstBlock:
    def _page(self, lint_skip=None):
        return SimpleNamespace(
            meta={"lint_skip": lint_skip} if lint_skip else {},
            file=SimpleNamespace(src_path="foo.md"),
        )

    def test_paragraph_passes(self):
        lint._check_first_block("Some intro paragraph.\n\nMore.", self._page())

    def test_h1_then_paragraph_passes(self):
        lint._check_first_block("# Title\n\nSome lede.", self._page())

    def test_h1_then_heading_raises(self):
        with pytest.raises(PluginError, match="starts with a heading"):
            lint._check_first_block("# Title\n\n## Subheading", self._page())

    def test_h2_alone_raises(self):
        with pytest.raises(PluginError, match="starts with a heading"):
            lint._check_first_block("## Subheading", self._page())

    def test_admonition_after_h1_raises(self):
        with pytest.raises(PluginError, match="starts with a admonition"):
            lint._check_first_block("# Title\n\n!!! note\n    body", self._page())

    def test_lint_skip_bypasses(self):
        lint._check_first_block("# Title\n\n## Heading first", self._page(lint_skip=["first_paragraph"]))


class TestCheckKeywords:
    def _page(self, keywords):
        return SimpleNamespace(
            meta={"keywords": keywords} if keywords is not None else {},
            file=SimpleNamespace(src_path="foo.md"),
        )

    def test_list_passes(self):
        lint._check_keywords(self._page(["a", "b"]))  # no exception

    def test_string_passes(self):
        lint._check_keywords(self._page("a, b"))  # no exception

    def test_missing_raises(self):
        with pytest.raises(PluginError, match="missing required frontmatter 'keywords:'"):
            lint._check_keywords(self._page(None))

    def test_empty_list_raises(self):
        with pytest.raises(PluginError, match="missing required frontmatter"):
            lint._check_keywords(self._page([]))


class TestCheckLedeQuality:
    def _page(self):
        return SimpleNamespace(meta={}, file=SimpleNamespace(src_path="foo.md"))

    def test_long_strong_lede_no_warnings(self, warn_records):
        # H1 + a >=30 word non-weak-opener lede
        md = "# Title\n\nA strong opening paragraph that contains well over thirty words of useful content describing what this page actually covers in concrete terms is exactly the kind of lede chat agents extract from."
        lint._check_lede_quality(md, self._page())
        assert not warn_records

    def test_short_paragraph_warns(self, warn_records):
        lint._check_lede_quality("# Title\n\nShort lede here.", self._page())
        messages = [r.getMessage() for r in warn_records]
        assert any("only" in m and "words" in m for m in messages)

    def test_weak_opener_warns(self, warn_records):
        md = "# Title\n\nThis page describes how to do many things including the configuration of providers and the management of API keys and other concerns."
        lint._check_lede_quality(md, self._page())
        assert any("weak opener" in r.getMessage() for r in warn_records)

    def test_non_paragraph_skipped(self, warn_records):
        # If first block (after H1) is not a paragraph, the hard-fail handler covers it; quality check noops.
        lint._check_lede_quality("# Title\n\n## Heading", self._page())
        assert not warn_records
