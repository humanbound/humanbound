"""Humanbound SDK exceptions."""


class HumanboundError(Exception):
    """Base exception for Humanbound SDK."""

    pass


class AuthenticationError(HumanboundError):
    """Raised when authentication fails or token is expired."""

    pass


class NotAuthenticatedError(HumanboundError):
    """Raised when trying to make API calls without authentication."""

    pass


class APIError(HumanboundError):
    """Raised when API returns an error response."""

    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class NotFoundError(APIError):
    """Raised when a resource is not found (404)."""

    pass


class ForbiddenError(APIError):
    """Raised when access to a resource is denied (401/403)."""

    pass


class SessionExpiredError(APIError):
    """Raised when the session has been revoked or expired (401 with revocation message)."""

    pass


class RateLimitError(APIError):
    """Raised when rate limit is exceeded (429)."""

    pass


class ValidationError(HumanboundError):
    """Raised when input validation fails."""

    pass


class ConfigurationError(HumanboundError):
    """Raised when SDK configuration is invalid."""

    pass


