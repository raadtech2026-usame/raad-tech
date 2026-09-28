"""Global exception handling (Backend LLD §14.2).

A single handler maps the `AppError` hierarchy to the stable error envelope and the HTTP
status table below; it never leaks stack traces or internal identifiers to clients. This is
edge/middleware-layer concern — the domain never imports FastAPI (§3.1).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    RateLimitedError,
    RuleViolationError,
    ValidationError,
)
from raad.core.logging.context import correlation_id_var

logger = logging.getLogger(__name__)

# Ordered most-specific-first; resolve_status walks this list, not a plain dict, so subclass
# lookups (e.g. PaymentError before its parent ExternalServiceError) resolve correctly.
_STATUS_TABLE: list[tuple[type[AppError], int]] = [
    (ValidationError, 422),
    (AuthenticationError, 401),
    (AuthorizationError, 403),
    (NotFoundError, 404),
    (ConflictError, 409),
    (RuleViolationError, 409),
    # Their shared base, and it must stay *below* them so those two keep resolving to 409.
    #
    # A `DomainError` is a business rule refusing caller input — "Category 'Fuel' is an expense
    # category, not an income category", "Fee plan belongs to a different organization",
    # "amount must not be negative". It was absent from this table, so it fell through to the
    # 500 default: the API answered a clear, correct refusal with a server-fault status, which
    # logged it as `unhandled_app_error`, would page an on-call, and told every client the
    # request could be retried unchanged. Live-reproduced against `POST /school-finance/income`.
    (DomainError, 400),
    (PaymentError, 402),
    (RateLimitedError, 429),
    (ExternalServiceError, 502),
    (InfrastructureError, 500),
]


def resolve_status(exc: AppError) -> int:
    for exc_type, status_code in _STATUS_TABLE:
        if isinstance(exc, exc_type):
            return status_code
    return 500


# PostgreSQL SQLSTATEs a constraint can raise, and what each one means to the caller. Anything
# else from `IntegrityError` (a NOT NULL on a column the code should always fill, an exclusion
# constraint) is a genuine server fault and keeps the 500 path.
_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"
_CHECK_VIOLATION = "23514"


def _sqlstate(exc: IntegrityError) -> str | None:
    orig = exc.orig
    state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if state is None and orig is not None:
        state = getattr(orig.__cause__, "sqlstate", None)
    return state


def resolve_integrity_error(exc: IntegrityError) -> tuple[int, str, str] | None:
    """Maps a constraint violation to `(status, code, message)`, or `None` to keep it a 500.

    The message never echoes the constraint or column name: those are schema internals, and
    the caller's remedy is the same either way.
    """
    state = _sqlstate(exc)
    if state == _UNIQUE_VIOLATION:
        return 409, ConflictError.code, (
            "This conflicts with a record that already exists. Reload and try again."
        )
    if state == _FOREIGN_KEY_VIOLATION:
        return 422, ValidationError.code, "The request refers to a record that does not exist."
    if state == _CHECK_VIOLATION:
        return 422, ValidationError.code, "The request breaks a data rule for this record."
    return None


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the global handlers on the given FastAPI app. Called once from
    `main.create_app`."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        status_code = resolve_status(exc)
        correlation_id = correlation_id_var.get()
        if status_code >= 500:
            logger.error(
                "unhandled_app_error",
                extra={"error_code": exc.code, "correlation_id": correlation_id},
                exc_info=exc,
            )
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                correlation_id=correlation_id,
                details=exc.details,
                reason=getattr(exc, "reason", None),
                required_action=getattr(exc, "required_action", None),
            )
        )
        return JSONResponse(status_code=status_code, content=envelope.model_dump())

    @app.exception_handler(StaleDataError)
    async def handle_stale_data(request: Request, exc: StaleDataError) -> JSONResponse:
        """Optimistic-lock loss (`row_version`): another request changed the same row between
        this request's read and its write, and the write was refused.

        It is the loser of a race, not a fault — the Unit of Work has already rolled the whole
        transaction back, so nothing this request did was kept. Before this handler it fell
        through to the 500 default (Known Issue #16), which told the client to retry unchanged
        and paged an on-call; the canonical case is two payments recorded on one Parent Invoice
        at the same moment.
        """
        correlation_id = correlation_id_var.get()
        logger.info("concurrent_modification_refused", extra={"correlation_id": correlation_id})
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=ConflictError.code,
                message=(
                    "This record was changed by another request at the same time. "
                    "Reload it and try again."
                ),
                correlation_id=correlation_id,
            )
        )
        return JSONResponse(status_code=409, content=envelope.model_dump())

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """A database constraint refused the write (Known Issue #16). The constraint did its
        job and the transaction was rolled back; only the status the caller sees changes."""
        correlation_id = correlation_id_var.get()
        mapped = resolve_integrity_error(exc)
        if mapped is None:
            logger.error(
                "unhandled_integrity_error",
                extra={"correlation_id": correlation_id},
                exc_info=exc,
            )
            status_code, code, message = 500, "INTERNAL_ERROR", "An unexpected error occurred."
        else:
            status_code, code, message = mapped
            logger.info(
                "constraint_violation_refused",
                extra={"correlation_id": correlation_id, "sqlstate": _sqlstate(exc)},
            )
        envelope = ErrorEnvelope(
            error=ErrorDetail(code=code, message=message, correlation_id=correlation_id)
        )
        return JSONResponse(status_code=status_code, content=envelope.model_dump())

    @app.exception_handler(Exception)
    async def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = correlation_id_var.get()
        logger.error(
            "unhandled_exception",
            extra={"correlation_id": correlation_id},
            exc_info=exc,
        )
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
                correlation_id=correlation_id,
            )
        )
        return JSONResponse(status_code=500, content=envelope.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Framework-raised errors (route-not-found, method-not-allowed, and any FastAPI/
        Starlette internals that raise HTTPException directly) still come out in the same
        stable envelope as our own AppError hierarchy — §14.2 requires *a single* global
        handler to own the response shape, not just handling for our own exception types.
        Registered against Starlette's base `HTTPException` deliberately: routing failures
        (404/405) raise that base class directly, not FastAPI's subclass, and Starlette
        dispatches by walking the exception's MRO — so binding only the subclass would miss
        them (confirmed by smoke test)."""
        correlation_id = correlation_id_var.get()
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=f"HTTP_{exc.status_code}",
                message=str(exc.detail),
                correlation_id=correlation_id,
            )
        )
        return JSONResponse(status_code=exc.status_code, content=envelope.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic/FastAPI transport-layer validation failures (§15.1) also come out in the
        standard envelope, with field-level detail preserved."""
        correlation_id = correlation_id_var.get()
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=ValidationError("").code,
                message="Request validation failed.",
                correlation_id=correlation_id,
                details=exc.errors(),
            )
        )
        return JSONResponse(status_code=422, content=envelope.model_dump())
