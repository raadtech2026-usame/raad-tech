"""Unit tests for `modules.tracking.events.subscribers` (roadmap track B2, ADR-0009; Phase A
item A4 for the active-trip-resolution coverage below). Stdlib `unittest` — no `pytest`. Mirrors
`test_notification_subscribers.py`'s convention: fakes bound directly into a real
`core.di.container.Container`, keyed by the real types `DevicePositionReportedProcessor` resolves.

Covers: a live position event persists via `record_vehicle_position`; a backfill-flagged event
persists via `record_backfill_position` instead; optional fields (`speed_kph`/`heading_deg`/
`alarm_flags`) pass through as `None` when absent from the payload, matching
`RecordVehiclePositionCommand`'s own optional fields; `event.org_id` is used over a payload
duplicate when both are present; a live position's `trip_id` is resolved fresh via
`TripApplicationService.get_active_trip_for_vehicle` (never trusted from the payload), while a
backfilled position's `trip_id` passes through the payload unresolved.

`GeofenceEvaluationTests` below (roadmap item A5; ADR-0014) covers the live geofence evaluation
orchestration: approaching/entered/exited-stop and arrived/exited-organization transitions,
sequence advancement past a stop with no configured radius or after an exit, per-(event-type,
stop-or-org) cooldown suppression, backfill/no-active-trip exemption, and that a failure inside
evaluation never prevents the position write that already succeeded from being recorded.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import OrganizationDTO
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.tracking.application.commands import (
    RecordBackfillPositionCommand,
    RecordGeofenceCrossingCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import (
    GeofenceHysteresisState,
    GeofenceStatePort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.tracking.domain.value_objects import GeofenceEventType
from raad.modules.tracking.events.subscribers import DevicePositionReportedProcessor
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetActiveTripForVehicleQuery,
    RouteDTO,
    StopDTO,
)
from raad.modules.transport_ops.application.services import (
    RouteApplicationService,
    TripApplicationService,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class _FakeUnitOfWork:
    """`Container.resolve` is a plain type-keyed lookup with no `isinstance` enforcement (see
    `test_notification_subscribers.py`'s identical `FakeTransportOpsUnitOfWork` precedent) - the
    fake `TrackingApplicationService` below never actually uses `uow`, so this needs no `async
    with` shape either, unlike that precedent's own fake."""


class _RecordingTrackingService:
    def __init__(self) -> None:
        self.recorded_positions: list[RecordVehiclePositionCommand] = []
        self.recorded_backfills: list[RecordBackfillPositionCommand] = []
        self.recorded_crossings: list[RecordGeofenceCrossingCommand] = []

    async def record_vehicle_position(self, command, *, uow):
        self.recorded_positions.append(command)

    async def record_backfill_position(self, command, *, uow):
        self.recorded_backfills.append(command)

    async def record_geofence_crossing(self, command, *, uow):
        self.recorded_crossings.append(command)
        return command


class _FakeTripApplicationService:
    """`active_trip_id` is `None` by default (no active trip), matching the common case of a
    vehicle with no trip in progress - most tests never need to configure it. `route_id`
    defaults to a fixed value since only `GeofenceEvaluationTests` below ever reads it."""

    def __init__(
        self, *, active_trip_id: str | None = None, route_id: str = "route-1"
    ) -> None:
        self.active_trip_id = active_trip_id
        self.route_id = route_id
        self.queries: list[GetActiveTripForVehicleQuery] = []

    async def get_active_trip_for_vehicle(self, query, *, uow):
        self.queries.append(query)
        if self.active_trip_id is None:
            return None
        return type(
            "_TripDTO", (), {"id": self.active_trip_id, "route_id": self.route_id}
        )()


def _make_event(payload: dict, *, org_id: str | None = VALID_ORG_ULID) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type="DevicePositionReported",
        version=1,
        occurred_at=datetime.now(timezone.utc),
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type="Vehicle",
        aggregate_id="vehicle-1",
    )


class DevicePositionReportedProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = Container()
        self.service = _RecordingTrackingService()
        self.trip_service = _FakeTripApplicationService()
        self.container.bind_singleton(TrackingApplicationService, self.service)
        self.container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
        self.container.bind_singleton(TripApplicationService, self.trip_service)
        self.container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())
        self.processor = DevicePositionReportedProcessor(self.container)

    async def test_live_position_is_recorded_via_record_vehicle_position(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": None,
                "latitude": 22.672803,
                "longitude": 114.059395,
                "speed_kph": 12,
                "heading_deg": 270,
                "alarm_flags": 0,
                "event_time": "2026-07-24T10:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(len(self.service.recorded_positions), 1)
        self.assertEqual(self.service.recorded_backfills, [])
        command = self.service.recorded_positions[0]
        self.assertEqual(command.organization_id, VALID_ORG_ULID)
        self.assertEqual(command.vehicle_id, "vehicle-1")
        self.assertEqual(command.device_id, "device-1")
        self.assertEqual(command.latitude, 22.672803)
        self.assertEqual(command.longitude, 114.059395)
        self.assertEqual(command.speed_kph, 12)
        self.assertEqual(command.heading_deg, 270)
        self.assertEqual(
            command.event_time, datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)
        )

    async def test_backfill_flagged_event_uses_record_backfill_position(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": True,
            }
        )
        await self.processor.process(event)

        self.assertEqual(self.service.recorded_positions, [])
        self.assertEqual(len(self.service.recorded_backfills), 1)

    async def test_missing_optional_fields_default_to_none(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
            }
        )
        await self.processor.process(event)

        command = self.service.recorded_positions[0]
        self.assertIsNone(command.trip_id)
        self.assertIsNone(command.speed_kph)
        self.assertIsNone(command.heading_deg)
        self.assertIsNone(command.alarm_flags)

    async def test_event_org_id_is_preferred_over_payload_organization_id(self) -> None:
        other_org = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
        event = _make_event(
            {
                "organization_id": other_org,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
            },
            org_id=VALID_ORG_ULID,
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].organization_id, VALID_ORG_ULID
        )

    async def test_live_position_resolves_trip_id_from_the_active_trip_service(self) -> None:
        """Roadmap A4: the payload's own (always-`None`-today) `trip_id` is never trusted for a
        live position - the resolved value from `TripApplicationService` wins unconditionally."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": None,
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].trip_id, "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        )
        self.assertEqual(len(self.trip_service.queries), 1)
        self.assertEqual(self.trip_service.queries[0].vehicle_id, "vehicle-1")

    async def test_resolved_trip_id_overrides_a_payload_trip_id_if_one_is_ever_present(
        self,
    ) -> None:
        """Even a hypothetical future vendor adapter that *does* attach its own `trip_id` must
        not win - the backend-resolved value is always authoritative (see this processor's own
        module docstring)."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": "some-vendor-supplied-trip-id",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].trip_id, "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        )

    async def test_no_active_trip_leaves_trip_id_none(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertIsNone(self.service.recorded_positions[0].trip_id)

    async def test_backfill_position_never_resolves_active_trip_and_keeps_payload_value(
        self,
    ) -> None:
        """Roadmap A4's own carve-out: resolving "the vehicle's currently active trip" for a
        late-arriving, past-dated position would misattribute it - left unresolved instead."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": "buffered-trip-id",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": True,
            }
        )
        await self.processor.process(event)

        self.assertEqual(self.service.recorded_backfills[0].trip_id, "buffered-trip-id")
        self.assertEqual(self.trip_service.queries, [])


# --- Live geofence evaluation (roadmap item A5; ADR-0014) ------------------------------------

TRIP_ID_1 = "01J8Z3K9G6X8YV5T4N2R7QW3TR"

# 1 degree of latitude at the equator is ~111,320m; ~0.0018 degrees is ~200m - deliberately
# between a 100m arrival radius and its 3x=300m approach radius, so a position placed there is
# inside the approach radius but outside the arrival radius.
_APPROACH_ONLY_LATITUDE_OFFSET = 0.0018
_FAR_AWAY_LATITUDE_OFFSET = 1.0  # ~111km - clearly outside any radius used in these tests


class _MutableClock(Clock):
    """Lets cooldown tests advance "now" between positions - `Clock` is otherwise always a
    frozen `FixedClock` elsewhere in this suite."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


class _FakeRouteApplicationService:
    def __init__(self, route: RouteDTO) -> None:
        self.route = route

    async def get_route_by_id(self, query, *, uow):
        return self.route


class _FakeOrganizationApplicationService:
    def __init__(self, organization: OrganizationDTO) -> None:
        self.organization = organization

    async def get_organization_by_id(self, query, *, uow):
        return self.organization


class _InMemoryGeofenceStatePort:
    def __init__(self) -> None:
        self._states: dict[str, GeofenceHysteresisState] = {}

    async def get_state(self, trip_id):
        return self._states.get(str(trip_id))

    async def save_state(self, trip_id, state) -> None:
        self._states[str(trip_id)] = state


def _make_stop(
    *, id: str, sequence_no: int, latitude: float = 0.0, geofence_radius_m: int | None = 100
) -> StopDTO:
    return StopDTO(
        id=id,
        name=f"Stop {id}",
        latitude=latitude,
        longitude=0.0,
        sequence_no=sequence_no,
        geofence_radius_m=geofence_radius_m,
    )


def _make_route(stops: list[StopDTO], *, route_id: str = "route-1") -> RouteDTO:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return RouteDTO(
        id=route_id,
        organization_id=VALID_ORG_ULID,
        name="Test Route",
        status="active",
        created_at=now,
        updated_at=now,
        stops=tuple(stops),
    )


def _make_organization(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    geofence_radius_m: int | None = None,
) -> OrganizationDTO:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OrganizationDTO(
        id=VALID_ORG_ULID,
        name="Test School",
        org_type="school",
        parent_org_id=None,
        region_id="region-1",
        billing_model="organization_pays",
        status="active",
        created_at=now,
        updated_at=now,
        latitude=latitude,
        longitude=longitude,
        geofence_radius_m=geofence_radius_m,
    )


def _make_position_event(
    *, latitude: float, longitude: float = 0.0, event_time: str = "2026-07-26T09:00:00+00:00"
) -> DomainEvent:
    return _make_event(
        {
            "organization_id": VALID_ORG_ULID,
            "vehicle_id": "vehicle-1",
            "device_id": "device-1",
            "latitude": latitude,
            "longitude": longitude,
            "event_time": event_time,
            "is_backfill": False,
        }
    )


class GeofenceEvaluationTests(unittest.IsolatedAsyncioTestCase):
    """Roadmap item A5 / ADR-0014. Each test wires its own route/organization fixture directly
    into the container rather than sharing one `setUp` fixture, since the whole point is
    exercising different route/organization shapes."""

    def _make_processor(
        self,
        *,
        route: RouteDTO,
        organization: OrganizationDTO,
        clock: Clock,
    ) -> tuple[DevicePositionReportedProcessor, _RecordingTrackingService, _InMemoryGeofenceStatePort]:
        container = Container()
        tracking_service = _RecordingTrackingService()
        trip_service = _FakeTripApplicationService(
            active_trip_id=TRIP_ID_1, route_id=route.id
        )
        state_port = _InMemoryGeofenceStatePort()
        container.bind_singleton(TrackingApplicationService, tracking_service)
        container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
        container.bind_singleton(TripApplicationService, trip_service)
        container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())
        container.bind_singleton(
            RouteApplicationService, _FakeRouteApplicationService(route)
        )
        container.bind_singleton(
            OrganizationApplicationService,
            _FakeOrganizationApplicationService(organization),
        )
        container.bind_singleton(OrganizationUnitOfWork, _FakeUnitOfWork())
        container.bind_singleton(GeofenceStatePort, state_port)
        container.bind_singleton(Clock, clock)
        return DevicePositionReportedProcessor(container), tracking_service, state_port

    async def test_approaching_then_entering_a_stop_fires_each_event_once(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(
            _make_position_event(latitude=_APPROACH_ONLY_LATITUDE_OFFSET)
        )
        self.assertEqual(
            [c.event_type for c in tracking_service.recorded_crossings],
            [GeofenceEventType.APPROACHING_STOP],
        )
        self.assertEqual(tracking_service.recorded_crossings[0].stop_id, "stop-1")

        await processor.process(_make_position_event(latitude=0.0))
        self.assertEqual(
            [c.event_type for c in tracking_service.recorded_crossings],
            [GeofenceEventType.APPROACHING_STOP, GeofenceEventType.ENTERED_STOP],
        )

    async def test_exiting_a_stop_fires_exited_and_advances_to_the_next_stop(self) -> None:
        stop_1 = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        stop_2 = _make_stop(
            id="stop-2", sequence_no=2, latitude=_FAR_AWAY_LATITUDE_OFFSET, geofence_radius_m=100
        )
        route = _make_route([stop_1, stop_2])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))  # enters stop 1
        clock.advance(seconds=200)  # past the cooldown window
        await processor.process(
            _make_position_event(latitude=_FAR_AWAY_LATITUDE_OFFSET)
        )  # now at stop 2's location - far from stop 1

        event_types = [c.event_type for c in tracking_service.recorded_crossings]
        self.assertIn(GeofenceEventType.EXITED, event_types)
        exited = next(
            c
            for c in tracking_service.recorded_crossings
            if c.event_type == GeofenceEventType.EXITED
        )
        self.assertEqual(exited.stop_id, "stop-1")

        state = await state_port.get_state(TRIP_ID_1)
        self.assertEqual(state.stop_target_id, "stop-2")

    async def test_last_stop_exit_marks_all_stops_exhausted(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, _tracking_service, state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))  # enters stop 1
        clock.advance(seconds=200)
        await processor.process(
            _make_position_event(latitude=_FAR_AWAY_LATITUDE_OFFSET)
        )  # exits stop 1, no stop 2 exists

        state = await state_port.get_state(TRIP_ID_1)
        self.assertTrue(state.stops_exhausted)
        self.assertIsNone(state.stop_target_id)

    async def test_stop_without_a_configured_radius_is_never_evaluated_or_advanced(
        self,
    ) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=None)
        route = _make_route([stop])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))

        self.assertEqual(tracking_service.recorded_crossings, [])
        state = await state_port.get_state(TRIP_ID_1)
        self.assertEqual(state.stop_target_id, "stop-1")
        self.assertFalse(state.stops_exhausted)

    async def test_organization_geofence_cooldown_suppresses_rapid_reentry(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization(latitude=0.0, longitude=0.0, geofence_radius_m=50)
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))  # inside org geofence
        clock.advance(seconds=10)
        await processor.process(
            _make_position_event(latitude=_FAR_AWAY_LATITUDE_OFFSET)
        )  # exits org geofence
        clock.advance(seconds=10)  # still within the 120s cooldown window
        await processor.process(_make_position_event(latitude=0.0))  # re-enters org geofence

        org_crossings = [
            c
            for c in tracking_service.recorded_crossings
            if c.stop_id is None
        ]
        # ARRIVED_ORG fires once; the second entry is suppressed by cooldown even though the
        # was-inside/is-inside flag genuinely transitioned again.
        arrived_count = sum(
            1 for c in org_crossings if c.event_type == GeofenceEventType.ARRIVED_ORG
        )
        self.assertEqual(arrived_count, 1)

    async def test_organization_geofence_refires_after_cooldown_elapses(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization(latitude=0.0, longitude=0.0, geofence_radius_m=50)
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))
        clock.advance(seconds=10)
        await processor.process(_make_position_event(latitude=_FAR_AWAY_LATITUDE_OFFSET))
        clock.advance(seconds=200)  # past the 120s cooldown window
        await processor.process(_make_position_event(latitude=0.0))

        arrived_count = sum(
            1
            for c in tracking_service.recorded_crossings
            if c.event_type == GeofenceEventType.ARRIVED_ORG
        )
        self.assertEqual(arrived_count, 2)

    async def test_organization_without_a_configured_geofence_is_never_evaluated(
        self,
    ) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization()  # no latitude/longitude/radius configured
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        await processor.process(_make_position_event(latitude=0.0))

        org_crossings = [c for c in tracking_service.recorded_crossings if c.stop_id is None]
        self.assertEqual(org_crossings, [])

    async def test_backfill_position_never_triggers_geofence_evaluation(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization(latitude=0.0, longitude=0.0, geofence_radius_m=50)
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 0.0,
                "longitude": 0.0,
                "event_time": "2026-07-26T09:00:00+00:00",
                "is_backfill": True,
            }
        )
        await processor.process(event)

        self.assertEqual(tracking_service.recorded_crossings, [])

    async def test_no_active_trip_skips_geofence_evaluation(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization(latitude=0.0, longitude=0.0, geofence_radius_m=50)
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )
        # Override: no active trip resolved for this vehicle.
        processor._container.bind_singleton(
            TripApplicationService, _FakeTripApplicationService(active_trip_id=None)
        )

        await processor.process(_make_position_event(latitude=0.0))

        self.assertEqual(tracking_service.recorded_crossings, [])

    async def test_a_failure_during_evaluation_does_not_prevent_the_position_write(
        self,
    ) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        processor, tracking_service, _state_port = self._make_processor(
            route=route, organization=organization, clock=clock
        )

        class _BrokenRouteApplicationService:
            async def get_route_by_id(self, query, *, uow):
                raise RuntimeError("route lookup exploded")

        processor._container.bind_singleton(
            RouteApplicationService, _BrokenRouteApplicationService()
        )

        # Must not raise - the position write already succeeded and must not be undone by a
        # downstream, best-effort evaluation failure (module docstring).
        await processor.process(_make_position_event(latitude=0.0))

        self.assertEqual(len(tracking_service.recorded_positions), 1)
        self.assertEqual(tracking_service.recorded_crossings, [])

    async def test_geofence_state_port_unbound_does_not_raise(self) -> None:
        stop = _make_stop(id="stop-1", sequence_no=1, geofence_radius_m=100)
        route = _make_route([stop])
        organization = _make_organization()
        clock = _MutableClock(datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc))
        container = Container()
        tracking_service = _RecordingTrackingService()
        trip_service = _FakeTripApplicationService(
            active_trip_id=TRIP_ID_1, route_id=route.id
        )
        container.bind_singleton(TrackingApplicationService, tracking_service)
        container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
        container.bind_singleton(TripApplicationService, trip_service)
        container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())
        container.bind_singleton(Clock, clock)
        # Deliberately not bound: GeofenceStatePort, RouteApplicationService,
        # OrganizationApplicationService, OrganizationUnitOfWork - matches an environment with
        # no RAAD_REDIS__URL configured.
        processor = DevicePositionReportedProcessor(container)

        await processor.process(_make_position_event(latitude=0.0))

        self.assertEqual(len(tracking_service.recorded_positions), 1)
        self.assertEqual(tracking_service.recorded_crossings, [])


if __name__ == "__main__":
    unittest.main()
