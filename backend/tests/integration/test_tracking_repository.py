"""PostgreSQL-backed integration test for `tracking`'s `SqlAlchemyVehiclePositionRepository`/
`SqlAlchemyGeofenceCrossingRepository`. Stdlib `unittest` — no `pytest` (not an approved
dependency) — against the real `SqlAlchemyTrackingUnitOfWork` and the live migrated schema,
not fakes, mirroring `test_transport_ops_driver_repository.py`'s skip-guard/cleanup pattern.

**Closes a real, previously-flagged gap**: CLAUDE.md's own "Known gaps" section names Tracking
as one of four modules with no dedicated live-DB integration test file — its
`SqlAlchemyUnitOfWork` wiring was exercised only indirectly. `test_tracking_redis_latest_position.py`
already covers the Redis-backed `LatestPositionPort`; this file covers the Postgres-backed
history repositories that one deliberately does not (Database Design §7.1: "Latest position is
NOT read from here").

All cross-module ids on `VehiclePosition`/`GeofenceCrossing` (`organization_id`, `vehicle_id`,
`device_id`, `trip_id`, `stop_id`) are `tracking`'s own opaque, non-empty-string value objects
(`domain/value_objects.py`) — no `fleet_device`/`transport_ops` row needs to exist first.
`VehiclePosition` is a plain entity, not an aggregate root (`domain/entities.py`'s own
docstring explains why no domain event is recorded for it), so these tests never call
`pull_domain_events()` on it.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import timedelta

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import CursorPageRequest, FilterCondition
from raad.core.time.clock import SystemClock
from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.value_objects import (
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeoPoint,
    OrganizationId,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)
from raad.modules.tracking.infra.repositories import SqlAlchemyTrackingUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VehiclePositionAndGeofenceCrossingRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_position_ids: list[str] = []
        self._created_crossing_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_position_ids:
                await conn.execute(
                    text("DELETE FROM vehicle_positions WHERE id = ANY(:ids)"),
                    {"ids": self._created_position_ids},
                )
            if self._created_crossing_ids:
                await conn.execute(
                    text("DELETE FROM geofence_events WHERE id = ANY(:ids)"),
                    {"ids": self._created_crossing_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTrackingUnitOfWork:
        return SqlAlchemyTrackingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_position_add_then_get_round_trips_all_fields(self) -> None:
        vehicle_id = self.id_generator.new_id()
        trip_id = self.id_generator.new_id()
        event_time = self.clock.now()
        async with self._new_uow() as uow:
            position = VehiclePosition.record(
                id=VehiclePositionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                vehicle_id=VehicleId(vehicle_id),
                device_id=DeviceId(self.id_generator.new_id()),
                trip_id=TripId(trip_id),
                position=GeoPoint(latitude=2.0469, longitude=45.3182),
                event_time=event_time,
                clock=self.clock,
            )
            uow.vehicle_positions.add(position)
            await uow.commit()
            position_id = position.id
            self._created_position_ids.append(str(position_id))

        async with self._new_uow() as uow:
            fetched = await uow.vehicle_positions.get(position_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.vehicle_id), vehicle_id)
        self.assertEqual(str(fetched.trip_id), trip_id)
        self.assertAlmostEqual(fetched.position.latitude, 2.0469, places=5)
        self.assertAlmostEqual(fetched.position.longitude, 45.3182, places=5)
        self.assertFalse(fetched.is_backfill)

    async def test_position_list_for_trip_returns_only_that_trips_positions(self) -> None:
        trip_id = self.id_generator.new_id()
        other_trip_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            for offset in range(2):
                position = VehiclePosition.record(
                    id=VehiclePositionId(self.id_generator.new_id()),
                    organization_id=OrganizationId(self.id_generator.new_id()),
                    vehicle_id=VehicleId(self.id_generator.new_id()),
                    device_id=DeviceId(self.id_generator.new_id()),
                    trip_id=TripId(trip_id),
                    position=GeoPoint(latitude=2.0, longitude=45.0),
                    event_time=self.clock.now() + timedelta(seconds=offset),
                    clock=self.clock,
                )
                uow.vehicle_positions.add(position)
                self._created_position_ids.append(str(position.id))
            other = VehiclePosition.record(
                id=VehiclePositionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                vehicle_id=VehicleId(self.id_generator.new_id()),
                device_id=DeviceId(self.id_generator.new_id()),
                trip_id=TripId(other_trip_id),
                position=GeoPoint(latitude=2.0, longitude=45.0),
                event_time=self.clock.now(),
                clock=self.clock,
            )
            uow.vehicle_positions.add(other)
            self._created_position_ids.append(str(other.id))
            await uow.commit()

        async with self._new_uow() as uow:
            for_trip = await uow.vehicle_positions.list_for_trip(TripId(trip_id))

        self.assertEqual(len(for_trip), 2)
        self.assertTrue(all(str(p.trip_id) == trip_id for p in for_trip))

    async def test_position_delete_before_prunes_only_older_rows(self) -> None:
        vehicle_id = self.id_generator.new_id()
        now = self.clock.now()
        async with self._new_uow() as uow:
            old_position = VehiclePosition.record(
                id=VehiclePositionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                vehicle_id=VehicleId(vehicle_id),
                device_id=DeviceId(self.id_generator.new_id()),
                position=GeoPoint(latitude=2.0, longitude=45.0),
                event_time=now - timedelta(days=200),
                clock=self.clock,
            )
            recent_position = VehiclePosition.record(
                id=VehiclePositionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                vehicle_id=VehicleId(vehicle_id),
                device_id=DeviceId(self.id_generator.new_id()),
                position=GeoPoint(latitude=2.0, longitude=45.0),
                event_time=now,
                clock=self.clock,
            )
            uow.vehicle_positions.add(old_position)
            uow.vehicle_positions.add(recent_position)
            await uow.commit()
            self._created_position_ids.append(str(recent_position.id))
            old_id = old_position.id

        async with self._new_uow() as uow:
            deleted_count = await uow.vehicle_positions.delete_before(now - timedelta(days=90))
            await uow.commit()

        self.assertGreaterEqual(deleted_count, 1)
        async with self._new_uow() as uow:
            self.assertIsNone(await uow.vehicle_positions.get(old_id))
            self.assertIsNotNone(await uow.vehicle_positions.get(recent_position.id))

    async def test_geofence_crossing_add_then_get_round_trips(self) -> None:
        trip_id = self.id_generator.new_id()
        stop_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            crossing = GeofenceCrossing.approaching_stop(
                id=GeofenceCrossingId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                trip_id=TripId(trip_id),
                stop_id=StopId(stop_id),
                clock=self.clock,
            )
            uow.geofence_crossings.add(crossing)
            uow.record_events(crossing.pull_domain_events())
            await uow.commit()
            crossing_id = crossing.id
            self._created_crossing_ids.append(str(crossing_id))

        async with self._new_uow() as uow:
            fetched = await uow.geofence_crossings.get(crossing_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.trip_id), trip_id)
        self.assertEqual(str(fetched.stop_id), stop_id)
        self.assertEqual(fetched.event_type, GeofenceEventType.APPROACHING_STOP)

    async def test_geofence_crossing_latest_for_trip_finds_most_recent(self) -> None:
        trip_id = self.id_generator.new_id()
        stop_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            first = GeofenceCrossing.approaching_stop(
                id=GeofenceCrossingId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                trip_id=TripId(trip_id),
                stop_id=StopId(stop_id),
                clock=self.clock,
            )
            uow.geofence_crossings.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()
            self._created_crossing_ids.append(str(first.id))

        async with self._new_uow() as uow:
            second = GeofenceCrossing.approaching_stop(
                id=GeofenceCrossingId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                trip_id=TripId(trip_id),
                stop_id=StopId(stop_id),
                clock=self.clock,
            )
            uow.geofence_crossings.add(second)
            uow.record_events(second.pull_domain_events())
            await uow.commit()
            self._created_crossing_ids.append(str(second.id))

        async with self._new_uow() as uow:
            latest = await uow.geofence_crossings.latest_for_trip(
                TripId(trip_id),
                stop_id=StopId(stop_id),
                event_type=GeofenceEventType.APPROACHING_STOP,
            )

        self.assertIsNotNone(latest)
        self.assertEqual(str(latest.id), str(second.id))


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VehiclePositionPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyVehiclePositionRepository.list_for_trip_page`
    (Pagination/Filtering/Sorting phase) against real SQL — the cursor-pagination analogue of
    `OrganizationPaginationRepositoryTests`/`UserPaginationRepositoryTests` (offset mode).
    Every test seeds its own trip's positions with distinct, ascending `event_time`s and
    cleans them up in `asyncTearDown`, mirroring this file's other test class."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_position_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_position_ids:
                await conn.execute(
                    text("DELETE FROM vehicle_positions WHERE id = ANY(:ids)"),
                    {"ids": self._created_position_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTrackingUnitOfWork:
        return SqlAlchemyTrackingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_positions(
        self, *, trip_id: str, vehicle_id: str, count: int, start_offset: int = 0
    ) -> list[str]:
        """Seeds `count` positions on `trip_id`/`vehicle_id`, each one second apart and
        strictly ascending in `event_time`, returning their ids in that same ascending order."""
        base = self.clock.now()
        ids: list[str] = []
        async with self._new_uow() as uow:
            for i in range(count):
                position = VehiclePosition.record(
                    id=VehiclePositionId(self.id_generator.new_id()),
                    organization_id=OrganizationId(self.id_generator.new_id()),
                    vehicle_id=VehicleId(vehicle_id),
                    device_id=DeviceId(self.id_generator.new_id()),
                    trip_id=TripId(trip_id),
                    position=GeoPoint(latitude=2.0, longitude=45.0),
                    event_time=base + timedelta(seconds=start_offset + i),
                    clock=self.clock,
                )
                uow.vehicle_positions.add(position)
                self._created_position_ids.append(str(position.id))
                ids.append(str(position.id))
            await uow.commit()
        return ids

    async def test_list_for_trip_page_small_limit_reports_has_more_and_next_cursor(
        self,
    ) -> None:
        trip_id = self.id_generator.new_id()
        vehicle_id = self.id_generator.new_id()
        await self._seed_positions(trip_id=trip_id, vehicle_id=vehicle_id, count=5)

        async with self._new_uow() as uow:
            page = await uow.vehicle_positions.list_for_trip_page(
                TripId(trip_id), CursorPageRequest(limit=2), filters=[]
            )

        self.assertEqual(len(page.data), 2)
        self.assertTrue(page.has_more)
        self.assertIsNotNone(page.next_cursor)

    async def test_list_for_trip_page_following_cursor_yields_all_rows_ascending_no_duplicates(
        self,
    ) -> None:
        trip_id = self.id_generator.new_id()
        vehicle_id = self.id_generator.new_id()
        expected_ids = await self._seed_positions(
            trip_id=trip_id, vehicle_id=vehicle_id, count=5
        )

        collected: list = []
        cursor: str | None = None
        async with self._new_uow() as uow:
            while True:
                page = await uow.vehicle_positions.list_for_trip_page(
                    TripId(trip_id),
                    CursorPageRequest(limit=2, cursor=cursor),
                    filters=[],
                )
                collected.extend(page.data)
                if not page.has_more:
                    break
                cursor = page.next_cursor

        self.assertEqual(len(collected), 5)
        collected_ids = [str(p.id) for p in collected]
        self.assertEqual(len(set(collected_ids)), 5)  # no duplicates
        self.assertEqual(collected_ids, expected_ids)  # ascending event_time order
        event_times = [p.event_time for p in collected]
        self.assertEqual(event_times, sorted(event_times))

    async def test_list_for_trip_page_filters_by_vehicle_id(self) -> None:
        trip_id = self.id_generator.new_id()
        vehicle_a = self.id_generator.new_id()
        vehicle_b = self.id_generator.new_id()
        await self._seed_positions(
            trip_id=trip_id, vehicle_id=vehicle_a, count=2
        )
        await self._seed_positions(
            trip_id=trip_id, vehicle_id=vehicle_b, count=3, start_offset=100
        )

        async with self._new_uow() as uow:
            page = await uow.vehicle_positions.list_for_trip_page(
                TripId(trip_id),
                CursorPageRequest(limit=10),
                filters=[
                    FilterCondition(field="vehicle_id", op="eq", value=vehicle_b)
                ],
            )

        self.assertEqual(len(page.data), 3)
        self.assertTrue(all(str(p.vehicle_id) == vehicle_b for p in page.data))

    async def test_list_for_trip_page_rejects_unwhitelisted_filter_field(self) -> None:
        trip_id = self.id_generator.new_id()
        vehicle_id = self.id_generator.new_id()
        await self._seed_positions(trip_id=trip_id, vehicle_id=vehicle_id, count=1)

        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.vehicle_positions.list_for_trip_page(
                    TripId(trip_id),
                    CursorPageRequest(),
                    filters=[
                        FilterCondition(field="latitude", op="eq", value="2.0")
                    ],
                )


if __name__ == "__main__":
    unittest.main()
