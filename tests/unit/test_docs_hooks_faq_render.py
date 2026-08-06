"""Unit tests for docs/hooks/faq_render.py."""

import logging
from types import SimpleNamespace

import faq_render
import pytest


@pytest.fixture
def warn_records():
    """Capture records on faq_render's docs.faq_render logger."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    faq_render.warn_log.addHandler(handler)
    try:
        yield records
    finally:
        faq_render.warn_log.removeHandler(handler)


def _page(src_path="foo.md", faq=None):
    meta = {"faq": faq} if faq is not None else {}
    return SimpleNamespace(meta=meta, file=SimpleNamespace(src_path=src_path))


class TestNormalizeFaqItems:
    def test_valid_items(self):
        items = faq_render._normalize_faq_items([{"q": "What?", "a": "Answer."}], "foo.md")
        assert items == [{"q": "What?", "a": "Answer."}]

    def test_empty_list(self):
        assert faq_render._normalize_faq_items([], "foo.md") == []

    def test_not_a_list(self):
        assert faq_render._normalize_faq_items("garbage", "foo.md") == []
        assert faq_render._normalize_faq_items(None, "foo.md") == []
        assert faq_render._normalize_faq_items({"q": "x", "a": "y"}, "foo.md") == []

    def test_missing_q_logs_and_skips(self, warn_records):
        items = faq_render._normalize_faq_items([{"a": "no question"}], "foo.md")
        assert items == []
        assert any("missing q/a" in r.getMessage() for r in warn_records)

    def test_missing_a_logs_and_skips(self, warn_records):
        items = faq_render._normalize_faq_items([{"q": "no answer"}], "foo.md")
        assert items == []
        assert any("missing q/a" in r.getMessage() for r in warn_records)

    def test_non_dict_item_logs_and_skips(self, warn_records):
        items = faq_render._normalize_faq_items([{"q": "ok", "a": "ok"}, "garbage"], "foo.md")
        assert len(items) == 1
        assert any("not a mapping" in r.getMessage() for r in warn_records)

    def test_strips_whitespace(self):
        items = faq_render._normalize_faq_items([{"q": "  What?  ", "a": "  Answer.  "}], "foo.md")
        assert items == [{"q": "What?", "a": "Answer."}]


class TestRenderFaqBlock:
    def test_single_item(self):
        block = faq_render._render_faq_block([{"q": "What is X?", "a": "X is Y."}])
        assert "## Frequently asked questions" in block
        assert '??? question "What is X?"' in block
        assert "    X is Y." in block

    def test_multiple_items(self):
        block = faq_render._render_faq_block(
            [
                {"q": "Q1", "a": "A1"},
                {"q": "Q2", "a": "A2"},
            ]
        )
        assert block.count('??? question "') == 2

    def test_escapes_quotes_in_question(self):
        block = faq_render._render_faq_block([{"q": 'What is "X"?', "a": "Y."}])
        assert '??? question "What is \\"X\\"?"' in block

    def test_multiline_answer_indented(self):
        block = faq_render._render_faq_block([{"q": "Q", "a": "Line one.\nLine two."}])
        assert "    Line one." in block
        assert "    Line two." in block


class TestOnPageMarkdown:
    def test_no_marker_returns_unchanged(self):
        md = "# Title\n\nSome paragraph."
        page = _page(faq=[{"q": "X?", "a": "Y."}])
        assert faq_render.on_page_markdown(md, page, {}, []) == md

    def test_marker_with_valid_faq_renders_block(self):
        md = "# Title\n\nLede.\n\n<!-- faq -->"
        page = _page(faq=[{"q": "What?", "a": "Answer."}])
        result = faq_render.on_page_markdown(md, page, {}, [])
        assert "<!-- faq -->" not in result
        assert "## Frequently asked questions" in result
        assert '??? question "What?"' in result

    def test_marker_without_faq_removed_with_warning(self, warn_records):
        md = "# Title\n\nLede.\n\n<!-- faq -->"
        page = _page()
        result = faq_render.on_page_markdown(md, page, {}, [])
        assert "<!-- faq -->" not in result
        assert "Frequently asked questions" not in result
        assert any("no valid faq" in r.getMessage() for r in warn_records)

    def test_marker_with_empty_faq_removed_with_warning(self, warn_records):
        md = "# Title\n\n<!-- faq -->"
        page = _page(faq=[])
        result = faq_render.on_page_markdown(md, page, {}, [])
        assert "<!-- faq -->" not in result
        assert any("no valid faq" in r.getMessage() for r in warn_records)

    def test_multiple_markers_all_replaced(self):
        md = "<!-- faq -->\nmiddle\n<!-- faq -->"
        page = _page(faq=[{"q": "Q", "a": "A"}])
        result = faq_render.on_page_markdown(md, page, {}, [])
        assert "<!-- faq -->" not in result
        assert result.count("## Frequently asked questions") == 2
