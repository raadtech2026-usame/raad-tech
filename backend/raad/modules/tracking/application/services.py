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

from datetime import timedelta

from raad.core.ids.generator import IdGenerator
from raad.core.pagination import CursorPage
from raad.core.time.clock import Clock
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
)
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
    FleetOnlineVehiclesDTO,
    OnlineVehicleDTO,
    OnlineVehiclePositionDTO,
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
        latest_position_port: LatestPositionPort | None = None,
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
        """Served by `LatestPositionPort` (Redis-backed via `infra.adapters.
        RedisLatestPositionPort`, Backend Stabilization phase) — never `TrackingUnitOfWork.
        vehicle_positions`, per that repository's own "latest is not read from here" contract
        (Phase 8.1). `latest_position_port` is optional at the *service* level (constructor)
        so the rest of this service — including `prune_position_history`, the retention
        scheduled job's own entry point, which needs no Redis at all — stays reachable even
        without a configured Redis; only this one method needs the port, so only this method
        fails loudly when it's unbound, mirroring `BillingApplicationService.initiate_payment`'s
        identical method-granularity "fail loudly, don't fake" treatment of its own optional
        `PaymentProviderPort`."""
        if self._latest_position_port is None:
            raise NotImplementedError(
                "No LatestPositionPort is bound - RAAD_REDIS__URL is not configured in this "
                "environment. See tracking.infra.adapters.RedisLatestPositionPort's own "
                "module docstring."
            )
        position = await self._latest_position_port.get_latest(
            VehicleId(query.vehicle_id)
        )
        return vehicle_position_to_dto(position) if position is not None else None

    async def get_vehicle_position_history(
        self, query: GetVehiclePositionHistoryQuery, *, uow: TrackingUnitOfWork
    ) -> CursorPage[VehiclePositionDTO]:
        """Cursor-paginated (Pagination/Filtering/Sorting phase) — see `GetVehiclePositionHistoryQuery`'s
        own docstring. `list_for_trip` (unpaginated) stays available on the repository
        interface for any other caller; this method is this route's own entry point."""
        async with uow:
            page = await uow.vehicle_positions.list_for_trip_page(
                TripId(query.trip_id), query.cursor_request, filters=query.filters
            )
            return CursorPage(
                data=[vehicle_position_to_dto(position) for position in page.data],
                limit=page.limit,
                next_cursor=page.next_cursor,
                has_more=page.has_more,
            )

    async def prune_position_history(
        self, retention_days: int, *, uow: TrackingUnitOfWork
    ) -> int:
        """No approved HTTP route — the retention-pruning scheduled job's own entry point
        (`.claude/rules/database.md` #6; see `domain.repositories.VehiclePositionRepository.
        delete_before`'s own docstring for why this is a bulk `DELETE`, not a partition drop).
        Returns the number of rows deleted."""
        async with uow:
            now = self._clock.now()
            # `event_time` is stored naive (`DateTime(timezone=False)`, Database Design §7.1)
            # but `Clock.now()` returns tz-aware UTC (`SystemClock`) - stripped here, the same
            # fix `infra/mappers.py`'s own `_to_naive_utc` already applies throughout this
            # codebase for the identical aware/naive mismatch.
            cutoff = (now - timedelta(days=retention_days)).replace(tzinfo=None)
            return await uow.vehicle_positions.delete_before(cutoff)

    async def get_geofence_crossings(
        self, query: GetGeofenceCrossingsQuery, *, uow: TrackingUnitOfWork
    ) -> list[GeofenceCrossingDTO]:
        async with uow:
            crossings = await uow.geofence_crossings.list_for_trip(
                TripId(query.trip_id)
            )
            return [geofence_crossing_to_dto(crossing) for crossing in crossings]


#: The existing ≤100-vehicle-per-page convention this same feature already established
#: (`listVehiclesForTracking`'s own page size, frontend) — the ADR-0031 scalability analysis's
#: chosen cap on how many online vehicles the All Vehicles map tracks live at once, rather than
#: opening an unbounded number of `/ws/tracking` connections. Not a hard platform limit; a
#: future widening needs its own decision, not a silent bump here.
FLEET_OVERVIEW_MAX_ONLINE_VEHICLES = 100


class FleetOverviewApplicationService:
    """ADR-0031 (Fleet Overview read model) — backs `GET /tracking/vehicles/online`, the All
    Vehicles map mode's one-time snapshot query. Composes `fleet_device`'s own
    `VehicleApplicationService`/`DeviceApplicationService` (never a cross-module DB read,
    `.claude/rules/backend.md` #3) plus this module's own `LatestPositionPort` — exactly the
    `PlatformStatsApplicationService` (ADR-0020) precedent: a new, distinct composing service,
    not a method bolted onto `TrackingApplicationService`, since its dependency set (two other
    modules' services) is entirely different from every other method in this file.

    Each dependency's own Unit of Work is resolved by the caller (the router) and passed in per
    call, mirroring `PlatformStatsApplicationService.get_platform_stats`'s identical shape —
    this service holds no UoW of its own.

    `latest_position_port` is optional, the same "fail loudly only at the one method that needs
    it, not the whole service" posture `TrackingApplicationService.get_current_vehicle_position`
    already establishes — without a reachable Redis, every vehicle's `position` is simply
    `None`, not a 500."""

    def __init__(
        self,
        *,
        vehicle_service: VehicleApplicationService,
        device_service: DeviceApplicationService,
        latest_position_port: LatestPositionPort | None = None,
    ) -> None:
        self._vehicle_service = vehicle_service
        self._device_service = device_service
        self._latest_position_port = latest_position_port

    async def list_online_vehicles(
        self, *, fleet_device_uow: FleetDeviceUnitOfWork
    ) -> FleetOnlineVehiclesDTO:
        online_devices = await self._device_service.list_online_devices_with_vehicle_assignment(
            uow=fleet_device_uow
        )
        if not online_devices:
            return FleetOnlineVehiclesDTO(vehicles=[], total_online=0)

        # ADR-0031's own scalability analysis: capped, deterministic (not "whichever devices
        # happened to sort first from the DB"), and disclosed via `total_online` (the *pre-cap*
        # count) rather than silently truncated with no signal to the caller.
        online_devices = sorted(online_devices, key=lambda d: d.vehicle_id)
        total_online = len(online_devices)
        capped = online_devices[:FLEET_OVERVIEW_MAX_ONLINE_VEHICLES]

        vehicle_ids = [d.vehicle_id for d in capped]
        vehicles = await self._vehicle_service.list_vehicles_by_ids(
            vehicle_ids, uow=fleet_device_uow
        )
        vehicles_by_id = {v.id: v for v in vehicles}

        positions: dict[VehicleId, VehiclePosition] = {}
        if self._latest_position_port is not None:
            positions = await self._latest_position_port.get_latest_many(
                [VehicleId(vid) for vid in vehicle_ids]
            )

        result: list[OnlineVehicleDTO] = []
        for online in capped:
            vehicle = vehicles_by_id.get(online.vehicle_id)
            if vehicle is None:
                # The device's own assignment points at a vehicle this caller's scope/tenant
                # can't see (or that no longer exists) — silently excluded, not an error, the
                # same posture `list_by_ids`' own docstring already documents for an
                # out-of-scope id.
                continue
            position = positions.get(VehicleId(online.vehicle_id))
            result.append(
                OnlineVehicleDTO(
                    vehicle_id=vehicle.id,
                    plate_no=vehicle.plate_no,
                    label=vehicle.label,
                    device_id=online.device_id,
                    is_online=True,
                    position=(
                        OnlineVehiclePositionDTO(
                            latitude=position.position.latitude,
                            longitude=position.position.longitude,
                            heading_deg=(
                                position.heading_deg.value
                                if position.heading_deg is not None
                                else None
                            ),
                            speed_kph=(
                                position.speed_kph.value
                                if position.speed_kph is not None
                                else None
                            ),
                            event_time=position.event_time,
                        )
                        if position is not None
                        else None
                    ),
                )
            )
        return FleetOnlineVehiclesDTO(vehicles=result, total_online=total_online)
