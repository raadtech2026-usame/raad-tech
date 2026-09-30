"""Daily transport operations against real PostgreSQL (ADR-0052..0054).

What only the database can show: the partial unique index on trips, the `cancelled` enum value,
`TIME`/`SMALLINT[]` round trips, a cover's crew row + cover + trip changes flushing in one commit,
cancellation recipients through real joins, and tenant scope on the board.

**Requires a reachable PostgreSQL database** at `RAAD_DB__URL`, migrated to head.
"""

from __future__ import annotations

import unittest
from datetime import date, time, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ConflictError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.application.commands import (
    CancelTripCommand,
    CreateCoverCommand,
    GenerateTripsCommand,
    RecordUnavailabilityCommand,
    SaveTimetableEntryCommand,
    ScheduleTripCommand,
)
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.ports import VehicleDirectoryPort
from raad.modules.transport_ops.application.services import TripApplicationService
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Student,
    StudentAssignment,
    StudentParent,
    TransportStaff,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    ParentId,
    RouteId,
    StopId,
    StudentAssignmentId,
    StudentId,
    TransportStaffId,
    UserId,
    VehicleId,
)
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."

_CLEANUP = (
    "DELETE FROM staff_covers WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_unavailability WHERE organization_id = ANY(:orgs)",
    "DELETE FROM vehicle_staff_assignments WHERE organization_id = ANY(:orgs)",
    "DELETE FROM trips WHERE organization_id = ANY(:orgs)",
    "DELETE FROM route_timetable_entries WHERE organization_id = ANY(:orgs)",
    "DELETE FROM operating_closures WHERE organization_id = ANY(:orgs)",
    "DELETE FROM student_assignments WHERE organization_id = ANY(:orgs)",
    "DELETE FROM student_parents WHERE student_id IN (SELECT id FROM students WHERE organization_id = ANY(:orgs))",
    "DELETE FROM stops WHERE route_id IN (SELECT id FROM routes WHERE organization_id = ANY(:orgs))",
    "DELETE FROM routes WHERE organization_id = ANY(:orgs)",
    "DELETE FROM drivers WHERE organization_id = ANY(:orgs)",
    "DELETE FROM transport_staff WHERE organization_id = ANY(:orgs)",
    "DELETE FROM parents WHERE organization_id = ANY(:orgs)",
    "DELETE FROM students WHERE organization_id = ANY(:orgs)",
)


class _Vehicles(VehicleDirectoryPort):
    def __init__(self, owners: dict[str, str]) -> None:
        self.owners = owners

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        return self.owners.get(vehicle_id)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DailyOperationsPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = build_engine(get_settings().db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.today = self.clock.now().date()
        self.org = self.ids.new_id()
        self.other_org = self.ids.new_id()
        self.bus = self.ids.new_id()
        self.admin = Principal(user_id=self.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.org)
        self.service = DailyOperationsApplicationService(
            clock=self.clock, id_generator=self.ids, vehicle_directory=_Vehicles({self.bus: self.org})
        )
        self.trips = TripApplicationService(clock=self.clock, id_generator=self.ids)
        await self._seed()

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for statement in _CLEANUP:
                await conn.execute(text(statement), {"orgs": [self.org, self.other_org]})
        await self.engine.dispose()

    def uow(self, *orgs: str) -> SqlAlchemyTransportOpsUnitOfWork:
        uow = SqlAlchemyTransportOpsUnitOfWork(self.session_factory, OutboxWriter(), AuditWriter())
        if orgs:
            uow.scope = TenantRegionScope(organization_ids=frozenset(orgs))
        return uow

    async def _seed(self) -> None:
        org = OrganizationId(self.org)
        async with self.uow() as uow:
            route = Route.create(id=RouteId(self.ids.new_id()), organization_id=org, name=f"R {self.org[-6:]}", clock=self.clock)
            stop_a = route.add_stop(id=StopId(self.ids.new_id()), name="A", latitude=2.0, longitude=45.0, sequence_no=1, clock=self.clock)
            stop_b = route.add_stop(id=StopId(self.ids.new_id()), name="B", latitude=2.1, longitude=45.1, sequence_no=2, clock=self.clock)
            uow.routes.add(route)
            self.route_id = str(route.id)
            self.drivers: list[Driver] = []
            self.staff: list[TransportStaff] = []
            for name in ("Amina", "Hassan"):
                person = TransportStaff.register(id=TransportStaffId(self.ids.new_id()), organization_id=org, full_name=name, clock=self.clock)
                uow.staff.add(person)
                driver = Driver.register(
                    id=DriverId(self.ids.new_id()), organization_id=org, user_id=UserId(self.ids.new_id()),
                    license_no=f"DL-{name}", staff_id=person.id, clock=self.clock,
                )
                uow.drivers.add(driver)
                self.staff.append(person)
                self.drivers.append(driver)
            student = Student.enroll(id=StudentId(self.ids.new_id()), organization_id=org, full_name="Child", clock=self.clock)
            uow.students.add(student)
            self.parent_user = self.ids.new_id()
            parent = Parent.register(id=ParentId(self.ids.new_id()), organization_id=org, user_id=UserId(self.parent_user), full_name="Parent", clock=self.clock)
            uow.parents.add(parent)
            for aggregate in (route, student, parent, *self.staff, *self.drivers):
                uow.record_events(aggregate.pull_domain_events())
            await uow.commit()
        async with self.uow() as uow:
            link = StudentParent.link(
                student_id=student.id, student_organization_id=org, parent_id=parent.id,
                parent_organization_id=org, is_primary=True, clock=self.clock,
            )
            uow.student_parents.add(link)
            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self.ids.new_id()), organization_id=org, student_id=student.id,
                student_organization_id=org, route_id=route.id, route_organization_id=org,
                pickup_stop_id=stop_a.id, dropoff_stop_id=stop_b.id, vehicle_id=VehicleId(self.bus), clock=self.clock,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(link.pull_domain_events() + assignment.pull_domain_events())
            await uow.commit()
        await self.service.save_timetable_entry(
            SaveTimetableEntryCommand(
                organization_id=self.org, route_id=self.route_id, vehicle_id=self.bus, trip_type="morning",
                weekdays=(1, 2, 3, 4, 5, 6, 7), default_driver_id=str(self.drivers[0].id),
                valid_from=self.today, planned_departure=time(6, 45), actor=self.admin,
            ),
            uow=self.uow(),
        )

    async def test_generation_round_trips_and_the_index_blocks_duplicates(self) -> None:
        result = await self.service.generate_trips(GenerateTripsCommand(actor=self.admin, days=3), uow=self.uow())
        self.assertEqual(result.created, 3)
        again = await self.service.generate_trips(GenerateTripsCommand(actor=self.admin, days=3), uow=self.uow())
        self.assertEqual(again.created, 0)
        entries = await self.service.list_timetable(uow=self.uow())
        self.assertEqual(entries[0].weekdays, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(entries[0].planned_departure, time(6, 45))
        with self.assertRaises(ConflictError):
            await self.trips.schedule_trip(
                ScheduleTripCommand(
                    organization_id=self.org, vehicle_id=self.bus, driver_id=str(self.drivers[1].id),
                    route_id=self.route_id, trip_type="morning", scheduled_date=self.today, actor=self.admin,
                ),
                uow=self.uow(),
            )
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO trips (id, created_at, updated_at, row_version, organization_id, vehicle_id, "
                        "driver_id, route_id, trip_type, status, scheduled_date) VALUES (:id, now(), now(), 1, "
                        ":org, :bus, :driver, :route, 'morning', 'scheduled', :day)"
                    ),
                    {"id": self.ids.new_id(), "org": self.org, "bus": self.bus, "driver": str(self.drivers[1].id),
                     "route": self.route_id, "day": self.today},
                )

    async def test_cancel_frees_the_slot_and_finds_the_parents(self) -> None:
        await self.service.generate_trips(GenerateTripsCommand(actor=self.admin, days=1), uow=self.uow())
        board = await self.service.daily_board(self.today, uow=self.uow())
        trip_id = board.vehicles[0].trips[0].id
        cancelled = await self.trips.cancel_trip(CancelTripCommand(trip_id=trip_id, reason="Breakdown", actor=self.admin), uow=self.uow())
        self.assertEqual((cancelled.status, cancelled.cancelled_reason), ("cancelled", "Breakdown"))
        trip, users = await self.service.parent_user_ids_for_trip(trip_id, uow=self.uow())
        self.assertEqual(users, [self.parent_user])
        # A replacement is allowed; generation still does not recreate the cancelled one.
        replacement = await self.trips.schedule_trip(
            ScheduleTripCommand(
                organization_id=self.org, vehicle_id=self.bus, driver_id=str(self.drivers[1].id),
                route_id=self.route_id, trip_type="morning", scheduled_date=self.today, actor=self.admin,
            ),
            uow=self.uow(),
        )
        self.assertEqual(replacement.status, "scheduled")

    async def test_cover_writes_crew_cover_and_trips_in_one_commit(self) -> None:
        await self.service.generate_trips(GenerateTripsCommand(actor=self.admin, days=2), uow=self.uow())
        absence = await self.service.record_unavailability(
            RecordUnavailabilityCommand(
                staff_id=str(self.staff[0].id), starts_on=self.today, ends_on=self.today + timedelta(days=1),
                reason="sick", note="private", actor=self.admin,
            ),
            uow=self.uow(),
        )
        self.assertEqual((await self.service.daily_board(self.today, uow=self.uow())).uncovered_trips, 1)
        cover = await self.service.create_cover(
            CreateCoverCommand(unavailability_id=absence.id, substitute_staff_id=str(self.staff[1].id), vehicle_id=self.bus, actor=self.admin),
            uow=self.uow(),
        )
        self.assertEqual(cover.trips_reassigned, 2)
        board = await self.service.daily_board(self.today, uow=self.uow())
        self.assertEqual(board.uncovered_trips, 0)
        self.assertEqual(board.vehicles[0].trips[0].driver_name, "Hassan")
        self.assertTrue(any(c.is_substitute for c in board.vehicles[0].crew))
        alerts = await self.service.collect_uncovered_alerts(uow=self.uow())
        self.assertEqual([a for a in alerts if a.organization_id == self.org], [])

    async def test_other_organizations_see_nothing(self) -> None:
        await self.service.generate_trips(GenerateTripsCommand(actor=self.admin, days=1), uow=self.uow())
        board = await self.service.daily_board(self.today, uow=self.uow(self.other_org))
        self.assertEqual(board.vehicles, [])
        self.assertEqual(await self.service.list_timetable(uow=self.uow(self.other_org)), [])


if __name__ == "__main__":
    unittest.main()
