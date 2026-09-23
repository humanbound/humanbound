"""
Emit an llms.txt index of all documentation pages.

Runs once after the build completes. Walks the resolved nav structure and
writes a markdown index with absolute URLs, grouped by top-level section.
Chat agents (ChatGPT, Claude, Perplexity) read this file to discover which
pages exist before deciding what to fetch.

Also writes llms-full.txt (every page's markdown, in nav order) and a .md copy
of each page next to its HTML.

Convention: https://llmstxt.org/
"""

from __future__ import annotations

import os
import re

from mkdocs.plugins import get_plugin_logger
from mkdocs.structure.nav import Navigation, Section
from mkdocs.structure.pages import Page

log = get_plugin_logger(__name__)

# Strip a leading emoji + optional whitespace from nav labels.
# Material nav uses unicode emoji at the start of section titles (e.g. "🚀 Getting Started").
_EMOJI_PREFIX = re.compile(r"^[\U0001F300-\U0001FAFF\U00002600-\U000027BF✨⭐]+\s*")


def _strip_emoji(label: str) -> str:
    """Strip a leading emoji (with any variation selectors / combining marks) and whitespace."""
    cleaned = _EMOJI_PREFIX.sub("", label)
    # Strip any leftover variation selectors, joiners, or non-alphanumeric junk
    # that followed the base emoji glyph (e.g. U+FE0F, U+200D, skin-tone modifiers).
    while cleaned and not cleaned[0].isalnum():
        cleaned = cleaned[1:]
    return cleaned.strip()


def _absolute_url(page: Page, site_url: str) -> str:
    base = site_url.rstrip("/")
    path = page.url.lstrip("/")
    return f"{base}/{path}"


def _description(page: Page, site_description: str) -> str:
    desc = page.meta.get("description") if page.meta else None
    return desc.strip() if isinstance(desc, str) and desc.strip() else site_description


def _format_page_line(
    page: Page, site_url: str, site_description: str, title_prefix: str = ""
) -> str:
    title = _strip_emoji(page.title) if page.title else page.file.src_path
    if title_prefix:
        title = f"{_strip_emoji(title_prefix)}: {title}"
    url = _absolute_url(page, site_url)
    desc = _description(page, site_description)
    return f"- [{title}]({url}): {desc}"


def _emit_section(section: Section, site_url: str, site_description: str, lines: list[str]) -> None:
    """Emit one top-level section. Sub-sections flatten into prefixed page titles."""
    lines.append(f"## {_strip_emoji(section.title)}")
    lines.append("")
    for child in section.children:
        if isinstance(child, Page):
            lines.append(_format_page_line(child, site_url, site_description))
        elif isinstance(child, Section):
            for grandchild in child.children:
                if isinstance(grandchild, Page):
                    lines.append(
                        _format_page_line(
                            grandchild, site_url, site_description, title_prefix=child.title
                        )
                    )
    lines.append("")


def _build_llms_txt(nav: Navigation, site_url: str, site_name: str, site_description: str) -> str:
    lines: list[str] = [f"# {site_name}", "", f"> {site_description}", ""]
    for item in nav.items:
        if isinstance(item, Page):
            # Top-level standalone page (e.g. Home, Deployment) gets its own heading,
            # otherwise it reads as part of the preceding section.
            lines.append(f"## {_strip_emoji(item.title)}")
            lines.append("")
            lines.append(_format_page_line(item, site_url, site_description))
            lines.append("")
        elif isinstance(item, Section):
            _emit_section(item, site_url, site_description, lines)
    return "\n".join(lines).rstrip() + "\n"


def _nav_pages(items) -> list[Page]:
    pages: list[Page] = []
    for item in items:
        if isinstance(item, Page):
            pages.append(item)
        elif isinstance(item, Section):
            pages.extend(_nav_pages(item.children))
    return pages


def _build_llms_full_txt(
    pages: list[Page], site_url: str, site_name: str, site_description: str
) -> str:
    parts = [f"# {site_name}\n\n> {site_description}\n"]
    for page in pages:
        parts.append(f"---\n\nSource: {_absolute_url(page, site_url)}\n\n{page.markdown.strip()}\n")
    return "\n".join(parts)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# Module-level cache so on_post_build can use the nav captured by on_nav.
# MkDocs does not pass nav to on_post_build; we have to stash it ourselves.
_NAV: Navigation | None = None
_FILES = None


def on_nav(nav, config, files):
    """MkDocs lifecycle hook: capture the resolved nav for use after build."""
    global _NAV, _FILES
    _NAV = nav
    _FILES = files
    return nav


def on_post_build(config):
    """MkDocs lifecycle hook: write llms.txt to the built site root."""
    if _NAV is None:
        log.warning("llms_txt: nav not captured; skipping emit")
        return

    site_name = config["site_name"]
    if not site_name.lower().endswith("docs"):
        site_name = f"{site_name} Docs"

    content = _build_llms_txt(
        nav=_NAV,
        site_url=config["site_url"],
        site_name=site_name,
        site_description=config["site_description"],
    )

    out_path = os.path.join(config["site_dir"], "llms.txt")
    _write(out_path, content)
    log.info("llms_txt: wrote %s (%d bytes)", out_path, len(content))

    # Per-page markdown mirrors the source tree, so /deployment/ is also served
    # as /deployment.md and relative links between .md files keep resolving.
    # Covers pages outside the nav too, since nav pages may link to them.
    doc_files = _FILES.documentation_pages()
    for file in doc_files:
        _write(os.path.join(config["site_dir"], file.src_uri), file.page.markdown)

    full = _build_llms_full_txt(
        _nav_pages(_NAV.items), config["site_url"], site_name, config["site_description"]
    )
    full_path = os.path.join(config["site_dir"], "llms-full.txt")
    _write(full_path, full)
    log.info(
        "llms_txt: wrote %s (%d bytes) and %d page .md files",
        full_path,
        len(full),
        len(doc_files),
    )
