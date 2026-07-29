# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound SDK configuration."""

import os
from pathlib import Path

# Default API base URL (can be overridden for on-prem deployments)
DEFAULT_BASE_URL = "https://api.humanbound.ai/api"

# Auth0 configuration for OAuth flow
AUTH0_DOMAIN = "aiandme.eu.auth0.com"
AUTH0_CLIENT_ID = "QZ5RlpOP6jJ9oemarOFkeDal2qKCHAnp"
AUTH0_AUDIENCE = "https://api.aiandme.io/api"

# Token storage location
CONFIG_DIR = Path.home() / ".humanbound"
TOKEN_FILE = CONFIG_DIR / "credentials.json"

# API timeout settings (in seconds)
DEFAULT_TIMEOUT = 30
LONG_TIMEOUT = 120  # For operations like report generation

# PostHog telemetry configuration.
POSTHOG_PUBLIC_KEY = "phc_yKExP2tUyiPGg3kY3tongw36iGLTYaH7D2DfRCHpZg9r"
POSTHOG_HOST = "https://eu.i.posthog.com"


def get_base_url() -> str:
    """Get the API base URL from environment or default."""
    return os.environ.get("HUMANBOUND_BASE_URL", DEFAULT_BASE_URL)


def _env_or_none(name: str) -> str | None:
    """Return the trimmed env value, or None when unset, empty, or whitespace."""
    value = os.environ.get(name, "").strip()
    return value or None


def get_api_key() -> str | None:
    """Get the user API key (hb_… secret) for headless auth, if set.

    When present, the client authenticates via the `x-api-key` header and skips
    the OAuth/credentials flow entirely.
    """
    return _env_or_none("HUMANBOUND_API_KEY")


def get_organisation_id() -> str | None:
    """Org id for headless selection (HUMANBOUND_ORG_ID), if set."""
    return _env_or_none("HUMANBOUND_ORG_ID")


def get_project_id() -> str | None:
    """Project id for headless selection (HUMANBOUND_PROJECT_ID), if set."""
    return _env_or_none("HUMANBOUND_PROJECT_ID")


def get_auth0_domain() -> str:
    """Get Auth0 domain from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_DOMAIN", AUTH0_DOMAIN)


def get_auth0_client_id() -> str:
    """Get Auth0 client ID from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_CLIENT_ID", AUTH0_CLIENT_ID)


def get_auth0_audience() -> str:
    """Get Auth0 audience from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_AUDIENCE", AUTH0_AUDIENCE)


def get_posthog_key() -> str:
    """Get the PostHog project key from environment or default."""
    return os.environ.get("HB_POSTHOG_KEY", POSTHOG_PUBLIC_KEY)


def get_posthog_host() -> str:
    """Get the PostHog ingest host from environment or default."""
    return os.environ.get("HB_POSTHOG_HOST", POSTHOG_HOST)


def get_humanbound_dir() -> Path:
    """Resolve ~/.humanbound at call time so tests can monkeypatch HOME."""
    return Path.home() / ".humanbound"
