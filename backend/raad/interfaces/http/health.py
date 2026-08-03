"""Health / readiness / liveness / metrics endpoints.

Deliberately mounted at the unversioned root (`/health...`, `/metrics`), not under `/api/v1` —
these are infrastructure/orchestrator-facing probes (load balancer health checks,
Kubernetes-style liveness/readiness, a Prometheus scrape target), not part of the versioned
business API contract, so they must stay stable even across a future `/api/v2`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from starlette.responses import JSONResponse

from raad.core.config.settings import get_settings
from raad.core.health.service import HealthCheckService
from raad.core.observability.metrics import MetricsRegistry

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Coarse "is the process up" check."""
    return {"status": "ok"}


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness: the process is running and able to respond at all. No dependency checks —
    an orchestrator restarts the process if this fails."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    """Readiness: the process is actually able to serve traffic (Priority 1 Item 5,
    `PROJECT_STATUS.md`; closes Known Issue #3). Previously confirmed only that `Settings` had
    loaded — never touched the database or Redis, so a broken DB connection or an unreachable
    *configured* Redis still reported "ready", the worst failure mode for a readiness probe.

    The database is treated as mandatory for readiness (unconfigured or unreachable both fail) —
    almost nothing in this platform works without one. Redis/broker are only gating if actually
    configured: an intentionally Redis-less deployment isn't "not ready", but a configured-and-
    unreachable one is (matches every other conditionally-bound Redis port's own "fail loudly,
    don't fake it" policy elsewhere in this codebase).
    """
    get_settings()
    container = getattr(request.app.state, "container", None)
    service = container.try_resolve(HealthCheckService) if container is not None else None
    if service is None:
        # No container at all (e.g. a bare ASGI harness with no lifespan run) - preserves this
        # route's own pre-Item-5 behavior for that edge case rather than a hard 500.
        return JSONResponse(status_code=200, content={"status": "ready", "checks": {}})

    db_status = await service.check_database()
    redis_status = await service.check_redis()
    broker_status = await service.check_broker()

    is_ready = (
        db_status.reachable is True
        and redis_status.reachable is not False
        and broker_status.reachable is not False
    )
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "not_ready",
            "checks": {
                "database": db_status.label,
                "redis": redis_status.label,
                "broker": broker_status.label,
            },
        },
    )


@router.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    """Prometheus text-exposition format (Priority 1 Item 5's "minimum monitoring"). No auth —
    matches every other infrastructure probe on this router; a real deployment restricts
    reachability at the network/reverse-proxy layer (the same posture already relied on for
    `/health*` and, before TLS, for the whole platform generally), not via an application-level
    credential a scraper would need provisioning for."""
    container = getattr(request.app.state, "container", None)
    registry = container.try_resolve(MetricsRegistry) if container is not None else None
    if registry is None:
        return PlainTextResponse("", media_type="text/plain; version=0.0.4")

    service = container.try_resolve(HealthCheckService) if container is not None else None
    dependency_reachable: dict[str, bool | None] = {}
    if service is not None:
        db_status = await service.check_database()
        redis_status = await service.check_redis()
        broker_status = await service.check_broker()
        dependency_reachable = {
            "database": db_status.reachable,
            "redis": redis_status.reachable,
            "broker": broker_status.reachable,
        }

    body = registry.render(dependency_reachable=dependency_reachable)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
