"""Repository interfaces for the `tracking` module (Backend LLD §5.1/§7.1/§7.2). Framework-
free — no SQLAlchemy/FastAPI/Pydantic; interfaces only, implemented in `infra/repositories.py`
in a later phase.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`,
for the same reason `fleet_device.domain.repositories` doesn't: that module co-locates a
SQLAlchemy-dependent concrete class in the same file, so importing anything from it would
force this domain layer's import graph to require SQLAlchemy (forbidden by LLD §5.3 /
`.claude/rules/backend.md` #2). Tenant scoping is injected automatically at the infra layer
(`.claude/rules/backend.md` #4) — no method here takes an `organization_id` filter parameter.

**`VehiclePositionRepository` is history-only.** Database Design §7.1 states plainly: "Latest
position is NOT read from here" — the current position lives in Redis (Phase 2 §10.3), behind
a different port this phase does not define (it is not a MySQL-backed repository, and no
approved document specifies its exact key/read shape beyond JT808 LLD §14's
`vehicle:{id}:last`). `list_for_trip` backs API Contracts §4.4's `GET /tracking/trips/{id}/
positions` — pagination parameters are an application/API-layer concern layered on top later
(same "domain repos return entities, not pages" stance as `fleet_device`'s interfaces), not
baked into this signature.

`GeofenceCrossingRepository.latest_for_trip` backs the cooldown/duplicate-suppression
pre-check Phase 2 §22.3 describes ("per (trip, stop, event-type)") — the same
repository-guard-plus-DB-constraint pattern `fleet_device`'s one-active-binding invariant
uses, except here the "constraint" side is an application-layer cooldown window, not a unique
index (repeat crossings of the same type are legitimate history rows, not violations).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.value_objects import (
    GeofenceCrossingId,
    GeofenceEventType,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)


class VehiclePositionRepository(ABC):
    @abstractmethod
    async def get(self, position_id: VehiclePositionId) -> VehiclePosition | None:
        raise NotImplementedError

    @abstractmethod
    async def list_for_trip(self, trip_id: TripId) -> list[VehiclePosition]:
        """History for one trip, ordered by `event_time` ascending (Database Design §7.1's
        `ix_vehicle_positions__trip_time (trip_id, event_time)` — including backfilled points,
        re-ordered by their original timestamp rather than ingest order, per
        `.claude/rules/jt808.md` #3)."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_vehicle(self, vehicle_id: VehicleId) -> list[VehiclePosition]:
        """History for one vehicle regardless of trip, ordered by `event_time` ascending
        (Database Design §7.1's `ix_vehicle_positions__veh_time (vehicle_id, event_time)`).
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, position: VehiclePosition) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository
        (LLD §7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def delete_before(self, cutoff: datetime) -> int:
        """Bulk-deletes every row with `event_time < cutoff`; returns the number deleted.
        Backend Stabilization phase addition for the retention-pruning scheduled job
        (`.claude/rules/database.md` #6: "bounded retention window (recommend 90 days,
        configurable)"). A plain bulk `DELETE`, not `PARTITION BY RANGE` + partition-drop —
        `.claude/rules/database.md` #6's own literal mechanism — because `vehicle_positions`
        is not actually partitioned yet (`infra/models.py`'s own docstring already flags this
        as deferred to "a later phase"); implementing real native partitioning now would be a
        larger, riskier schema change than this phase's "prefer minimal changes" instruction
        allows, so this satisfies the underlying *requirement* (bounded, hard-deleted retention)
        via the mechanism already available, flagged as a deviation from the exact documented
        approach rather than silently presented as partition-drop."""
        raise NotImplementedError


class GeofenceCrossingRepository(ABC):
    @abstractmethod
    async def get(self, crossing_id: GeofenceCrossingId) -> GeofenceCrossing | None:
        raise NotImplementedError

    @abstractmethod
    async def list_for_trip(self, trip_id: TripId) -> list[GeofenceCrossing]:
        """Full crossing history for one trip, ordered by `occurred_at` ascending — the read
        side backing `tracking.application.queries.GetGeofenceCrossingsQuery` (Phase 8.2), the
        same "read model over an owned, long-term-retained table" reasoning
        `VehiclePositionRepository.list_for_trip` documents above (Database Design §11.1:
        geofence events are retained long-term)."""
        raise NotImplementedError

    @abstractmethod
    async def latest_for_trip(
        self, trip_id: TripId, *, stop_id: StopId | None, event_type: GeofenceEventType
    ) -> GeofenceCrossing | None:
        """The most recent crossing of the given type for `(trip_id, stop_id)`, or `None`.
        Backs the Phase 2 §22.3 cooldown/duplicate-suppression pre-check — the caller compares
        its `occurred_at` against the configured cooldown window (application layer)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, crossing: GeofenceCrossing) -> None:
        raise NotImplementedError
