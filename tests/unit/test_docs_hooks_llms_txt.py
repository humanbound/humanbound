"""Unit tests for docs/hooks/llms_txt.py."""

from types import SimpleNamespace

import pytest

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


def _page(src_uri, title, markdown=""):
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import File
    from mkdocs.structure.pages import Page

    config = MkDocsConfig()
    config.load_dict({"site_name": "x"})
    page = Page(title, File(src_uri, "/src", "/site", use_directory_urls=True), config)
    page.meta = {"description": f"{title} desc."}
    page.markdown = markdown
    return page


class TestBuildLlmsTxt:
    def test_top_level_page_after_section_gets_own_heading(self):
        from mkdocs.structure.nav import Navigation, Section

        commands = _page("reference/commands.md", "Commands")
        community = _page("community.md", "🤝 Community")
        nav = Navigation([Section("📖 Reference", [commands]), community], [commands, community])

        out = llms_txt._build_llms_txt(nav, "https://x.com", "X Docs", "Site desc.")

        reference, community_section = out.split("## Reference\n", 1)[1].split("## Community\n")
        assert "Community" not in reference
        assert "- [Community](https://x.com/community/)" in community_section


class TestOnPostBuild:
    def test_writes_llms_full_and_per_page_markdown(self, tmp_path):
        from mkdocs.structure.files import Files
        from mkdocs.structure.nav import Navigation, Section

        install = _page("getting-started/installation.md", "Installation", "# Installation\n")
        deploy = _page("deployment.md", "Deployment", "# Deployment\n")
        orphan = _page("management/members.md", "Members", "# Members\n")
        nav = Navigation([Section("Getting Started", [install]), deploy], [install, deploy])
        files = Files([install.file, deploy.file, orphan.file])

        llms_txt.on_nav(nav, None, files)
        llms_txt.on_post_build(
            {
                "site_name": "X",
                "site_url": "https://x.com",
                "site_description": "Site desc.",
                "site_dir": str(tmp_path),
            }
        )

        assert (tmp_path / "getting-started/installation.md").read_text() == "# Installation\n"
        assert (tmp_path / "deployment.md").read_text() == "# Deployment\n"
        assert (tmp_path / "management/members.md").read_text() == "# Members\n"

        full = (tmp_path / "llms-full.txt").read_text()
        assert full.index("Source: https://x.com/getting-started/installation/") < full.index(
            "Source: https://x.com/deployment/"
        )
        assert "# Members" not in full
