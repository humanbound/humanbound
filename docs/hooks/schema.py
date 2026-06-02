"""
Schema.org JSON-LD emitter.

Computes a JSON-LD @graph per page and attaches it to page.meta as a
serialized string. The template (overrides/main.html) renders the string
inside a single <script type="application/ld+json"> tag.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from functools import cache

from mkdocs.plugins import get_plugin_logger

log = get_plugin_logger(__name__)

# Canonical @id URIs. Sitewide IDs use `<site>/#fragment` per JSON-LD convention.
ORG_ID = "https://humanbound.ai/#org"
PRODUCT_ID = "https://humanbound.ai/#product"
DOCS_WEBSITE_ID = "https://docs.humanbound.ai/#website"

# Fallback for pages with no git history (untracked / brand-new local files).
# Production dates come from git via _git_iso_date below.
BUILD_TIME_ISO = datetime.now(timezone.utc).isoformat(timespec="seconds")


@cache
def _git_iso_date(abs_path: str) -> str | None:
    """Last-commit ISO 8601 date for a file. None if untracked or git unavailable.

    Requires full git history on the checkout (CI must use fetch-depth: 0).
    Cached per process so mkdocs serve reloads stay fast.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", abs_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    return result.stdout.strip() or None


def build_organization() -> dict:
    """Minimal Organization reference stub. Full identity lives on humanbound.ai."""
    return {
        "@type": "Organization",
        "@id": ORG_ID,
        "name": "Humanbound",
        "url": "https://humanbound.ai",
    }


def build_website(config) -> dict:
    """WebSite entity for the docs subdomain."""
    return {
        "@type": "WebSite",
        "@id": DOCS_WEBSITE_ID,
        "url": config.site_url.rstrip("/"),
        "name": "Humanbound Docs",
        "description": config.site_description,
        "publisher": {"@id": ORG_ID},
        "inLanguage": "en",
    }


def build_techarticle(page, config) -> dict:
    """Per-page TechArticle. Always emitted (uniform type for all docs pages)."""
    canonical = page.canonical_url
    if not canonical:
        raise RuntimeError(f"schema hook: page.canonical_url is empty for {page.file.src_path}")

    description = page.meta.get("description") or config.site_description
    headline = page.meta.get("title") or page.title

    article: dict = {
        "@type": "TechArticle",
        "@id": f"{canonical}#article",
        "headline": headline,
        "description": description,
        "url": canonical,
        "isPartOf": {"@id": DOCS_WEBSITE_ID},
        "about": {"@id": PRODUCT_ID},
        "publisher": {"@id": ORG_ID},
        "inLanguage": "en",
        "dateModified": _git_iso_date(page.file.abs_src_path) or BUILD_TIME_ISO,
    }

    keywords = _normalize_keywords(page.meta.get("keywords"))
    if keywords:
        article["keywords"] = keywords

    author = _build_author(page.meta.get("author"))
    if author:
        article["author"] = author

    same_as = _normalize_same_as(page.meta.get("sameAs"))
    if same_as:
        article["sameAs"] = same_as

    return article


def _normalize_keywords(raw) -> str | None:
    """Accept list-of-strings or comma-separated string; emit comma-separated string."""
    if isinstance(raw, list):
        cleaned = [str(k).strip() for k in raw if str(k).strip()]
        return ", ".join(cleaned) if cleaned else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _build_author(raw) -> dict | list[dict] | None:
    """Accept a string (name only), dict (name + optional url), or list of either."""
    if raw is None:
        return None
    if isinstance(raw, list):
        authors = [_build_author(item) for item in raw]
        authors = [a for a in authors if a]
        if not authors:
            return None
        return authors if len(authors) > 1 else authors[0]
    if isinstance(raw, str) and raw.strip():
        return {"@type": "Person", "name": raw.strip()}
    if isinstance(raw, dict) and raw.get("name"):
        person: dict = {"@type": "Person", "name": str(raw["name"]).strip()}
        if raw.get("url"):
            person["url"] = str(raw["url"]).strip()
        return person
    return None


def _normalize_same_as(raw) -> list[str] | None:
    """Accept list of URLs or single URL string; emit list of URLs."""
    if isinstance(raw, list):
        cleaned = [str(u).strip() for u in raw if str(u).strip()]
        return cleaned or None
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return None


def build_breadcrumb(page, config) -> dict:
    """BreadcrumbList derived from page.ancestors (nearest-first; we reverse).

    Skips nav-only section headers that have no URL. Google requires `item` on
    every ListItem except the last, so a URL-less entry breaks rich-result
    eligibility for the whole breadcrumb.
    """
    site_url = config.site_url.rstrip("/")

    entries: list[dict] = [{"name": "Home", "item": site_url}]

    # page.ancestors is nearest-first; reverse for root → leaf order.
    for ancestor in reversed(list(page.ancestors)):
        ancestor_url = getattr(ancestor, "canonical_url", None) or getattr(ancestor, "url", None)
        if not ancestor_url:
            continue
        if ancestor_url.startswith("http"):
            absolute = ancestor_url
        else:
            absolute = f"{site_url}/{ancestor_url.lstrip('/')}"
        entries.append({"name": ancestor.title, "item": absolute})

    entries.append({"name": page.title, "item": page.canonical_url})

    return {
        "@type": "BreadcrumbList",
        "@id": f"{page.canonical_url}#breadcrumb",
        "itemListElement": [
            {"@type": "ListItem", "position": i, **entry}
            for i, entry in enumerate(entries, start=1)
        ],
    }


def build_faqpage(page) -> dict | None:
    """FAQPage from page.meta['faq']. Returns None when no valid items remain."""
    raw = page.meta.get("faq")
    if not isinstance(raw, list) or not raw:
        return None

    main_entity: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            log.warning(
                "schema hook: faq item is not a mapping on %s: %r",
                page.file.src_path,
                item,
            )
            continue
        q = item.get("q")
        a = item.get("a")
        if not q or not a:
            log.warning(
                "schema hook: faq item missing q/a on %s: %r",
                page.file.src_path,
                item,
            )
            continue
        main_entity.append(
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
        )

    if not main_entity:
        return None

    return {
        "@type": "FAQPage",
        "@id": f"{page.canonical_url}#faq",
        "isPartOf": {"@id": f"{page.canonical_url}#article"},
        "mainEntity": main_entity,
    }


def on_page_context(context, page, config, nav):
    """MkDocs lifecycle hook: build the JSON-LD graph and attach it to page.meta."""
    graph = [
        build_organization(),
        build_website(config),
    ]
    if page.ancestors:
        graph.append(build_breadcrumb(page, config))
    graph.append(build_techarticle(page, config))

    faqpage = build_faqpage(page)
    if faqpage:
        graph.append(faqpage)

    page.meta["schema_jsonld"] = json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        separators=(",", ":"),
        default=str,
    )
    return context
