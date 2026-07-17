"""Exception hierarchy, HTTP mapping, and the standard error envelope (Backend LLD §14)."""

from raad.core.errors.envelope import ErrorDetail, ErrorEnvelope
from raad.core.errors.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    PaymentError,
    RuleViolationError,
    ValidationError,
)
from raad.core.errors.handlers import register_exception_handlers, resolve_status

__all__ = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "DomainError",
    "ErrorDetail",
    "ErrorEnvelope",
    "ExternalServiceError",
    "InfrastructureError",
    "NotFoundError",
    "PaymentError",
    "RuleViolationError",
    "ValidationError",
    "register_exception_handlers",
    "resolve_status",
]
