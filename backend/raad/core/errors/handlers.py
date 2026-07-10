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
from starlette.exceptions import HTTPException as StarletteHTTPException

from raad.core.errors.envelope import ErrorDetail, ErrorEnvelope
from raad.core.errors.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    PaymentError,
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
    (PaymentError, 402),
    (ExternalServiceError, 502),
    (InfrastructureError, 500),
]


def resolve_status(exc: AppError) -> int:
    for exc_type, status_code in _STATUS_TABLE:
        if isinstance(exc, exc_type):
            return status_code
    return 500


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
            )
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
