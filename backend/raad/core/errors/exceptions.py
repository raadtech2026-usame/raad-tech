"""Exception hierarchy (Backend LLD §14.1).

The domain and application layers raise these — never HTTP-specific exceptions — so the
domain stays framework-free (§3.1, §14.3). `interfaces/http` maps them to the HTTP envelope
(see `handlers.py`); other delivery mechanisms (workers, WebSocket) can map the same
exceptions to their own transport without duplicating the hierarchy.
"""

from __future__ import annotations

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
