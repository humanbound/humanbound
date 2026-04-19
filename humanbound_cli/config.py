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



def get_base_url() -> str:
    """Get the API base URL from environment or default."""
    return os.environ.get("HUMANBOUND_BASE_URL", DEFAULT_BASE_URL)


def get_auth0_domain() -> str:
    """Get Auth0 domain from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_DOMAIN", AUTH0_DOMAIN)


def get_auth0_client_id() -> str:
    """Get Auth0 client ID from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_CLIENT_ID", AUTH0_CLIENT_ID)


def get_auth0_audience() -> str:
    """Get Auth0 audience from environment or default."""
    return os.environ.get("HUMANBOUND_AUTH0_AUDIENCE", AUTH0_AUDIENCE)
