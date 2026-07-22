"""Application-layer tests for `tracking`'s `TrackingApplicationService`. Stdlib `unittest` —
no `pytest`, matching established precedent. In-memory fake `TrackingUnitOfWork`/repositories,
with `list_for_trip` sorted by `event_time` (the documented repository contract,
`domain/repositories.py`) so "position ordering" is actually exercised, not assumed.

Covers: position recording (live + backfill), history ordering by `event_time` (not insertion
order), the pure `evaluate_geofence` pass-through, and geofence-crossing recording per event
type.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import DomainError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    CursorPage,
    CursorPageRequest,
    FilterCondition,
    decode_cursor,
    encode_cursor,
)
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
    GetGeofenceCrossingsQuery,
    GetVehiclePositionHistoryQuery,
)
from raad.modules.tracking.application.services import TrackingApplicationService
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

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
VALID_DEVICE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MF"
VALID_TRIP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MG"
VALID_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MH"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class InMemoryVehiclePositionRepository(VehiclePositionRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, VehiclePosition] = {}

    async def get(self, position_id: VehiclePositionId):
        return self.by_id.get(str(position_id))

    async def list_for_trip(self, trip_id: TripId) -> list[VehiclePosition]:
        matches = [
            p
            for p in self.by_id.values()
            if p.trip_id is not None and str(p.trip_id) == str(trip_id)
        ]
        return sorted(matches, key=lambda p: p.event_time)

    async def list_for_vehicle(self, vehicle_id: VehicleId) -> list[VehiclePosition]:
        matches = [
            p for p in self.by_id.values() if str(p.vehicle_id) == str(vehicle_id)
        ]
        return sorted(matches, key=lambda p: p.event_time)

    async def list_for_trip_page(
        self,
        trip_id: TripId,
        cursor_request: CursorPageRequest,
        *,
        filters: list[FilterCondition],
    ) -> CursorPage[VehiclePosition]:
        """In-memory cursor-pagination fake — mirrors `SqlAlchemyVehiclePositionRepository.
        list_for_trip_page`'s contract: `trip_id` mandatory-ANDed, ascending `(event_time,
        id)` keyset, `filters` whitelisted to `vehicle_id`/`is_backfill`/`trip_id`."""
        matches = [
            p
            for p in self.by_id.values()
            if p.trip_id is not None and str(p.trip_id) == str(trip_id)
        ]
        for condition in filters:
            if condition.field == "vehicle_id":
                matches = [p for p in matches if str(p.vehicle_id) == condition.value]
            elif condition.field == "is_backfill":
                wanted = condition.value.strip().lower() in {"1", "true", "yes"}
                matches = [p for p in matches if p.is_backfill == wanted]
            elif condition.field == "trip_id":
                matches = [p for p in matches if str(p.trip_id) == condition.value]
            else:
                raise ValidationError(
                    f"Field {condition.field!r} is not filterable on this resource.",
                    details={"field": condition.field},
                )

        matches.sort(key=lambda p: (p.event_time, str(p.id)))

        if cursor_request.cursor is not None:
            cursor_event_time_raw, cursor_id = decode_cursor(cursor_request.cursor)
            cursor_key = (datetime.fromisoformat(cursor_event_time_raw), cursor_id)
            matches = [
                p for p in matches if (p.event_time, str(p.id)) > cursor_key
            ]

        page_rows = matches[: cursor_request.limit]
        has_more = len(matches) > cursor_request.limit
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(last.event_time.isoformat(), str(last.id))

        return CursorPage(
            data=page_rows,
            limit=cursor_request.limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def add(self, position: VehiclePosition) -> None:
        self.by_id[str(position.id)] = position

    async def delete_before(self, cutoff) -> int:
        stale_ids = [
            position_id
            for position_id, position in self.by_id.items()
            if position.event_time < cutoff
        ]
        for position_id in stale_ids:
            del self.by_id[position_id]
        return len(stale_ids)


class InMemoryGeofenceCrossingRepository(GeofenceCrossingRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, GeofenceCrossing] = {}

    async def get(self, crossing_id: GeofenceCrossingId):
        return self.by_id.get(str(crossing_id))

    async def list_for_trip(self, trip_id: TripId) -> list[GeofenceCrossing]:
        matches = [c for c in self.by_id.values() if str(c.trip_id) == str(trip_id)]
        return sorted(matches, key=lambda c: c.occurred_at)

    async def latest_for_trip(self, trip_id, *, stop_id, event_type):
        candidates = [
            c
            for c in self.by_id.values()
            if str(c.trip_id) == str(trip_id) and c.event_type == event_type
        ]
        return max(candidates, key=lambda c: c.occurred_at) if candidates else None

    def add(self, crossing: GeofenceCrossing) -> None:
        self.by_id[str(crossing.id)] = crossing


class FakeTrackingUnitOfWork(TrackingUnitOfWork):
    def __init__(
        self,
        vehicle_positions: InMemoryVehiclePositionRepository,
        geofence_crossings: InMemoryGeofenceCrossingRepository,
    ) -> None:
        self.vehicle_positions = vehicle_positions
        self.geofence_crossings = geofence_crossings
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class NullLatestPositionPort(LatestPositionPort):
    async def get_latest(self, vehicle_id):
        return None


def make_service() -> tuple[TrackingApplicationService, FakeTrackingUnitOfWork]:
    service = TrackingApplicationService(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_generator=SequentialIdGenerator(),
        latest_position_port=NullLatestPositionPort(),
    )
    uow = FakeTrackingUnitOfWork(
        InMemoryVehiclePositionRepository(), InMemoryGeofenceCrossingRepository()
    )
    return service, uow


def _position_command(
    event_time: datetime, **overrides
) -> RecordVehiclePositionCommand:
    kwargs = dict(
        organization_id=VALID_ORG_ULID,
        vehicle_id=VALID_VEHICLE_ULID,
        device_id=VALID_DEVICE_ULID,
        latitude=2.0469,
        longitude=45.3182,
        event_time=event_time,
        trip_id=VALID_TRIP_ULID,
    )
    kwargs.update(overrides)
    return RecordVehiclePositionCommand(**kwargs)


class RecordVehiclePositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_live_position_persists_and_commits(self) -> None:
        service, uow = make_service()
        dto = await service.record_vehicle_position(
            _position_command(datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)), uow=uow
        )
        self.assertFalse(dto.is_backfill)
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(len(uow.vehicle_positions.by_id), 1)

    async def test_record_backfill_position_flags_is_backfill_true(self) -> None:
        service, uow = make_service()
        command = RecordBackfillPositionCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            device_id=VALID_DEVICE_ULID,
            latitude=2.0469,
            longitude=45.3182,
            event_time=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            trip_id=VALID_TRIP_ULID,
        )
        dto = await service.record_backfill_position(command, uow=uow)
        self.assertTrue(dto.is_backfill)

    async def test_invalid_coordinates_raise_domain_error(self) -> None:
        service, uow = make_service()
        with self.assertRaises(DomainError):
            await service.record_vehicle_position(
                _position_command(
                    datetime(2026, 1, 1, tzinfo=timezone.utc), latitude=999.0
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)

    async def test_position_history_is_ordered_by_event_time_not_insertion_order(
        self,
    ) -> None:
        """Regression: Database Design §7.1's ix_vehicle_positions__trip_time contract -
        list_for_trip must return history ordered by event_time, including out-of-order
        insertion (e.g. a backfilled point arriving after later live points)."""
        service, uow = make_service()
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

        # Insert out of chronological order: middle, then earliest (backfill), then latest.
        await service.record_vehicle_position(
            _position_command(base + timedelta(minutes=5)), uow=uow
        )
        await service.record_backfill_position(
            RecordBackfillPositionCommand(
                organization_id=VALID_ORG_ULID,
                vehicle_id=VALID_VEHICLE_ULID,
                device_id=VALID_DEVICE_ULID,
                latitude=2.0469,
                longitude=45.3182,
                event_time=base,  # earliest, but inserted second
                trip_id=VALID_TRIP_ULID,
            ),
            uow=uow,
        )
        await service.record_vehicle_position(
            _position_command(base + timedelta(minutes=10)), uow=uow
        )

        page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(trip_id=VALID_TRIP_ULID), uow=uow
        )
        self.assertEqual(len(page.data), 3)
        event_times = [p.event_time for p in page.data]
        self.assertEqual(event_times, sorted(event_times))
        self.assertEqual(
            event_times[0], base
        )  # backfilled point sorts first despite being inserted 2nd

    async def test_history_for_unknown_trip_returns_empty_list(self) -> None:
        service, uow = make_service()
        page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(trip_id="01J8Z3K9G6X8YV5T4N2R7QW3ZZ"),
            uow=uow,
        )
        self.assertEqual(page.data, [])
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_cursor)

    async def test_history_page_reports_has_more_and_next_cursor(self) -> None:
        """Regression: `CursorPage.has_more`/`next_cursor` reflect the true remaining count,
        not just "this page came back non-empty"."""
        service, uow = make_service()
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        for i in range(3):
            await service.record_vehicle_position(
                _position_command(base + timedelta(minutes=i)), uow=uow
            )

        page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(
                trip_id=VALID_TRIP_ULID,
                cursor_request=CursorPageRequest(limit=2),
            ),
            uow=uow,
        )
        self.assertEqual(len(page.data), 2)
        self.assertTrue(page.has_more)
        self.assertIsNotNone(page.next_cursor)
        self.assertEqual(
            [p.event_time for p in page.data], [base, base + timedelta(minutes=1)]
        )

    async def test_history_following_next_cursor_returns_remaining_slice_no_overlap(
        self,
    ) -> None:
        service, uow = make_service()
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        for i in range(3):
            await service.record_vehicle_position(
                _position_command(base + timedelta(minutes=i)), uow=uow
            )

        first_page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(
                trip_id=VALID_TRIP_ULID,
                cursor_request=CursorPageRequest(limit=2),
            ),
            uow=uow,
        )
        second_page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(
                trip_id=VALID_TRIP_ULID,
                cursor_request=CursorPageRequest(
                    limit=2, cursor=first_page.next_cursor
                ),
            ),
            uow=uow,
        )

        self.assertEqual(len(second_page.data), 1)
        self.assertFalse(second_page.has_more)
        self.assertIsNone(second_page.next_cursor)
        first_ids = {p.id for p in first_page.data}
        second_ids = {p.id for p in second_page.data}
        self.assertEqual(first_ids & second_ids, set())
        self.assertEqual(second_page.data[0].event_time, base + timedelta(minutes=2))

    async def test_history_filters_by_vehicle_id(self) -> None:
        service, uow = make_service()
        base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        other_vehicle_ulid = "01J8Z3K9G6X8YV5T4N2R7QW3XV"
        await service.record_vehicle_position(_position_command(base), uow=uow)
        await service.record_vehicle_position(
            _position_command(
                base + timedelta(minutes=1), vehicle_id=other_vehicle_ulid
            ),
            uow=uow,
        )

        page = await service.get_vehicle_position_history(
            GetVehiclePositionHistoryQuery(
                trip_id=VALID_TRIP_ULID,
                filters=[
                    FilterCondition(
                        field="vehicle_id", op="eq", value=VALID_VEHICLE_ULID
                    )
                ],
            ),
            uow=uow,
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.data[0].vehicle_id, VALID_VEHICLE_ULID)

    async def test_history_unwhitelisted_filter_field_raises_validation_error(
        self,
    ) -> None:
        service, uow = make_service()
        await service.record_vehicle_position(
            _position_command(datetime(2026, 1, 1, tzinfo=timezone.utc)), uow=uow
        )
        with self.assertRaises(ValidationError):
            await service.get_vehicle_position_history(
                GetVehiclePositionHistoryQuery(
                    trip_id=VALID_TRIP_ULID,
                    filters=[
                        FilterCondition(field="latitude", op="eq", value="2.0")
                    ],
                ),
                uow=uow,
            )


class EvaluateGeofenceApplicationTests(unittest.TestCase):
    def test_evaluate_geofence_is_synchronous_no_io(self) -> None:
        """Regression: evaluate_geofence performs no I/O - a sync method, not async, and
        takes no uow parameter."""
        service, _uow = make_service()
        import inspect

        self.assertFalse(inspect.iscoroutinefunction(service.evaluate_geofence))

    def test_evaluate_geofence_detects_entered_transition(self) -> None:
        service, _uow = make_service()
        result = service.evaluate_geofence(
            EvaluateGeofenceCommand(
                position_latitude=2.0469,
                position_longitude=45.3182,
                center_latitude=2.0469,
                center_longitude=45.3182,
                radius_m=100,
                was_inside=False,
            )
        )
        self.assertTrue(result.is_inside)
        self.assertEqual(result.transition, "entered")

    def test_evaluate_geofence_detects_exited_transition(self) -> None:
        service, _uow = make_service()
        result = service.evaluate_geofence(
            EvaluateGeofenceCommand(
                position_latitude=10.0,
                position_longitude=10.0,
                center_latitude=0.0,
                center_longitude=0.0,
                radius_m=100,
                was_inside=True,
            )
        )
        self.assertFalse(result.is_inside)
        self.assertEqual(result.transition, "exited")


class RecordGeofenceCrossingTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_approaching_stop_crossing(self) -> None:
        service, uow = make_service()
        dto = await service.record_geofence_crossing(
            RecordGeofenceCrossingCommand(
                organization_id=VALID_ORG_ULID,
                trip_id=VALID_TRIP_ULID,
                event_type=GeofenceEventType.APPROACHING_STOP,
                stop_id=VALID_STOP_ULID,
            ),
            uow=uow,
        )
        self.assertEqual(dto.event_type, "approaching_stop")
        self.assertEqual(uow.recorded_events[0].event_type, "VehicleApproachingStop")

    async def test_record_approaching_stop_without_stop_id_raises_domain_error(
        self,
    ) -> None:
        """Regression: the domain invariant (stop_id required for approaching_stop) is
        reachable through the application layer, not bypassed."""
        service, uow = make_service()
        with self.assertRaises(DomainError):
            await service.record_geofence_crossing(
                RecordGeofenceCrossingCommand(
                    organization_id=VALID_ORG_ULID,
                    trip_id=VALID_TRIP_ULID,
                    event_type=GeofenceEventType.APPROACHING_STOP,
                    stop_id=None,
                ),
                uow=uow,
            )

    async def test_record_arrived_org_crossing_without_stop_id(self) -> None:
        service, uow = make_service()
        dto = await service.record_geofence_crossing(
            RecordGeofenceCrossingCommand(
                organization_id=VALID_ORG_ULID,
                trip_id=VALID_TRIP_ULID,
                event_type=GeofenceEventType.ARRIVED_ORG,
                stop_id=None,
            ),
            uow=uow,
        )
        self.assertEqual(dto.event_type, "arrived_org")

    async def test_get_geofence_crossings_returns_all_for_trip(self) -> None:
        service, uow = make_service()
        await service.record_geofence_crossing(
            RecordGeofenceCrossingCommand(
                organization_id=VALID_ORG_ULID,
                trip_id=VALID_TRIP_ULID,
                event_type=GeofenceEventType.ARRIVED_ORG,
                stop_id=None,
            ),
            uow=uow,
        )
        await service.record_geofence_crossing(
            RecordGeofenceCrossingCommand(
                organization_id=VALID_ORG_ULID,
                trip_id=VALID_TRIP_ULID,
                event_type=GeofenceEventType.EXITED,
                stop_id=None,
            ),
            uow=uow,
        )
        crossings = await service.get_geofence_crossings(
            GetGeofenceCrossingsQuery(trip_id=VALID_TRIP_ULID), uow=uow
        )
        self.assertEqual(len(crossings), 2)


class GetCurrentVehiclePositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_latest_position_port_has_nothing(self) -> None:
        """Regression: latest position is served by LatestPositionPort (Redis), never the
        history repository - confirmed by using a port that always returns None regardless of
        what's in vehicle_positions."""
        service, uow = make_service()
        await service.record_vehicle_position(
            _position_command(datetime(2026, 1, 1, tzinfo=timezone.utc)), uow=uow
        )
        from raad.modules.tracking.application.queries import (
            GetCurrentVehiclePositionQuery,
        )

        result = await service.get_current_vehicle_position(
            GetCurrentVehiclePositionQuery(vehicle_id=VALID_VEHICLE_ULID)
        )
        self.assertIsNone(result)

    async def test_raises_not_implemented_when_no_port_bound(self) -> None:
        """`latest_position_port` is optional at the service level (Backend Stabilization
        phase) — the whole service stays constructible without Redis, but this one method
        fails loudly when the port itself is missing, mirroring `BillingApplicationService.
        initiate_payment`'s identical method-granularity treatment of `PaymentProviderPort`."""
        from raad.modules.tracking.application.queries import (
            GetCurrentVehiclePositionQuery,
        )

        service = TrackingApplicationService(
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
            id_generator=SequentialIdGenerator(),
            latest_position_port=None,
        )
        with self.assertRaises(NotImplementedError):
            await service.get_current_vehicle_position(
                GetCurrentVehiclePositionQuery(vehicle_id=VALID_VEHICLE_ULID)
            )


class PrunePositionHistoryTests(unittest.IsolatedAsyncioTestCase):
    """`prune_position_history` (Backend Stabilization phase) — the retention-pruning
    scheduled job's own entry point. Needs no `LatestPositionPort` at all (unlike
    `get_current_vehicle_position`) — exercised here via `make_service()`'s `NullLatestPositionPort`
    purely to prove that's true, not because the method touches it."""

    async def test_deletes_positions_older_than_retention_window(self) -> None:
        service, uow = make_service()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        old_position = await service.record_vehicle_position(
            _position_command((now - timedelta(days=100)).replace(tzinfo=None)), uow=uow
        )
        recent_position = await service.record_vehicle_position(
            _position_command((now - timedelta(days=10)).replace(tzinfo=None)), uow=uow
        )

        deleted_count = await service.prune_position_history(90, uow=uow)

        self.assertEqual(deleted_count, 1)
        self.assertIsNone(await uow.vehicle_positions.get(
            VehiclePositionId(old_position.id)
        ))
        self.assertIsNotNone(
            await uow.vehicle_positions.get(VehiclePositionId(recent_position.id))
        )

    async def test_no_positions_older_than_window_deletes_nothing(self) -> None:
        service, uow = make_service()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await service.record_vehicle_position(
            _position_command((now - timedelta(days=1)).replace(tzinfo=None)), uow=uow
        )

        deleted_count = await service.prune_position_history(90, uow=uow)
        self.assertEqual(deleted_count, 0)


if __name__ == "__main__":
    unittest.main()
