"""Tracking infrastructure layer (Backend LLD §6.2/§7/§8; Database Design §7.1/§7.2) —
Phase 8.3 scope. SQLAlchemy ORM models, ORM↔domain mappers, and the concrete
repositories/UnitOfWork that implement the domain's and application's interfaces. Importing
this package registers `VehiclePositionModel`/`GeofenceCrossingModel` onto
`core.db.base.Base.metadata` — not yet wired into `migrations/env.py` (deliberately deferred
to the dedicated migrations phase, mirroring `fleet_device`'s 7.3 → 7.5 split). No HTTP/
FastAPI, no new business rules — `domain/` and `application/` are unchanged. Public surface of
this package.

Note: the concrete UoW is named `SqlAlchemyTrackingUnitOfWork` (not
`SqlAlchemyTrackingContextUnitOfWork` or similar) to match the module's exact bounded-context
name, consistent with `SqlAlchemyFleetDeviceUnitOfWork`/`SqlAlchemyOrganizationUnitOfWork`/
`SqlAlchemyIamUnitOfWork` (`.claude/rules/naming.md`: modules match bounded-context names
exactly).
"""

from raad.modules.tracking.infra.mappers import (
    geofence_crossing_to_model,
    model_to_geofence_crossing,
    model_to_vehicle_position,
    vehicle_position_to_model,
)
from raad.modules.tracking.infra.models import (
    GeofenceCrossingModel,
    VehiclePositionModel,
)
from raad.modules.tracking.infra.repositories import (
    SqlAlchemyGeofenceCrossingRepository,
    SqlAlchemyTrackingUnitOfWork,
    SqlAlchemyVehiclePositionRepository,
)

__all__ = [
    "GeofenceCrossingModel",
    "SqlAlchemyGeofenceCrossingRepository",
    "SqlAlchemyTrackingUnitOfWork",
    "SqlAlchemyVehiclePositionRepository",
    "VehiclePositionModel",
    "geofence_crossing_to_model",
    "model_to_geofence_crossing",
    "model_to_vehicle_position",
    "vehicle_position_to_model",
]
