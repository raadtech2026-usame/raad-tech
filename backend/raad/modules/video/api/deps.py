"""FastAPI dependency wiring for `video` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `VideoUnitOfWork` and `VideoApplicationService` — the only place this
module's HTTP layer touches `core.di`. Mirrors `billing.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.application.services import VideoApplicationService


def get_video_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> VideoUnitOfWork:
    """Resolves a fresh `VideoUnitOfWork` per call — **not** entered here, for the same reason
    `billing.api.deps.get_billing_uow` isn't: every `VideoApplicationService` method already
    manages its own `async with uow:` block(s).

    **ADR-0021, closing a real gap (focused D5 review, 2026-08-13):** `scope` is resolved here
    (the caller's real `TenantRegionScope`) and set on the UoW *before* it's entered, mirroring
    `transport_ops.api.deps.get_transport_ops_uow`/`fleet_device.api.deps.get_fleet_device_uow`
    exactly — this module previously never did this, so `SqlAlchemyVideoSessionRepository.get`
    was unconditionally unrestricted regardless of caller. `POST /video/sessions/{id}/stop`
    (`api/routers.py`) is the one route that actually depends on this: it resolves an existing
    `VideoSession` by a client-supplied `session_id` *before* `enforce_d5` ever runs, so a
    session belonging to another organization must 404 there — the same non-disclosure
    `/video/live`/`/video/playback` already get for free via `fleet_device`'s own tenant-scoped
    device lookup."""
    uow = container.resolve(VideoUnitOfWork)
    uow.scope = scope
    return uow


def get_video_service(
    container: Container = Depends(get_container),
) -> VideoApplicationService:
    return container.resolve(VideoApplicationService)
