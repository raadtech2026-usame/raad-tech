"""FastAPI dependency wiring for `video` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `VideoUnitOfWork` and `VideoApplicationService` — the only place this
module's HTTP layer touches `core.di`. Mirrors `billing.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.application.services import VideoApplicationService


def get_video_uow(
    container: Container = Depends(get_container),
) -> VideoUnitOfWork:
    """Resolves a fresh `VideoUnitOfWork` per call — **not** entered here, for the same reason
    `billing.api.deps.get_billing_uow` isn't: every `VideoApplicationService` method already
    manages its own `async with uow:` block(s)."""
    return container.resolve(VideoUnitOfWork)


def get_video_service(
    container: Container = Depends(get_container),
) -> VideoApplicationService:
    return container.resolve(VideoApplicationService)
