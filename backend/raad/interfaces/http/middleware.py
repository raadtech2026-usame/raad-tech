"""Edge middleware (Backend LLD §13.1, §18.2, §16.1): request-id / correlation-id binding,
request logging, JWT-derived security context, security response headers, and the rate-limit
hook seam. No error-envelope logic here — that is the global exception handler in
`core/errors/handlers.py`, registered separately in `main.py`.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from raad.core.logging.context import bind_context, reset_context
from raad.core.logging.setup import get_logger
from raad.core.security.tokens import TokenService, resolve_principal_from_access_token
from raad.core.tenancy.principal import Principal

logger = get_logger("raad.http")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Binds `request_id` (always generated fresh) and `correlation_id` (propagated from an
    inbound `X-Correlation-ID` header when present, e.g. for service-to-service calls;
    otherwise defaults to the request_id) for the lifetime of the request, and echoes both
    back on the response so a client/support engineer can correlate a report to log lines.
    """

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


class SecurityContextMiddleware(BaseHTTPMiddleware):
    """Verifies an inbound `Authorization: Bearer <jwt>` header, if present, and — on success
    — attaches the resulting `Principal` to `request.state.principal` and binds it to the log
    context (§13.1). This middleware never *enforces* authentication: a missing/invalid token
    simply leaves `request.state.principal` unset, since no route requires authentication yet
    (no business endpoints exist). Enforcement is `get_principal` (`interfaces/http/deps.py`),
    which raises `AuthenticationError` if `request.state.principal` was never set — keeping
    "is this token valid" (mechanical, here) separate from "does this route require auth"
    (per-endpoint, at the dependency).

    The actual "raw token string -> `Principal`" resolution is `core.security.tokens.
    resolve_principal_from_access_token` — factored out (Pagination/Filtering/Sorting phase's
    successor, the WebSocket phase) so `/ws/tracking`/`/ws/notifications` authenticate via the
    exact same logic rather than a second copy of it. This middleware itself never runs for a
    WebSocket connection at all (`BaseHTTPMiddleware` only wraps ASGI `http` scope — see that
    function's own docstring), which is precisely why the shared logic had to move somewhere
    both entry points could call.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.principal = None
        container = getattr(request.app.state, "container", None)
        token_service: TokenService | None = (
            container.try_resolve(TokenService) if container is not None else None
        )

        auth_header = request.headers.get("authorization", "")
        if token_service is not None and auth_header.lower().startswith("bearer "):
            raw_token = auth_header[len("bearer ") :].strip()
            request.state.principal = resolve_principal_from_access_token(
                token_service, raw_token
            )

        principal: Principal | None = request.state.principal
        tokens = bind_context(
            principal_id=principal.user_id if principal else None,
            role=principal.role.value if principal else None,
            org_id=principal.org_id if principal else None,
        )
        try:
            return await call_next(request)
        finally:
            reset_context(tokens)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Standard defensive response headers (OWASP secure-headers baseline), independent of any
    authentication decision — applied to every response, including error responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


# Rate-limit hook (§16.1: "request-id, logging, error envelope, rate-limit hooks").
# Not implemented in this phase — no rate-limit policy (thresholds, per-role/per-route
# limits) has been approved yet. When one is, it is added as another BaseHTTPMiddleware here
# and wired in `main.create_app` alongside the two above.
