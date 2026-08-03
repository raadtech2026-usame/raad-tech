"""Edge middleware (Backend LLD §13.1, §18.2, §16.1): request-id / correlation-id binding,
request logging, JWT-derived security context, security response headers, and the rate-limit
hook seam. No error-envelope logic here — that is the global exception handler in
`core/errors/handlers.py`, registered separately in `main.py`.
"""

from __future__ import annotations

import time
import uuid

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from raad.core.errors.exceptions import RateLimitedError
from raad.core.logging.context import bind_context, reset_context
from raad.core.logging.setup import get_logger
from raad.core.security.login_rate_limiter import LoginRateLimiter
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fills the rate-limit hook seam (§16.1: "request-id, logging, error envelope, rate-limit
    hooks") this class used to be a stub comment for — Priority 1 Item 3 (`PROJECT_STATUS.md`).
    Deliberately scoped to `POST /api/v1/auth/login` only, not a general per-route framework:
    the original stub's "no rate-limit policy (thresholds, per-role/per-route limits) has been
    approved yet" was never resolved into one, and this closes the actual Priority-1 gap
    (unthrottled login) rather than a broader speculative one. Every other route passes through
    untouched.

    Resolves `LoginRateLimiter` via `container.try_resolve(...)`, the same idiom
    `SecurityContextMiddleware` above already uses for `TokenService`: if unbound (no
    `RAAD_REDIS__URL` configured), this logs one warning — at the first request it would have
    rate-limited, not at every request thereafter, and never crashes or blocks the login itself
    — the same "fail loud once, don't cascade-fail the platform over an optional hardening
    layer" posture already established for every other optionally-bound Redis port in this
    codebase. Priority 1 Item 4 (Redis production hardening, next) is what makes Redis reliably
    present so this becomes consistently enforced rather than occasionally absent.
    """

    _LIMITED_PATH = "/api/v1/auth/login"

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._warned_unbound = False
        self._warned_unreachable = False

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method != "POST" or request.url.path != self._LIMITED_PATH:
            return await call_next(request)

        container = getattr(request.app.state, "container", None)
        limiter: LoginRateLimiter | None = (
            container.try_resolve(LoginRateLimiter) if container is not None else None
        )
        if limiter is None:
            if not self._warned_unbound:
                logger.warning(
                    "login_rate_limiter_unbound",
                    extra={
                        "detail": "RAAD_REDIS__URL not configured — /auth/login is not "
                        "rate-limited. Configure Redis (Priority 1 Item 4) to enable this."
                    },
                )
                self._warned_unbound = True
            return await call_next(request)

        client_ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown"
        )
        try:
            allowed = await limiter.is_allowed(client_ip)
        except RedisError:
            # `RAAD_REDIS__URL` is configured (limiter is bound) but the server itself is
            # unreachable/down — a real, live-observed scenario in this environment (Redis
            # is configured but no broker/cache process is actually running), distinct from
            # the `limiter is None` branch above. An optional hardening layer must never take
            # `/auth/login` down with it: log once, not per-request (matches the unbound
            # branch's own rate-limited logging), and fail open.
            if not self._warned_unreachable:
                logger.warning(
                    "login_rate_limiter_unreachable",
                    extra={
                        "detail": "Redis configured but unreachable — /auth/login is "
                        "temporarily not rate-limited."
                    },
                )
                self._warned_unreachable = True
            allowed = True

        if not allowed:
            # Raised, not hand-built into a JSONResponse — propagates to the same global
            # AppError handler (core/errors/handlers.py) every other error already goes
            # through, matching this file's own module docstring ("no error-envelope logic
            # here"). Confirmed safe to raise from within middleware: FastAPI/Starlette's
            # exception-handling machinery wraps the entire user middleware stack, not just
            # route handlers — this middleware runs *after* CorrelationIdMiddleware in the
            # actual request-processing order (see main.create_app's own ordering comment)
            # despite being defined above it in this file, so correlation_id_var is already
            # bound by the time the global handler reads it.
            raise RateLimitedError(
                "Too many login attempts. Please wait before trying again."
            )

        return await call_next(request)
