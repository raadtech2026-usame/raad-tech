"""SQLAlchemy repository implementations for `tracking` (Backend LLD §7, §8; Database Design
§7.1/§7.2). Compose `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — repositories never
return an ORM model, only the domain entities `modules/tracking/domain/repositories.py`
declares (§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves** — identical to
`fleet_device`/`organization`/`iam`'s own docstrings: because `get()`/`list_for_*()` return
plain domain objects (not the tracked ORM rows), a handler that mutated one in place would
never touch SQLAlchemy's dirty-tracking. Neither `VehiclePosition` nor `GeofenceCrossing` has
a mutation method today (Phase 8.1), so `flush_tracked_changes()` is a no-op in every use-case
this phase actually exercises — implemented anyway, uniformly, for the same reason
`mappers.py`'s `existing=` parameter is (see that module's docstring).

`SqlAlchemyRepositoryBase.get_by_id`'s soft-delete filter (`hasattr(self.model,
"deleted_at")`) is inert for both models here — neither carries a `deleted_at` column
(`models.py`'s module docstring) — so no special-casing is needed, the same way
`fleet_device.infra.repositories` notes for `DeviceAssignmentModel`.

**Tenant-scoping note (pre-existing gap, consistent with every module so far):** repository
queries do not yet apply the automatic tenant filter — `core.tenancy`'s `ScopeResolver` is
still pending (see `fleet_device.infra.repositories`'s identical note).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.repositories import (
    GeofenceCrossingRepository,
    VehiclePositionRepository,
)
from raad.modules.tracking.domain.value_objects import (
    GeofenceCrossingId,
    GeofenceEventType,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)
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


class SqlAlchemyVehiclePositionRepository(
    SqlAlchemyRepositoryBase[VehiclePositionModel], VehiclePositionRepository
):
    model = VehiclePositionModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[VehiclePosition, VehiclePositionModel]] = {}

    async def get(self, position_id: VehiclePositionId) -> VehiclePosition | None:
        row = await self.get_by_id(str(position_id))
        return self._track(row)

    async def list_for_trip(self, trip_id: TripId) -> list[VehiclePosition]:
        statement = (
            select(VehiclePositionModel)
            .where(VehiclePositionModel.trip_id == str(trip_id))
            .order_by(VehiclePositionModel.event_time.asc())
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]  # type: ignore[misc]

    async def list_for_vehicle(self, vehicle_id: VehicleId) -> list[VehiclePosition]:
        statement = (
            select(VehiclePositionModel)
            .where(VehiclePositionModel.vehicle_id == str(vehicle_id))
            .order_by(VehiclePositionModel.event_time.asc())
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]  # type: ignore[misc]

    def add(self, position: VehiclePosition) -> None:
        model = vehicle_position_to_model(position)
        super().add(model)
        self._tracked[str(position.id)] = (position, model)

    async def delete_before(self, cutoff: datetime) -> int:
        statement = delete(VehiclePositionModel).where(
            VehiclePositionModel.event_time < cutoff
        )
        result = await self._session.execute(statement)
        return result.rowcount or 0

    def flush_tracked_changes(self) -> None:
        for position, model in self._tracked.values():
            vehicle_position_to_model(position, existing=model)

    def _track(self, row: VehiclePositionModel | None) -> VehiclePosition | None:
        if row is None:
            return None
        position = model_to_vehicle_position(row)
        self._tracked[row.id] = (position, row)
        return position


class SqlAlchemyGeofenceCrossingRepository(
    SqlAlchemyRepositoryBase[GeofenceCrossingModel], GeofenceCrossingRepository
):
    model = GeofenceCrossingModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[GeofenceCrossing, GeofenceCrossingModel]] = {}

    async def get(self, crossing_id: GeofenceCrossingId) -> GeofenceCrossing | None:
        row = await self.get_by_id(str(crossing_id))
        return self._track(row)

    async def list_for_trip(self, trip_id: TripId) -> list[GeofenceCrossing]:
        statement = (
            select(GeofenceCrossingModel)
            .where(GeofenceCrossingModel.trip_id == str(trip_id))
            .order_by(GeofenceCrossingModel.occurred_at.asc())
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]  # type: ignore[misc]

    async def latest_for_trip(
        self, trip_id: TripId, *, stop_id: StopId | None, event_type: GeofenceEventType
    ) -> GeofenceCrossing | None:
        statement = (
            select(GeofenceCrossingModel)
            .where(
                GeofenceCrossingModel.trip_id == str(trip_id),
                GeofenceCrossingModel.stop_id
                == (str(stop_id) if stop_id is not None else None),
                GeofenceCrossingModel.event_type == event_type.value,
            )
            .order_by(GeofenceCrossingModel.occurred_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, crossing: GeofenceCrossing) -> None:
        model = geofence_crossing_to_model(crossing)
        super().add(model)
        self._tracked[str(crossing.id)] = (crossing, model)

    def flush_tracked_changes(self) -> None:
        for crossing, model in self._tracked.values():
            geofence_crossing_to_model(crossing, existing=model)

    def _track(self, row: GeofenceCrossingModel | None) -> GeofenceCrossing | None:
        if row is None:
            return None
        crossing = model_to_geofence_crossing(row)
        self._tracked[row.id] = (crossing, row)
        return crossing


class SqlAlchemyTrackingUnitOfWork(SqlAlchemyUnitOfWork, TrackingUnitOfWork):
    """Concrete `TrackingUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `tracking`'s two
    repositories once the session is open, and re-syncs every tracked entity's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above — a no-op today, see this
    module's docstring) immediately before delegating to `SqlAlchemyUnitOfWork.commit()`,
    which still owns the actual outbox-write + session-commit behavior, preserved exactly
    (§8.3), via `super().commit()`. Identical shape to
    `SqlAlchemyFleetDeviceUnitOfWork`/`SqlAlchemyOrganizationUnitOfWork`/
    `SqlAlchemyIamUnitOfWork`.
    """

    vehicle_positions: SqlAlchemyVehiclePositionRepository
    geofence_crossings: SqlAlchemyGeofenceCrossingRepository

    async def __aenter__(self) -> "SqlAlchemyTrackingUnitOfWork":
        await super().__aenter__()
        self.vehicle_positions = SqlAlchemyVehiclePositionRepository(self.session)
        self.geofence_crossings = SqlAlchemyGeofenceCrossingRepository(self.session)
        return self

    async def commit(self) -> None:
        self.vehicle_positions.flush_tracked_changes()
        self.geofence_crossings.flush_tracked_changes()
        await super().commit()
