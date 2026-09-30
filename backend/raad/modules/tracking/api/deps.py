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
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_scope
from raad.modules.tracking.application.safety_services import SafetyAlertApplicationService
from raad.modules.tracking.application.services import (
    FleetOverviewApplicationService,
    TrackingApplicationService,
)


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


def get_fleet_overview_service(
    container: Container = Depends(get_container),
) -> FleetOverviewApplicationService:
    """ADR-0031 — raises `LookupError` if unbound (no `settings.db.url`, the same condition
    `PlatformStatsApplicationService`/`MeApplicationService` guard their own binding on in
    `core/di/bootstrap.py`)."""
    return container.resolve(FleetOverviewApplicationService)


def get_scoped_tracking_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> TrackingUnitOfWork:
    """ADR-0055: safety alerts are tenant-owned, so their routes get the caller's scope
    (ADR-0021). Position and geofence routes keep their own policy-guarded, unscoped UoW."""
    uow = container.resolve(TrackingUnitOfWork)
    uow.scope = scope
    return uow


def get_safety_alert_service(
    container: Container = Depends(get_container),
) -> SafetyAlertApplicationService:
    return container.resolve(SafetyAlertApplicationService)


def get_scoped_tracking_uow_fresh(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> TrackingUnitOfWork:
    """A second, independent scoped UoW for routes that need two tracking transactions (a UoW
    cannot be re-entered once exited). FastAPI caches a dependency per request, so the same
    function cannot provide both."""
    uow = container.resolve(TrackingUnitOfWork)
    uow.scope = scope
    return uow
