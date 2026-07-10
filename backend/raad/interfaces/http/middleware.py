"""Edge middleware (Backend LLD §13.1, §18.2, §16.1): request-id / correlation-id binding,
request logging, and the rate-limit hook seam. No error-envelope logic here — that is the
global exception handler in `core/errors/handlers.py`, registered separately in `main.py`.
"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from raad.core.logging.context import bind_context, reset_context
from raad.core.logging.setup import get_logger

logger = get_logger("raad.http")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Binds `request_id` (always generated fresh) and `correlation_id` (propagated from an
    inbound `X-Correlation-ID` header when present, e.g. for service-to-service calls;
    otherwise defaults to the request_id) for the lifetime of the request, and echoes both
    back on the response so a client/support engineer can correlate a report to log lines."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get("x-correlation-id", request_id)

        tokens = bind_context(request_id=request_id, correlation_id=correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_context(tokens)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emits one structured log line per completed request (§13.1). Must run *inside*
    `CorrelationIdMiddleware` (added to the app before it, per `main.create_app`) so the
    request/correlation IDs are already bound when this log line is written."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


# Rate-limit hook (§16.1: "request-id, logging, error envelope, rate-limit hooks").
# Not implemented in this phase — no rate-limit policy (thresholds, per-role/per-route
# limits) has been approved yet. When one is, it is added as another BaseHTTPMiddleware here
# and wired in `main.create_app` alongside the two above.
