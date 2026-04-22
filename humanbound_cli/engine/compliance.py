# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Lightweight compliance overlay for locally-derived scope.

Matches the extracted business_scope against six bundled domain templates
(banking, insurance, healthcare, legal, ecommerce) using keyword detection,
then overlays the template's restricted intents and regulatory citation.
EU AI Act is treated as a cross-cutting overlay.

Deliberately downgraded vs the Platform's /scan endpoint:
- Keyword domain detection (no LLM classification call)
- Single static template per domain (no risk-profile ensemble)
- No regulatory risk scoring, no threat prioritisation with citations
- No compliance framework detection beyond the six bundled templates
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("humanbound.engine.compliance")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "compliance"

# Keyword → domain mapping. First match wins.
_DOMAIN_KEYWORDS = {
    "banking": [
        "bank",
        "banking",
        "retail banking",
        "financial services",
        "account balance",
        "transfer",
        "credit card",
        "debit card",
    ],
    "insurance": [
        "insurance",
        "insurer",
        "policyholder",
        "claims",
        "underwriting",
        "premium",
        "coverage",
    ],
    "healthcare": [
        "health",
        "healthcare",
        "medical",
        "patient",
        "clinic",
        "hospital",
        "diagnosis",
        "prescription",
    ],
    "legal": [
        "legal",
        "law firm",
        "attorney",
        "solicitor",
        "client support",
        "case management",
    ],
    "ecommerce": [
        "e-commerce",
        "ecommerce",
        "online store",
        "retail",
        "shopping",
        "checkout",
        "shipping",
        "order tracking",
    ],
}


def detect_domain(scope: dict) -> str | None:
    """Return the domain slug matching the scope's business_scope text, or None.

    Matches whole keywords against a lowercased version of business_scope plus
    the first few permitted intents. Conservative — returns None when unsure.
    """
    text_parts = [scope.get("overall_business_scope", "")]
    intents = scope.get("intents", {})
    text_parts.extend(intents.get("permitted", [])[:5])
    haystack = " ".join(str(p) for p in text_parts).lower()

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return domain
    return None


def load_template(domain: str) -> dict | None:
    """Load a bundled compliance template by domain slug. Returns None if missing."""
    path = TEMPLATES_DIR / f"{domain}.yaml"
    if not path.exists():
        logger.warning(f"Compliance template not found for domain={domain}")
        return None

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — compliance overlay skipped.")
        return None

    return yaml.safe_load(path.read_text())


def apply_template(scope: dict, domain: str, include_eu_ai_act: bool = True) -> dict:
    """Overlay a compliance template's restricted intents + citation onto scope.

    Non-destructive: returns a new dict. Preserves the LLM-derived
    business_scope and permitted intents. Union of restricted intents
    (dedup preserves order). `more_info` is appended (semicolon-joined).
    """
    template = load_template(domain)
    if not template:
        return scope

    enriched = {
        "overall_business_scope": scope.get("overall_business_scope", ""),
        "intents": {
            "permitted": list(scope.get("intents", {}).get("permitted", [])),
            "restricted": list(scope.get("intents", {}).get("restricted", [])),
        },
        "more_info": scope.get("more_info", ""),
    }

    seen = {r.strip().lower() for r in enriched["intents"]["restricted"]}
    for item in template.get("restricted", []):
        key = item.strip().lower()
        if key not in seen:
            enriched["intents"]["restricted"].append(item)
            seen.add(key)

    template_info = template.get("more_info", "")
    if template_info:
        enriched["more_info"] = (
            f"{enriched['more_info']}; {template_info}" if enriched["more_info"] else template_info
        )

    if include_eu_ai_act:
        enriched = _apply_eu_ai_act(enriched)

    return enriched


def apply_eu_ai_act_only(scope: dict) -> dict:
    """Apply only the EU AI Act cross-cutting overlay, preserving LLM-derived scope."""
    enriched = {
        "overall_business_scope": scope.get("overall_business_scope", ""),
        "intents": {
            "permitted": list(scope.get("intents", {}).get("permitted", [])),
            "restricted": list(scope.get("intents", {}).get("restricted", [])),
        },
        "more_info": scope.get("more_info", ""),
    }
    return _apply_eu_ai_act(enriched)


def _apply_eu_ai_act(scope: dict) -> dict:
    """Overlay the EU AI Act cross-cutting restrictions onto any scope."""
    template = load_template("eu-ai-act")
    if not template:
        return scope

    seen = {r.strip().lower() for r in scope["intents"]["restricted"]}
    for item in template.get("restricted", []):
        key = item.strip().lower()
        if key not in seen:
            scope["intents"]["restricted"].append(item)
            seen.add(key)

    info = template.get("more_info", "")
    if info and info not in scope.get("more_info", ""):
        scope["more_info"] = f"{scope['more_info']}; {info}" if scope.get("more_info") else info

    return scope


def domain_label(domain: str) -> str:
    """Human-readable label for a domain slug, for CLI output."""
    labels = {
        "banking": "Banking & Finance (FCA)",
        "insurance": "Insurance (IDD, Solvency II)",
        "healthcare": "Healthcare (HIPAA)",
        "legal": "Legal Services (SRA, ABA)",
        "ecommerce": "E-Commerce (CRA 2015, FTC Act)",
    }
    return labels.get(domain, domain.title())
