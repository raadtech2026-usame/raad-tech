"""Health / readiness / liveness endpoints.

Deliberately mounted at the unversioned root (`/health...`), not under `/api/v1` — these are
infrastructure/orchestrator-facing probes (load balancer health checks, Kubernetes-style
liveness/readiness), not part of the versioned business API contract, so they must stay
stable even across a future `/api/v2`.
"""
from __future__ import annotations

from fastapi import APIRouter

from raad.core.config.settings import get_settings

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
async def readiness() -> dict[str, str]:
    """Readiness: the process is able to serve traffic. Currently confirms settings loaded
    successfully; DB/Redis/broker connectivity checks are added once those clients exist."""
    get_settings()
    return {"status": "ready"}
