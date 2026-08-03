"""Exception hierarchy (Backend LLD §14.1).

The domain and application layers raise these — never HTTP-specific exceptions — so the
domain stays framework-free (§3.1, §14.3). `interfaces/http` maps them to the HTTP envelope
(see `handlers.py`); other delivery mechanisms (workers, WebSocket) can map the same
exceptions to their own transport without duplicating the hierarchy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class AppError(Exception):
    """Base of the exception hierarchy. `code` is a stable machine-readable identifier
    returned in the error envelope — never a translated/user-facing string."""

    code: str = "APP_ERROR"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class DomainError(AppError):
    """Invariant violation or illegal state transition, raised by the domain layer."""

    code = "DOMAIN_ERROR"


class ConflictError(DomainError):
    """E.g. vehicle already has an active trip."""

    code = "CONFLICT"


class RuleViolationError(DomainError):
    """E.g. illegal Trip status transition."""

    code = "RULE_VIOLATION"


class ValidationError(AppError):
    """Input failed validation (transport or application layer, §15)."""

    code = "VALIDATION_ERROR"


class AuthenticationError(AppError):
    """Not authenticated."""

    code = "UNAUTHENTICATED"


class AccountLockedError(AuthenticationError):
    """Priority 1 Item 3 (PROJECT_STATUS.md, account lockout) — too many consecutive failed
    login attempts against this account. A deliberate judgment call, not the generic
    `AuthenticationError`: discloses that the account exists and is temporarily locked, rather
    than the same undifferentiated "Invalid credentials." — the same tradeoff `AuthApplication
    Service.login()`'s existing "Account is not active." message already makes (clarity for a
    legitimate locked-out Driver/Parent, judged as a low-severity enumeration risk for this
    platform's actual threat model). Resolves to HTTP 401 automatically (`core/errors/
    handlers.py`'s `_STATUS_TABLE` walks `isinstance`, so this subtype matches the existing
    `AuthenticationError` entry — no table edit needed). `locked_until` rides the base
    `AppError.details` dict — the existing generic mechanism `ValidationError`'s own
    `{"violations": [...]}` already uses — rather than a bespoke envelope field, so
    `handlers.py`'s shared handler needs no change for this one new error type."""

    code = "ACCOUNT_LOCKED"

    def __init__(self, *, locked_until: datetime) -> None:
        super().__init__(
            "Account is temporarily locked due to too many failed login attempts.",
            details={"locked_until": locked_until.isoformat()},
        )


class AuthorizationError(AppError):
    """Authenticated but not permitted (RBAC / scope / policy)."""

    code = "FORBIDDEN"


class ParentAccessDeniedError(AuthorizationError):
    """CR-1 denial (Backend LLD §5.4), raised by `interfaces.http.policy_guards.enforce_cr1`.
    Carries the policy's own `reason`/`required_action` (API Contracts §3.3/§5.2's documented
    `PARENT_ACCESS_DENIED` shape) so a Parent client can distinguish "assignment ended" from
    "renew your subscription" instead of a generic 403."""

    code = "PARENT_ACCESS_DENIED"

    def __init__(self, *, reason: str | None, required_action: str | None) -> None:
        super().__init__(f"Access denied: {reason}")
        self.reason = reason
        self.required_action = required_action


class VideoForbiddenError(AuthorizationError):
    """D5 denial (`.claude/rules/jt1078.md` #1), raised by
    `interfaces.http.policy_guards.enforce_d5` (API Contracts §5.2's documented
    `VIDEO_FORBIDDEN` code). No `reason`/`required_action` taxonomy is documented for video,
    unlike CR-1 — message-only."""

    code = "VIDEO_FORBIDDEN"


class RateLimitedError(AppError):
    """Priority 1 Item 3 (PROJECT_STATUS.md) — `interfaces.http.middleware.RateLimitMiddleware`
    raises this directly from within middleware (not a route/application-layer error) rather
    than constructing the error envelope by hand there; it propagates to the same global
    `AppError` handler (`core/errors/handlers.py`) every other error already goes through —
    correlation-id binding, the standard envelope shape, all for free, no duplicated logic.
    Needs its own `_STATUS_TABLE` entry (429) — unlike `AccountLockedError` above, this isn't a
    subtype of any existing category."""

    code = "RATE_LIMITED"


class NotFoundError(AppError):
    """Aggregate/resource not found within the caller's scope. Also used for cross-tenant
    misses by design — see §14.3 (404-over-403, avoids tenant-existence probing)."""

    code = "NOT_FOUND"


class ExternalServiceError(AppError):
    """FCM / payment / device-plane / maps failure."""

    code = "EXTERNAL_SERVICE_ERROR"


class PaymentError(ExternalServiceError):
    """Provider-specific, mapped from the payment adapter (e.g. EVC Plus)."""

    code = "PAYMENT_ERROR"


class InfrastructureError(AppError):
    """DB / broker / Redis failure."""

    code = "INFRASTRUCTURE_ERROR"
