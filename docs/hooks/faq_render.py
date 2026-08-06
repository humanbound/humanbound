"""
Render visible FAQ accordions from page frontmatter at a `<!-- faq -->` marker.

Google's FAQ rich-results policy requires the JSON-LD FAQPage content to be
visibly present on the page. Schema.py emits the JSON-LD whenever `faq:` is
in frontmatter; this hook makes the same content visible.

Author workflow:
  1. Add `faq:` to page frontmatter (list of `{q, a}` dicts).
  2. Drop `<!-- faq -->` wherever the visible accordion should appear.

If the marker is present but `faq:` is missing or empty, the marker is
removed and a warning is logged. If the marker is absent, the hook is a
no-op — JSON-LD still emits but no visible block is rendered (this leaves
the page in a Google rich-results-disqualifying state; that's by design,
so authors opt in to visibility explicitly).
"""

from __future__ import annotations

import logging

FAQ_MARKER = "<!-- faq -->"

# Stdlib logger, not the MkDocs plugin logger, so warnings don't escalate
# under `strict: true`. Matches the pattern in lint.py.
warn_log = logging.getLogger("docs.faq_render")
if not warn_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s - docs.faq_render: %(message)s"))
    warn_log.addHandler(_handler)
    warn_log.setLevel(logging.WARNING)
    warn_log.propagate = False


def _normalize_faq_items(raw, src_path: str) -> list[dict]:
    """Filter the page's `faq:` frontmatter to valid {q, a} dicts.

    Mirrors schema.py's build_faqpage filtering so the visible block matches
    the JSON-LD exactly (Google requires this).
    """
    if not isinstance(raw, list):
        return []
    items: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            warn_log.warning("faq item is not a mapping on %s: %r", src_path, item)
            continue
        q = item.get("q")
        a = item.get("a")
        if not q or not a:
            warn_log.warning("faq item missing q/a on %s: %r", src_path, item)
            continue
        items.append({"q": str(q).strip(), "a": str(a).strip()})
    return items


def _render_faq_block(items: list[dict]) -> str:
    """Render FAQ items as a Material `???` collapsible admonition block.

    Each item becomes a `??? question "Q text"` block with the answer
    indented 4 spaces (Material's admonition syntax).
    """
    lines: list[str] = ["", "## Frequently asked questions", ""]
    for item in items:
        q = item["q"].replace('"', '\\"')  # escape quotes for the admonition title
        lines.append(f'??? question "{q}"')
        # Indent answer body 4 spaces per Material admonition syntax.
        # Multi-line answers split on \n and each line indented.
        for answer_line in item["a"].splitlines() or [""]:
            lines.append(f"    {answer_line}")
        lines.append("")
    return "\n".join(lines)


def on_page_markdown(markdown, page, config, files):
    if FAQ_MARKER not in markdown:
        return markdown

    raw_faq = page.meta.get("faq") if page.meta else None
    items = _normalize_faq_items(raw_faq, page.file.src_path)

    if not items:
        warn_log.warning(
            "page '%s' has %s marker but no valid faq: frontmatter — removing marker.",
            page.file.src_path,
            FAQ_MARKER,
        )
        return markdown.replace(FAQ_MARKER, "")

    block = _render_faq_block(items)
    return markdown.replace(FAQ_MARKER, block)
