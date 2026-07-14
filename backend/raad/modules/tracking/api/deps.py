"""FastAPI dependency wiring for `tracking` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `TrackingUnitOfWork` and `TrackingApplicationService` — the only place
this module's HTTP layer touches `core.di`; routers never import the container directly
beyond this file, and never construct a repository or touch SQLAlchemy. Mirrors
`fleet_device`/`organization`/`iam.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.services import TrackingApplicationService


def get_tracking_uow(
    container: Container = Depends(get_container),
) -> TrackingUnitOfWork:
    """Resolves a fresh `TrackingUnitOfWork` per call — **not** entered here, for the same
    reason `fleet_device.api.deps.get_fleet_device_uow` isn't: every application-service
    method already manages its own `async with uow:` block (`application/services.py`), so
    wrapping it again here would call `__aenter__`/`__aexit__` twice on the same instance.
    """
    return container.resolve(TrackingUnitOfWork)


def get_tracking_service(
    container: Container = Depends(get_container),
) -> TrackingApplicationService:
    """Raises `LookupError` if `core/di` left `TrackingApplicationService` unbound — it
    requires a `LatestPositionPort` implementation that does not exist yet (`routers.py`'s
    module docstring), the same "fail loudly, don't fake it" policy `get_uow`/`get_scope`
    already document in `interfaces/http/deps.py`."""
    return container.resolve(TrackingApplicationService)
