"""ASGI app factory and composition root wiring (Backend LLD §1). No business logic — this
file only assembles cross-cutting concerns (settings, logging, DI, middleware, error
handling) and mounts the health, `/api/v1`, and WebSocket routers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from raad.core.config.settings import get_settings
from raad.core.di.bootstrap import build_container
from raad.core.errors.handlers import register_exception_handlers
from raad.core.logging.setup import configure_logging, get_logger
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker
from raad.core.workers.lifecycle import WorkerLifecycle
from raad.interfaces.http.api_v1 import api_router
from raad.interfaces.http.health import router as health_router
from raad.interfaces.http.middleware import (
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityContextMiddleware,
    SecurityHeadersMiddleware,
)
from raad.interfaces.http.realtime import (
    BrokerFanOutWorker,
    ConnectionManager,
    build_realtime_broker_consumer,
)
from raad.interfaces.http.ws import ws_router
from raad.modules.notifications.api.ws import build_notifications_fanout_handler
from raad.modules.tracking.api.ws import build_tracking_fanout_handler

logger = get_logger("raad.main")


def _build_realtime_lifecycle(app: FastAPI) -> WorkerLifecycle:
    """Constructs the two realtime fan-out consumers (`interfaces/http/realtime.py`'s own
    module docstring explains why each channel needs its own, distinct from `core/di/
    bootstrap.py`'s `notification-worker`-group `BrokerConsumer`) only when a broker is
    actually configured — the same "don't start a worker with nothing to consume" posture
    `interfaces/workers/bootstrap.py` already applies to the (separate-process) Notification
    Worker. `app.state.tracking_connections`/`notifications_connections` (the `ConnectionManager`
    the two WebSocket routes register/broadcast through) are created unconditionally, just
    below this function's own call site — accepting a connection and letting a client
    subscribe works with no broker at all; only *delivery* needs one, mirroring
    `TrackingApplicationService`'s own "service always constructible, only the one method that
    needs Redis fails loudly" posture applied one layer up."""
    settings = app.state.settings
    container = app.state.container
    clock = container.resolve(Clock)

    workers: list[tuple[Worker, float]] = []
    if settings.broker.url:
        tracking_consumer = build_realtime_broker_consumer(
            broker_url=settings.broker.url, group_name="ws-tracking", clock=clock
        )
        notifications_consumer = build_realtime_broker_consumer(
            broker_url=settings.broker.url, group_name="ws-notifications", clock=clock
        )
        tracking_worker = BrokerFanOutWorker(
            "ws_tracking_fanout",
            clock=clock,
            consumer=tracking_consumer,
            handler=build_tracking_fanout_handler(
                connections=app.state.tracking_connections, container=container
            ),
        )
        notifications_worker = BrokerFanOutWorker(
            "ws_notifications_fanout",
            clock=clock,
            consumer=notifications_consumer,
            handler=build_notifications_fanout_handler(
                connections=app.state.notifications_connections, container=container
            ),
        )
        interval = settings.workers.realtime_fanout_interval_seconds
        workers = [(tracking_worker, interval), (notifications_worker, interval)]
    else:
        logger.info(
            "realtime_fanout_not_started",
            extra={"reason": "no BrokerConsumer bound (RAAD_BROKER__URL not configured)"},
        )
    return WorkerLifecycle(workers)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate settings (fail fast), configure logging, build the DI composition
    root, create the two WebSocket `ConnectionManager`s, and start the realtime fan-out
    workers (WebSocket phase) whenever a broker is configured. Shutdown: stop the realtime
    workers, then dispose the DB engine's connection pool if one was bound (`db.url`
    configured)."""
    settings = get_settings()
    settings.validate_on_startup()
    configure_logging(settings.observability)

    app.state.settings = settings
    app.state.container = build_container(settings)
    app.state.tracking_connections = ConnectionManager()
    app.state.notifications_connections = ConnectionManager()

    realtime_lifecycle = _build_realtime_lifecycle(app)
    app.state.realtime_lifecycle = realtime_lifecycle
    await realtime_lifecycle.start_all()

    logger.info(
        "raad_business_api_startup", extra={"environment": settings.environment.value}
    )
    yield

    await realtime_lifecycle.stop_all()

    engine = app.state.container.try_resolve(AsyncEngine)
    if engine is not None:
        await engine.dispose()
    logger.info("raad_business_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RAAD Business API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware order matters: Starlette runs the *last-added* middleware outermost, i.e.
    # first on the way in. Added innermost-first: RequestLoggingMiddleware must run innermost
    # so CorrelationIdMiddleware's and SecurityContextMiddleware's bound context (request/
    # correlation IDs, principal) is already set when the request-completed log line is
    # written; SecurityHeadersMiddleware is outermost of those four so it stamps every
    # response, including ones produced by the global exception handlers. CORSMiddleware is
    # added last of all (truly outermost) — a preflight `OPTIONS` request carries no
    # `Authorization` header, so it must be answered before `SecurityContextMiddleware` (or
    # any other layer) ever runs, and every response (success or error) needs the CORS headers
    # stamped on it for the browser to expose it to the calling frontend at all.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityContextMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(ws_router)  # /ws/tracking, /ws/notifications — see that router's own
    # module docstring for why these are mounted outside /api/v1.

    return app


app = create_app()
