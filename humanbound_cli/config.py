# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Humanbound SDK configuration."""

import os
import tempfile
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


def write_secure_file(path, content: str) -> None:
    """Atomically write ``content`` to ``path`` with owner-only (0600) permissions.

    The file is created via a temporary file in the same directory and then
    atomically ``os.replace``-d into place, so it never exists on disk in a
    partially-written or world-readable state. This closes the brief window in
    which a naive ``write_text`` followed by ``chmod`` leaves a freshly-created
    file at the process umask (typically ``0644`` -> group/world readable).

    File modes are advisory no-ops on Windows, where user-profile ACLs apply
    instead; behaviour there is unchanged.
    """
    path = Path(path)

    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Output directory does not exist: {path.parent}") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            os.chmod(tmp, 0o600)
        except (OSError, NotImplementedError):
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_secure_config_file(path, content: str) -> None:
    """Atomically write ``content`` to ``path`` with owner-only permissions.

    This wrapper also creates the parent directory if it does not exist and
    attempts to set its permissions to 0700. It provides a helpful error
    message if the directory is unwritable (e.g., due to previous sudo runs).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except (OSError, NotImplementedError):
        pass

    try:
        write_secure_file(path, content)
    except PermissionError as e:
        # mkstemp needs write on the parent dir (e.g. a root-owned ~/.humanbound).
        raise PermissionError(
            f"Could not write {path} securely: its directory {path.parent} is not "
            f"writable by the current user (e.g. created by a previous root/`sudo` run). "
            f"Fix ownership with: sudo chown -R $(id -un) {path.parent}"
        ) from e


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
