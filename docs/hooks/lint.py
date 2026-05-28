"""
Per-page SEO/GEO lint for the docs site.

Runs on every page's raw markdown. Hard-fails the build on structural problems
(missing description, missing lede paragraph). Warn-only rules are layered in
later tasks. A page can opt out of structural lede checks with
`lint_skip: [first_paragraph]` in its frontmatter.

Warn-only checks use a stdlib logger (not `mkdocs.plugins.get_plugin_logger`)
so that `strict: true` does NOT escalate them into build failures. The
plugin logger is reserved for hard-fail context only.
"""

from __future__ import annotations

import logging

from mkdocs.exceptions import PluginError

# Stdlib logger: visible in build output, not tracked by MkDocs strict mode.
warn_log = logging.getLogger("docs.lint")
if not warn_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s - docs.lint: %(message)s"))
    warn_log.addHandler(_handler)
    warn_log.setLevel(logging.WARNING)
    warn_log.propagate = False


def _first_block_kind(markdown: str) -> str:
    """Classify the first 'content' block after an optional leading H1.

    The universal MkDocs convention is to start a page with `# Title`; that's
    not a GEO problem. The real failure mode is when the next block after the
    H1 (or the very first block, if no H1) is a heading, code, table, or
    admonition instead of a lede paragraph.
    """
    stripped = markdown.lstrip("\n")
    if not stripped.strip():
        return "empty"

    lines = stripped.split("\n")
    idx = 0

    # If the first non-blank line is an H1 (# Title — exactly one hash + space),
    # skip it and look at what comes next.
    first = lines[idx].lstrip()
    if first.startswith("# ") and not first.startswith("## "):
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines):
            return "empty"

    first_line = lines[idx].lstrip()
    if first_line.startswith("#"):
        return "heading"
    if first_line.startswith("!!!") or first_line.startswith("???"):
        return "admonition"
    if first_line.startswith("```") or first_line.startswith("~~~"):
        return "code"
    if first_line.startswith("|"):
        return "table"
    return "paragraph"


def _skip(page, check: str) -> bool:
    raw = page.meta.get("lint_skip") if page.meta else None
    if isinstance(raw, list):
        return check in raw
    return False


def _check_description(page) -> None:
    desc = page.meta.get("description") if page.meta else None
    if not isinstance(desc, str) or not desc.strip():
        raise PluginError(
            f"lint: page '{page.file.src_path}' is missing required frontmatter 'description:'. "
            "Every page must have a description for SEO/GEO."
        )


def _check_first_block(markdown: str, page) -> None:
    if _skip(page, "first_paragraph"):
        return
    kind = _first_block_kind(markdown)
    if kind != "paragraph":
        raise PluginError(
            f"lint: page '{page.file.src_path}' starts with a {kind} instead of a lede paragraph. "
            "Chat agents and search snippets extract from the first paragraph. "
            "Add an introductory paragraph, or opt out with `lint_skip: [first_paragraph]` in frontmatter."
        )


_WEAK_OPENERS = (
    "this page",
    "this document",
    "this section",
    "in this",
    "welcome to",
    "here you'll",
    "here you will",
)


def _first_paragraph(markdown: str) -> str:
    """Extract the first paragraph after an optional leading H1.

    Mirrors `_first_block_kind`'s H1-skipping behavior: this codebase follows
    the `# Title` convention universally, so the warn-only quality check would
    score the H1 text (almost always under 30 words) on every page if we
    didn't skip it.
    """
    stripped = markdown.lstrip("\n")
    if not stripped.strip():
        return ""

    lines = stripped.split("\n")
    idx = 0

    # Skip a single leading H1 (# Title) if present.
    first = lines[idx].lstrip()
    if first.startswith("# ") and not first.startswith("## "):
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines):
            return ""

    paragraph: list[str] = []
    for line in lines[idx:]:
        if not line.strip():
            break
        paragraph.append(line.strip())
    return " ".join(paragraph)


def _check_keywords(page) -> None:
    raw = page.meta.get("keywords") if page.meta else None
    if isinstance(raw, list) and any(str(k).strip() for k in raw):
        return
    if isinstance(raw, str) and raw.strip():
        return
    raise PluginError(
        f"lint: page '{page.file.src_path}' is missing required frontmatter 'keywords:'. "
        "Every page must have at least one keyword for SEO/GEO. "
        "Add a `keywords:` list to the page's frontmatter."
    )


def _check_lede_quality(markdown: str, page) -> None:
    if _skip(page, "first_paragraph"):
        return
    if _first_block_kind(markdown) != "paragraph":
        return  # already hard-failed in _check_first_block; nothing to score
    paragraph = _first_paragraph(markdown)
    word_count = len(paragraph.split())
    if word_count < 30:
        warn_log.warning(
            "page '%s' first paragraph is only %d words — chat agents prefer >=30 word ledes.",
            page.file.src_path,
            word_count,
        )
    lower = paragraph.lower().lstrip()
    if any(lower.startswith(opener) for opener in _WEAK_OPENERS):
        warn_log.warning(
            "page '%s' first paragraph starts with a weak opener ('%s...') — rewrite for extractability.",
            page.file.src_path,
            lower[:30],
        )


def on_page_markdown(markdown, page, config, files):
    _check_description(page)
    _check_first_block(markdown, page)
    _check_keywords(page)
    _check_lede_quality(markdown, page)
    return markdown
