"""Unit tests for docs/hooks/llms_txt.py."""

from types import SimpleNamespace

import pytest

# The docs hooks import `mkdocs` at module load; it only ships in the `[dev]`
# extra. Skip (don't error) when it's absent so `pytest` works on a plain install.
pytest.importorskip("mkdocs")

import llms_txt


class TestStripEmoji:
    def test_strips_leading_emoji(self):
        assert llms_txt._strip_emoji("🚀 Getting Started") == "Getting Started"

    def test_strips_variation_selector(self):
        # 🖥️ has a U+FE0F variation selector after the base emoji
        assert llms_txt._strip_emoji("🖥️ Local Engine") == "Local Engine"

    def test_passthrough_no_emoji(self):
        assert llms_txt._strip_emoji("Getting Started") == "Getting Started"

    def test_empty_string(self):
        assert llms_txt._strip_emoji("") == ""


class TestAbsoluteUrl:
    def _page(self, url):
        return SimpleNamespace(url=url)

    def test_relative_url_joined(self):
        page = self._page("getting-started/installation/")
        assert (
            llms_txt._absolute_url(page, "https://docs.humanbound.ai")
            == "https://docs.humanbound.ai/getting-started/installation/"
        )

    def test_trailing_slash_in_site_url_handled(self):
        page = self._page("foo/")
        assert (
            llms_txt._absolute_url(page, "https://docs.humanbound.ai/")
            == "https://docs.humanbound.ai/foo/"
        )

    def test_leading_slash_in_page_url_handled(self):
        page = self._page("/foo/")
        assert (
            llms_txt._absolute_url(page, "https://docs.humanbound.ai")
            == "https://docs.humanbound.ai/foo/"
        )


class TestDescription:
    def test_uses_page_description_when_present(self):
        page = SimpleNamespace(meta={"description": "Page desc."})
        assert llms_txt._description(page, "Site desc.") == "Page desc."

    def test_falls_back_to_site_description_when_empty(self):
        page = SimpleNamespace(meta={"description": "   "})
        assert llms_txt._description(page, "Site desc.") == "Site desc."

    def test_falls_back_when_missing(self):
        page = SimpleNamespace(meta={})
        assert llms_txt._description(page, "Site desc.") == "Site desc."

    def test_no_meta_at_all(self):
        page = SimpleNamespace(meta=None)
        assert llms_txt._description(page, "Site desc.") == "Site desc."


class TestFormatPageLine:
    def test_basic_line(self):
        page = SimpleNamespace(
            title="Installation",
            url="getting-started/installation/",
            meta={"description": "How to install."},
            file=SimpleNamespace(src_path="getting-started/installation.md"),
        )
        line = llms_txt._format_page_line(page, "https://docs.humanbound.ai", "Site desc.")
        assert (
            line
            == "- [Installation](https://docs.humanbound.ai/getting-started/installation/): How to install."
        )

    def test_strips_emoji_from_page_title(self):
        page = SimpleNamespace(
            title="🏠 Home",
            url="",
            meta={"description": "Welcome."},
            file=SimpleNamespace(src_path="index.md"),
        )
        line = llms_txt._format_page_line(page, "https://docs.humanbound.ai", "Site desc.")
        assert line.startswith("- [Home]")

    def test_with_title_prefix(self):
        page = SimpleNamespace(
            title="Installation",
            url="getting-started/installation/",
            meta={"description": "How."},
            file=SimpleNamespace(src_path="x.md"),
        )
        line = llms_txt._format_page_line(
            page, "https://x.com", "Site", title_prefix="🚀 Getting Started"
        )
        assert line.startswith("- [Getting Started: Installation]")
