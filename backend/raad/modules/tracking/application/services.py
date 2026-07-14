"""Tracking application services (Backend LLD §4.1/§4.3). Thin, orchestration-only handlers —
business rules stay inside the `VehiclePosition`/`GeofenceCrossing` entities and the
`GeofenceEvaluationService` domain service (`modules/tracking/domain`); these services only:
resolve/validate pre-conditions, load/create entities via the repositories bound to
`TrackingUnitOfWork`, invoke domain behavior, record the resulting `DomainEvent`s, commit, and
return a DTO — the exact skeleton the LLD's §4.3 "transaction & event ordering" steps
describe, identical to `fleet_device`/`organization`/`iam`'s services.

One service, `TrackingApplicationService`, covers every use case — unlike `fleet_device`'s
split-by-API-grouping (`/vehicles` + `/devices`), `.claude/rules/api.md` #2 maps this whole
module to a single grouping (`/tracking` + `/ws/tracking`), so there is no natural second
service boundary.

**`evaluate_geofence` is the one non-`async`, no-`uow` method here.** `EvaluateGeofenceCommand`
performs no I/O — it is a thin pass-through to `GeofenceEvaluationService`'s pure primitives
(Phase 8.1) — so giving it an `async def` signature or a `uow` parameter would be dishonest
about what the method actually does; every other method here does real I/O and stays `async`.

**`TrackingVisibilityPolicy` (Phase 8.1) is deliberately not invoked from any read method
here.** Phase 2 §23.3's four dimensions (capability/scope/ownership/time-window) each need
data this module doesn't own or hasn't been given a port for yet (RBAC, `organization`'s
region scope, `transport_ops`'s student/trip ownership) — evaluating the policy belongs to
whichever future API-layer dependency resolves those four inputs and calls
`TrackingVisibilityPolicy().evaluate(...)`, the same way `fleet_device`'s API layer defers to
a "pending-RBAC-matrix" authorization dependency rather than the application service. This
phase's queries return data for an already-authorized caller.
"""

from __future__ import annotations

from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.tracking.application.commands import (
    EvaluateGeofenceCommand,
    RecordBackfillPositionCommand,
    RecordGeofenceCrossingCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import (
    LatestPositionPort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.queries import (
    GeofenceCrossingDTO,
    GeofenceEvaluationResultDTO,
    GetCurrentVehiclePositionQuery,
    GetGeofenceCrossingsQuery,
    GetVehiclePositionHistoryQuery,
    VehiclePositionDTO,
    geofence_crossing_to_dto,
    vehicle_position_to_dto,
)
from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.services import GeofenceEvaluationService
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)


class TrackingApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        latest_position_port: LatestPositionPort,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._latest_position_port = latest_position_port

    # --- Position ingestion -------------------------------------------------------------

    async def record_vehicle_position(
        self, command: RecordVehiclePositionCommand, *, uow: TrackingUnitOfWork
    ) -> VehiclePositionDTO:
        async with uow:
            position = self._build_position(command, is_backfill=False)
            uow.vehicle_positions.add(position)
            await uow.commit()
            return vehicle_position_to_dto(position)

    async def record_backfill_position(
        self, command: RecordBackfillPositionCommand, *, uow: TrackingUnitOfWork
    ) -> VehiclePositionDTO:
        async with uow:
            position = self._build_position(command, is_backfill=True)
            uow.vehicle_positions.add(position)
            await uow.commit()
            return vehicle_position_to_dto(position)

    def _build_position(
        self,
        command: RecordVehiclePositionCommand | RecordBackfillPositionCommand,
        *,
        is_backfill: bool,
    ) -> VehiclePosition:
        return VehiclePosition.record(
            id=VehiclePositionId(self._id_generator.new_id()),
            organization_id=OrganizationId(command.organization_id),
            vehicle_id=VehicleId(command.vehicle_id),
            device_id=DeviceId(command.device_id),
            trip_id=TripId(command.trip_id) if command.trip_id is not None else None,
            position=GeoPoint(latitude=command.latitude, longitude=command.longitude),
            event_time=command.event_time,
            clock=self._clock,
            speed_kph=(
                SpeedKph(command.speed_kph) if command.speed_kph is not None else None
            ),
            heading_deg=(
                HeadingDegrees(command.heading_deg)
                if command.heading_deg is not None
                else None
            ),
            alarm_flags=(
                AlarmFlags(command.alarm_flags)
                if command.alarm_flags is not None
                else None
            ),
            is_backfill=is_backfill,
        )

    # --- Geofence evaluation & recording -------------------------------------------------

    def evaluate_geofence(
        self, command: EvaluateGeofenceCommand
    ) -> GeofenceEvaluationResultDTO:
        """No I/O — see class docstring. Pure pass-through to
        `GeofenceEvaluationService` (Phase 8.1)."""
        position = GeoPoint(
            latitude=command.position_latitude, longitude=command.position_longitude
        )
        center = GeoPoint(
            latitude=command.center_latitude, longitude=command.center_longitude
        )
        distance_m = GeofenceEvaluationService.distance_m(position, center)
        is_inside = GeofenceEvaluationService.is_within_radius(
            position=position, center=center, radius_m=command.radius_m
        )
        transition = GeofenceEvaluationService.detect_transition(
            was_inside=command.was_inside, is_inside=is_inside
        )
        return GeofenceEvaluationResultDTO(
            is_inside=is_inside, distance_m=distance_m, transition=transition.value
        )

    async def record_geofence_crossing(
        self, command: RecordGeofenceCrossingCommand, *, uow: TrackingUnitOfWork
    ) -> GeofenceCrossingDTO:
        async with uow:
            crossing_id = GeofenceCrossingId(self._id_generator.new_id())
            organization_id = OrganizationId(command.organization_id)
            trip_id = TripId(command.trip_id)
            stop_id = StopId(command.stop_id) if command.stop_id is not None else None

            if command.event_type == GeofenceEventType.APPROACHING_STOP:
                crossing = GeofenceCrossing.approaching_stop(
                    id=crossing_id,
                    organization_id=organization_id,
                    trip_id=trip_id,
                    stop_id=stop_id,  # type: ignore[arg-type]
                    clock=self._clock,
                )
            elif command.event_type == GeofenceEventType.ENTERED_STOP:
                crossing = GeofenceCrossing.entered_stop(
                    id=crossing_id,
                    organization_id=organization_id,
                    trip_id=trip_id,
                    stop_id=stop_id,  # type: ignore[arg-type]
                    clock=self._clock,
                )
            elif command.event_type == GeofenceEventType.ARRIVED_ORG:
                crossing = GeofenceCrossing.arrived_at_organization(
                    id=crossing_id,
                    organization_id=organization_id,
                    trip_id=trip_id,
                    clock=self._clock,
                )
            else:
                crossing = GeofenceCrossing.exited(
                    id=crossing_id,
                    organization_id=organization_id,
                    trip_id=trip_id,
                    stop_id=stop_id,
                    clock=self._clock,
                )

            uow.geofence_crossings.add(crossing)
            uow.record_events(crossing.pull_domain_events())
            await uow.commit()
            return geofence_crossing_to_dto(crossing)

    # --- Reads --------------------------------------------------------------------------

    async def get_current_vehicle_position(
        self, query: GetCurrentVehiclePositionQuery
    ) -> VehiclePositionDTO | None:
        """Served by `LatestPositionPort` (Redis-backed in infra, a later phase) — never
        `TrackingUnitOfWork.vehicle_positions`, per that repository's own "latest is not read
        from here" contract (Phase 8.1)."""
        position = await self._latest_position_port.get_latest(
            VehicleId(query.vehicle_id)
        )
        return vehicle_position_to_dto(position) if position is not None else None

    async def get_vehicle_position_history(
        self, query: GetVehiclePositionHistoryQuery, *, uow: TrackingUnitOfWork
    ) -> list[VehiclePositionDTO]:
        async with uow:
            positions = await uow.vehicle_positions.list_for_trip(TripId(query.trip_id))
            return [vehicle_position_to_dto(position) for position in positions]

    async def get_geofence_crossings(
        self, query: GetGeofenceCrossingsQuery, *, uow: TrackingUnitOfWork
    ) -> list[GeofenceCrossingDTO]:
        async with uow:
            crossings = await uow.geofence_crossings.list_for_trip(
                TripId(query.trip_id)
            )
            return [geofence_crossing_to_dto(crossing) for crossing in crossings]
