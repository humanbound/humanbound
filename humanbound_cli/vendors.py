# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""CLI vendor registry — the credential-field spec per hosted-platform vendor.

Mirrors the backend ``VENDOR_REGISTRY`` / ``VENDOR_CREDENTIAL_MODELS``. Adding a
vendor here (id -> label + credential fields) is all the CLI needs; the command,
discovery call, picker, connector build, and onboarding flow are vendor-agnostic.
"""

# Each credential field: name (payload key), label (prompt text), secret (hide
# input + mask), env (de-facto env var candidates, first set one wins).
VENDORS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI",
        "credentials": [
            {
                "name": "api_key",
                "label": "OpenAI API key",
                "secret": True,
                "env": ["OPENAI_API_KEY"],
            },
        ],
    },
}


def ids() -> list[str]:
    """Return the known vendor ids (sorted) — for ``click.Choice``."""
    return sorted(VENDORS)


def get(vendor: str) -> dict:
    """Return the vendor spec; raise ``KeyError`` for an unknown id."""
    return VENDORS[vendor]
