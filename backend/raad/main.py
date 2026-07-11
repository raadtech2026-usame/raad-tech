"""ASGI app factory and composition root wiring (Backend LLD §1). No business logic — this
file only assembles cross-cutting concerns (settings, logging, DI, middleware, error
handling) and mounts the health and `/api/v1` routers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from raad.core.config.settings import get_settings
from raad.core.di.bootstrap import build_container
from raad.core.errors.handlers import register_exception_handlers
from raad.core.logging.setup import configure_logging, get_logger
from raad.interfaces.http.api_v1 import api_router
from raad.interfaces.http.health import router as health_router
from raad.interfaces.http.middleware import (
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityContextMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger("raad.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate settings (fail fast), configure logging, build the DI composition
    root. Shutdown: log only — there are no live connections (DB engine, broker, Redis) to
    close yet in this phase."""
    settings = get_settings()
    settings.validate_on_startup()
    configure_logging(settings.observability)

    app.state.settings = settings
    app.state.container = build_container(settings)

    logger.info(
        "raad_business_api_startup", extra={"environment": settings.environment.value}
    )
    yield
    logger.info("raad_business_api_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAAD Business API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware order matters: Starlette runs the *last-added* middleware outermost, i.e.
    # first on the way in. Added innermost-first: RequestLoggingMiddleware must run innermost
    # so CorrelationIdMiddleware's and SecurityContextMiddleware's bound context (request/
    # correlation IDs, principal) is already set when the request-completed log line is
    # written; SecurityHeadersMiddleware is outermost so it stamps every response, including
    # ones produced by the global exception handlers.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityContextMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
