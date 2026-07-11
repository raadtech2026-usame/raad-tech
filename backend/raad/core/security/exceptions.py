"""Security-specific exceptions (Backend LLD §14.1, §17 `security`).

Subclasses of the existing `AppError` hierarchy (`core/errors`) rather than a parallel
hierarchy — the global handler already maps `AuthenticationError`/`AuthorizationError` to
401/403 via `isinstance`, so these resolve correctly without touching `core/errors`.
"""

from __future__ import annotations

from raad.core.errors.exceptions import AuthenticationError


class InvalidTokenError(AuthenticationError):
    """Token signature/structure is invalid, or its `token_type` doesn't match what the
    caller expected (e.g. a refresh token presented as an access token)."""

    code = "INVALID_TOKEN"


class TokenExpiredError(AuthenticationError):
    code = "TOKEN_EXPIRED"


class InvalidCredentialsError(AuthenticationError):
    """Reserved for the future login use-case (`modules/iam`) — password mismatch or unknown
    principal. Not raised anywhere in this phase, since no login flow exists yet."""

    code = "INVALID_CREDENTIALS"
