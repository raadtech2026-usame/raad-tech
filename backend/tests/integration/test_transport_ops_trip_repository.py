"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyTripRepository`
(Phase 12). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `17753b338730`), not fakes — mirroring
`test_transport_ops_route_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real
identity-map/`flush_tracked_changes` mechanics (`infra/repositories.py`'s module docstring), and
`active_trip_for_vehicle`/`list_for_route`'s direct-`select()` correctness. The DB-level proof
of the `ux_trips__active_vehicle` partial unique index itself lives in
`test_postgres_repository_invariants.py`, alongside the analogous `device_assignments` tests —
not duplicated here.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown` (trips before drivers/routes, respecting the FK
constraints), leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Driver, Route, Trip
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    RouteId,
    RouteStatus,
    TripId,
    TripStatus,
    TripType,
    UserId,
    VehicleId,
)
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TripRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_trip_ids: list[str] = []
        self._created_driver_ids: list[str] = []
        self._created_route_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_trip_ids:
                await conn.execute(
                    text("DELETE FROM trips WHERE id = ANY(:ids)"),
                    {"ids": self._created_trip_ids},
                )
            if self._created_driver_ids:
                await conn.execute(
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_driver_ids},
                )
            if self._created_route_ids:
                await conn.execute(
                    text("DELETE FROM routes WHERE id = ANY(:ids)"),
                    {"ids": self._created_route_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_driver_and_route(
        self, uow: SqlAlchemyTransportOpsUnitOfWork, org_id: str
    ) -> tuple[DriverId, RouteId]:
        driver = Driver.register(
            id=DriverId(self.id_generator.new_id()),
            organization_id=OrganizationId(org_id),
            user_id=UserId(self.id_generator.new_id()),
            license_no=f"LIC-{self.tag}",
            clock=self.clock,
        )
        route = Route.create(
            id=RouteId(self.id_generator.new_id()),
            organization_id=OrganizationId(org_id),
            name=f"Route {self.tag}",
            clock=self.clock,
        )
        uow.drivers.add(driver)
        uow.routes.add(route)
        uow.record_events(driver.pull_domain_events())
        uow.record_events(route.pull_domain_events())
        await uow.commit()
        self._created_driver_ids.append(str(driver.id))
        self._created_route_ids.append(str(route.id))
        return driver.id, route.id

    async def test_add_then_get_round_trips_trip(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver_id, route_id = await self._seed_driver_and_route(uow, org_id)

        async with self._new_uow() as uow:
            trip = Trip.schedule(
                id=TripId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                vehicle_id=VehicleId(self.id_generator.new_id()),
                driver_id=driver_id,
                driver_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )
            uow.trips.add(trip)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            trip_id = trip.id
            self._created_trip_ids.append(str(trip_id))

        async with self._new_uow() as uow:
            fetched = await uow.trips.get(trip_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.status, TripStatus.SCHEDULED)
        self.assertEqual(fetched.trip_type, TripType.MORNING)
        self.assertEqual(fetched.scheduled_date, date(2026, 7, 20))

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver_id, route_id = await self._seed_driver_and_route(uow, org_id)

        async with self._new_uow() as uow:
            trip = Trip.schedule(
                id=TripId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                vehicle_id=VehicleId(self.id_generator.new_id()),
                driver_id=driver_id,
                driver_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )
            uow.trips.add(trip)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            trip_id = trip.id
            self._created_trip_ids.append(str(trip_id))

        async with self._new_uow() as uow:
            loaded = await uow.trips.get(trip_id)
            loaded.start(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.trips.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.trips.get(trip_id)

        self.assertEqual(refetched.status, TripStatus.IN_PROGRESS)
        self.assertIsNotNone(refetched.started_at)

    async def test_active_trip_for_vehicle_finds_only_in_progress_trip(self) -> None:
        org_id = self.id_generator.new_id()
        vehicle_id = VehicleId(self.id_generator.new_id())
        async with self._new_uow() as uow:
            driver_id, route_id = await self._seed_driver_and_route(uow, org_id)

        async with self._new_uow() as uow:
            none_yet = await uow.trips.active_trip_for_vehicle(vehicle_id)
        self.assertIsNone(none_yet)

        async with self._new_uow() as uow:
            trip = Trip.schedule(
                id=TripId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                vehicle_id=vehicle_id,
                driver_id=driver_id,
                driver_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )
            trip.start(clock=self.clock)
            uow.trips.add(trip)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            self._created_trip_ids.append(str(trip.id))

        async with self._new_uow() as uow:
            active = await uow.trips.active_trip_for_vehicle(vehicle_id)

        self.assertIsNotNone(active)
        self.assertEqual(str(active.id), str(trip.id))

    async def test_list_for_route_returns_only_trips_for_that_route(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver_id, route_id = await self._seed_driver_and_route(uow, org_id)

        async with self._new_uow() as uow:
            trip = Trip.schedule(
                id=TripId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                vehicle_id=VehicleId(self.id_generator.new_id()),
                driver_id=driver_id,
                driver_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )
            uow.trips.add(trip)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            self._created_trip_ids.append(str(trip.id))

        async with self._new_uow() as uow:
            trips_for_route = await uow.trips.list_for_route(route_id)

        self.assertEqual(len(trips_for_route), 1)
        self.assertEqual(str(trips_for_route[0].id), str(trip.id))


if __name__ == "__main__":
    unittest.main()
