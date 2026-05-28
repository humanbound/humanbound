"""
Auto-link glossary terms in docs pages to their section in reference/glossary.md.

On first call, parses the glossary file once and builds a {term: anchor} map
plus a compiled regex. For each page (except the glossary itself), finds the
FIRST occurrence of each term in the body and replaces it with a markdown
link whose path is computed relative to the page's source location.

Skips inside:
- Fenced code blocks (``` or ~~~)
- Headings (lines starting with #)
- Inline code spans (`text`)
- Existing markdown links and images
- HTML tags

Match rule: exact case (\\bTerm\\b). "Orchestrator" links; "orchestrator"
does not — avoids over-linking common words. Longest-term-first ordering
so multi-word terms ("Tier 2 Classifier") match before their substrings
("Tier 2").
"""

from __future__ import annotations

import re
from pathlib import Path
from posixpath import dirname, relpath

GLOSSARY_SRC = "reference/glossary.md"

# Module-level cache, populated on first on_page_markdown call.
# Maps term -> anchor (just the slug, e.g. "testing-assessment").
# Per-page link path is computed relative to the page's src_path.
_GLOSSARY: dict[str, str] | None = None
_PATTERN: re.Pattern | None = None


def _slugify(text: str) -> str:
    """Match MkDocs/Markdown default toc.slugify behavior.

    Lowercase, replace non-word chars (keeping dashes) with dash, collapse
    runs of dashes, strip leading/trailing dashes. For "Testing & Assessment"
    this produces "testing-assessment".
    """
    s = text.lower().strip()
    s = re.sub(r"[^\w\-]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _parse_glossary(content: str) -> dict[str, str]:
    """Extract {term: 'reference/glossary.md#section-anchor'} from the glossary.

    Walks the file line by line tracking the current ## section. For each
    table row of the form `| **Term** | definition |`, records the term
    pointing at the current section's slug.
    """
    terms: dict[str, str] = {}
    current_anchor = ""
    row_re = re.compile(r"^\|\s*\*\*([^*]+?)\*\*\s*\|")
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("## "):
            current_anchor = _slugify(s[3:].strip())
            continue
        m = row_re.match(line)
        if m and current_anchor:
            term = m.group(1).strip()
            if term and term not in terms:
                terms[term] = current_anchor
    return terms


def _load_glossary(config) -> dict[str, str]:
    global _GLOSSARY, _PATTERN
    if _GLOSSARY is not None:
        return _GLOSSARY

    glossary_path = Path(config["docs_dir"]) / GLOSSARY_SRC
    if not glossary_path.exists():
        _GLOSSARY = {}
        _PATTERN = re.compile(r"(?!)")  # never matches
        return _GLOSSARY

    _GLOSSARY = _parse_glossary(glossary_path.read_text(encoding="utf-8"))
    if _GLOSSARY:
        # Longest first so "Tier 2 Classifier" matches before "Tier 2".
        terms_sorted = sorted(_GLOSSARY.keys(), key=len, reverse=True)
        escaped = [re.escape(t) for t in terms_sorted]
        _PATTERN = re.compile(r"\b(" + "|".join(escaped) + r")\b")
    else:
        _PATTERN = re.compile(r"(?!)")
    return _GLOSSARY


# Patterns within a text line that the autolink must NOT touch.
_SKIP_PATTERN = re.compile(
    r"`[^`\n]*`"                    # inline code
    r"|!\[[^\]]*\]\([^)]*\)"        # image
    r"|\[[^\]]*\]\([^)]*\)"         # inline link
    r"|\[[^\]]*\]\[[^\]]*\]"        # reference link
    r"|<[^>\n]+>"                   # HTML tag
)


def _glossary_link(page_src_path: str, anchor: str) -> str:
    """Build a markdown link path from the page's source location to the glossary.

    MkDocs resolves relative links in markdown against the page's source-file
    directory. So from `management/collaboration.md`, the link must be
    `../reference/glossary.md` to actually point at `docs/reference/glossary.md`.
    """
    page_dir = dirname(page_src_path)
    rel = relpath(GLOSSARY_SRC, page_dir if page_dir else ".")
    return f"{rel}#{anchor}"


def _replace_in_segment(segment: str, used: set[str], page_src_path: str) -> str:
    """Replace first occurrence of each unused term in a linkable text segment."""
    def sub(m: re.Match) -> str:
        term = m.group(1)
        if term in used:
            return term
        used.add(term)
        link = _glossary_link(page_src_path, _GLOSSARY[term])
        return f"[{term}]({link})"
    return _PATTERN.sub(sub, segment)


def _process_line(line: str, used: set[str], page_src_path: str) -> str:
    """Walk a non-code, non-heading line, skipping inline code / links / HTML."""
    parts: list[str] = []
    pos = 0
    for m in _SKIP_PATTERN.finditer(line):
        gap = line[pos:m.start()]
        parts.append(_replace_in_segment(gap, used, page_src_path))
        parts.append(m.group(0))  # skip-segment passes through unchanged
        pos = m.end()
    parts.append(_replace_in_segment(line[pos:], used, page_src_path))
    return "".join(parts)


def _autolink(markdown: str, page_src_path: str) -> str:
    """Walk markdown line by line, autolinking in linkable contexts only."""
    used: set[str] = set()
    out: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in markdown.split("\n"):
        s = line.lstrip()
        if in_fence:
            out.append(line)
            if s.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            continue
        if s.startswith("```"):
            in_fence, fence_marker = True, "```"
            out.append(line)
            continue
        if s.startswith("~~~"):
            in_fence, fence_marker = True, "~~~"
            out.append(line)
            continue
        if s.startswith("#"):
            out.append(line)  # heading — never autolink
            continue
        out.append(_process_line(line, used, page_src_path))

    return "\n".join(out)


def on_page_markdown(markdown, page, config, files):
    if page.file.src_path == GLOSSARY_SRC:
        return markdown  # don't self-link inside the glossary
    if not _load_glossary(config):
        return markdown
    return _autolink(markdown, page.file.src_path)
