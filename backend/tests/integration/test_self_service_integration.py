"""PostgreSQL integration tests for mobile self-service (ADR-0061): the `/me/trips`, `/me/crew`,
`/me/documents`, `/me/unavailability` and `/me/incidents` use-cases, against the real
repositories and under the tenant scope the HTTP dependency sets.

The point of every test is the same: a driver reaches only their own trips, reports and
records, and a parent only the trips their own children ride.

**Requires a reachable PostgreSQL database** (`RAAD_DB__URL`); skipped when unavailable. Rows
are created under organization ids minted for the run and deleted in `asyncTearDown`.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text

from _transport_staff_helpers import register_test_driver
from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import NotFoundError, RuleViolationError, ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.fleet_device.domain import value_objects as fleet_vo
from raad.modules.fleet_device.domain.entities import Vehicle
from raad.modules.fleet_device.infra.repositories import SqlAlchemyFleetDeviceUnitOfWork
from raad.modules.transport_ops.application.incident_services import IncidentApplicationService
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.ports import (
    VehicleDirectoryPort,
    VehicleSummary,
    VehicleSummaryPort,
)
from raad.modules.transport_ops.application.self_service import SelfServiceApplicationService
from raad.modules.transport_ops.domain.entities import (
    Parent,
    Route,
    StaffDocument,
    StaffDocumentType,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    ParentId,
    RouteId,
    StaffAssignmentKind,
    StaffDocumentId,
    StaffDocumentTypeId,
    StopId,
    StudentAssignmentId,
    StudentId,
    TripId,
    TripType,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."

CLEANUP = (
    "DELETE FROM incident_notes WHERE incident_id IN "
    "(SELECT id FROM incidents WHERE organization_id = ANY(:orgs))",
    "DELETE FROM incidents WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_covers WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_unavailability WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_documents WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_document_types WHERE organization_id = ANY(:orgs)",
    "DELETE FROM vehicle_staff_assignments WHERE organization_id = ANY(:orgs)",
    "DELETE FROM trips WHERE organization_id = ANY(:orgs)",
    "DELETE FROM student_assignments WHERE organization_id = ANY(:orgs)",
    "DELETE FROM student_parents WHERE student_id IN "
    "(SELECT id FROM students WHERE organization_id = ANY(:orgs))",
    "DELETE FROM stops WHERE route_id IN (SELECT id FROM routes WHERE organization_id = ANY(:orgs))",
    "DELETE FROM routes WHERE organization_id = ANY(:orgs)",
    "DELETE FROM drivers WHERE organization_id = ANY(:orgs)",
    "DELETE FROM transport_staff WHERE organization_id = ANY(:orgs)",
    "DELETE FROM students WHERE organization_id = ANY(:orgs)",
    "DELETE FROM parents WHERE organization_id = ANY(:orgs)",
    "DELETE FROM vehicles WHERE organization_id = ANY(:orgs)",
)


class _Directory(VehicleDirectoryPort, VehicleSummaryPort):
    """Reads `fleet_device` through its own unit of work, like the composition-root adapters."""

    def __init__(self, world: "World") -> None:
        self._world = world

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        async with self._world.fleet_uow() as uow:
            vehicle = await uow.vehicles.get(fleet_vo.VehicleId(vehicle_id))
            return str(vehicle.organization_id) if vehicle is not None else None

    async def summaries(self, vehicle_ids, *, organization_id):
        result = {}
        async with self._world.fleet_uow() as uow:
            for vehicle_id in vehicle_ids:
                vehicle = await uow.vehicles.get(fleet_vo.VehicleId(vehicle_id))
                if vehicle is not None and str(vehicle.organization_id) == organization_id:
                    result[vehicle_id] = VehicleSummary(
                        vehicle_id, str(vehicle.plate_no), vehicle.label
                    )
        return result


class World:
    """One organization with a route, a bus, two drivers and two families."""

    def __init__(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_id = self.ids.new_id()
        self.today = self.clock.now().date()
        directory = _Directory(self)
        self.operations = DailyOperationsApplicationService(
            clock=self.clock, id_generator=self.ids, vehicle_directory=directory
        )
        self.service = SelfServiceApplicationService(
            clock=self.clock,
            vehicles=directory,
            operations=self.operations,
            incidents=IncidentApplicationService(
                clock=self.clock, id_generator=self.ids, vehicle_directory=directory
            ),
        )

    def uow(self, scoped: bool = True):
        uow = SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        uow.scope = TenantRegionScope(
            organization_ids=frozenset({self.org_id}) if scoped else None
        )
        return uow

    def fleet_uow(self):
        return SqlAlchemyFleetDeviceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def cleanup(self) -> None:
        async with self.engine.begin() as conn:
            for statement in CLEANUP:
                await conn.execute(text(statement), {"orgs": [self.org_id]})
        await self.engine.dispose()

    async def seed(self) -> None:
        org = OrganizationId(self.org_id)
        async with self.fleet_uow() as uow:
            vehicle = Vehicle.register(
                id=fleet_vo.VehicleId(self.ids.new_id()),
                organization_id=fleet_vo.OrganizationId(self.org_id),
                plate_no=f"S{self.tag}",
                label="Bus One",
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            self.vehicle_id = str(vehicle.id)

        async with self.uow() as uow:
            route = Route.create(
                id=RouteId(self.ids.new_id()), organization_id=org, name="North", clock=self.clock
            )
            self.stop_ids = []
            for n in (1, 2, 3):
                stop_id = StopId(self.ids.new_id())
                route.add_stop(
                    id=stop_id,
                    name=f"Stop {n}",
                    latitude=2.0 + n / 100,
                    longitude=45.0 + n / 100,
                    sequence_no=n,
                    geofence_radius_m=150,
                    clock=self.clock,
                )
                self.stop_ids.append(str(stop_id))
            uow.routes.add(route)
            self.route_id = str(route.id)

            self.driver_a = self._driver(uow, org, "A")
            self.driver_b = self._driver(uow, org, "B")

            self.parent_a, self.student_a = self._family(uow, org, "A", self.stop_ids[0])
            self.parent_b, self.student_b = self._family(uow, org, "B", self.stop_ids[1])

            self.trip_a = self._trip(uow, org, self.driver_a, self.today, TripType.MORNING)
            self.trip_b = self._trip(uow, org, self.driver_b, self.today, TripType.AFTERNOON)
            self.trip_a_tomorrow = self._trip(
                uow, org, self.driver_a, self.today + timedelta(days=1), TripType.MORNING
            )

            crew = VehicleStaffAssignment.assign(
                id=VehicleStaffAssignmentId(self.ids.new_id()),
                organization_id=org,
                staff_id=self.driver_a["staff_id"],
                vehicle_id=VehicleId(self.vehicle_id),
                role_id=None,
                route_id=None,
                starts_on=self.today - timedelta(days=5),
                ends_on=None,
                kind=StaffAssignmentKind.PERMANENT,
                reason=None,
                clock=self.clock,
            )
            uow.staff_assignments.add(crew)

            doc_type = StaffDocumentType.create(
                id=StaffDocumentTypeId(self.ids.new_id()),
                organization_id=org,
                name="Driving licence",
                clock=self.clock,
            )
            uow.staff_document_types.add(doc_type)
            document = StaffDocument.record(
                id=StaffDocumentId(self.ids.new_id()),
                organization_id=org,
                staff_id=self.driver_a["staff_id"],
                type_id=doc_type.id,
                number="LIC-A",
                issued_on=self.today - timedelta(days=300),
                expires_on=self.today + timedelta(days=10),
                notes=None,
                replaces_id=None,
                clock=self.clock,
            )
            uow.staff_documents.add(document)
            await uow.commit()

    def _driver(self, uow, org, label):
        user_id = self.ids.new_id()
        driver = register_test_driver(
            uow,
            id=DriverId(self.ids.new_id()),
            organization_id=org,
            user_id=UserId(user_id),
            license_no=f"L{self.tag}{label}",
            clock=self.clock,
        )
        uow.drivers.add(driver)
        return {
            "id": driver.id,
            "staff_id": driver.staff_id,
            "principal": Principal(user_id=user_id, role=Role.DRIVER, org_id=self.org_id),
        }

    def _family(self, uow, org, label, pickup_stop_id):
        user_id = self.ids.new_id()
        parent = Parent.register(
            id=ParentId(self.ids.new_id()),
            organization_id=org,
            user_id=UserId(user_id),
            full_name=f"Parent {label}",
            clock=self.clock,
        )
        student = Student.enroll(
            id=StudentId(self.ids.new_id()),
            organization_id=org,
            full_name=f"Student {label}",
            clock=self.clock,
        )
        uow.parents.add(parent)
        uow.students.add(student)
        uow.student_parents.add(
            StudentParent.link(
                student_id=student.id,
                student_organization_id=org,
                parent_id=parent.id,
                parent_organization_id=org,
                relationship="parent",
                is_primary=True,
                clock=self.clock,
            )
        )
        uow.student_assignments.add(
            StudentAssignment.assign(
                id=StudentAssignmentId(self.ids.new_id()),
                organization_id=org,
                student_id=student.id,
                student_organization_id=org,
                route_id=RouteId(self.route_id),
                route_organization_id=org,
                pickup_stop_id=StopId(pickup_stop_id),
                dropoff_stop_id=StopId(self.stop_ids[2]),
                vehicle_id=VehicleId(self.vehicle_id),
                clock=self.clock,
            )
        )
        principal = Principal(user_id=user_id, role=Role.PARENT, org_id=self.org_id)
        return principal, str(student.id)

    def _trip(self, uow, org, driver, day, trip_type):
        trip = Trip.schedule(
            id=TripId(self.ids.new_id()),
            organization_id=org,
            vehicle_id=VehicleId(self.vehicle_id),
            driver_id=driver["id"],
            driver_organization_id=org,
            route_id=RouteId(self.route_id),
            route_organization_id=org,
            trip_type=trip_type,
            scheduled_date=day,
            planned_departure=time(6, 30) if trip_type is TripType.MORNING else time(13, 0),
            clock=self.clock,
        )
        uow.trips.add(trip)
        return str(trip.id)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SelfServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.world = World()
        await self.world.seed()
        self.service = self.world.service
        self.a = self.world.driver_a["principal"]
        self.b = self.world.driver_b["principal"]

    async def asyncTearDown(self) -> None:
        await self.world.cleanup()

    def uow(self):
        return self.world.uow()

    # ---- trips ---------------------------------------------------------------------------------

    async def test_a_driver_sees_only_their_own_trips(self) -> None:
        trips = await self.service.my_trips(self.a, uow=self.uow())

        self.assertEqual(
            [t.id for t in trips], [self.world.trip_a, self.world.trip_a_tomorrow]
        )
        first = trips[0]
        self.assertEqual(first.status, "scheduled")
        self.assertEqual(first.trip_type, "morning")
        self.assertEqual(first.planned_departure, time(6, 30))
        self.assertEqual(first.route_name, "North")
        self.assertEqual(first.vehicle.plate_no, f"S{self.world.tag}")
        self.assertEqual(first.students, [])
        self.assertNotIn(self.world.trip_b, [t.id for t in trips])

    async def test_a_parent_sees_the_trips_their_child_rides_and_only_their_child(self) -> None:
        trips = await self.service.my_trips(self.world.parent_a, uow=self.uow())

        self.assertEqual(
            {t.id for t in trips},
            {self.world.trip_a, self.world.trip_b, self.world.trip_a_tomorrow},
        )
        for trip in trips:
            self.assertEqual([s.student_id for s in trip.students], [self.world.student_a])
        self.assertNotIn(self.world.student_b, repr(trips))
        self.assertNotIn("Student B", repr(trips))

    async def test_a_cancelled_trip_carries_its_reason(self) -> None:
        async with self.uow() as uow:
            trip = await uow.trips.get(TripId(self.world.trip_a))
            trip.cancel(reason="Bus in the workshop", clock=self.world.clock)
            await uow.commit()

        for principal in (self.a, self.world.parent_a):
            trips = await self.service.my_trips(principal, uow=self.uow())
            cancelled = next(t for t in trips if t.id == self.world.trip_a)
            self.assertEqual(cancelled.status, "cancelled")
            self.assertEqual(cancelled.cancelled_reason, "Bus in the workshop")

    async def test_other_roles_and_unlinked_accounts_get_not_found(self) -> None:
        for principal in (
            Principal(user_id=self.world.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.world.org_id),
            Principal(user_id=self.world.ids.new_id(), role=Role.DRIVER, org_id=self.world.org_id),
            Principal(user_id=self.world.ids.new_id(), role=Role.PARENT, org_id=self.world.org_id),
        ):
            with self.assertRaises(NotFoundError):
                await self.service.my_trips(principal, uow=self.uow())

    async def test_the_window_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            await self.service.my_trips(
                self.a,
                start=self.world.today,
                end=self.world.today + timedelta(days=200),
                uow=self.uow(),
            )

    async def test_trip_detail_is_the_drivers_own_only(self) -> None:
        detail = await self.service.my_trip_detail(self.a, self.world.trip_a, uow=self.uow())

        self.assertEqual([s.name for s in detail.stops], ["Stop 1", "Stop 2", "Stop 3"])
        self.assertEqual(
            [(p.full_name, p.pickup_stop_name, p.dropoff_stop_name) for p in detail.passengers],
            [("Student A", "Stop 1", "Stop 3"), ("Student B", "Stop 2", "Stop 3")],
        )
        self.assertEqual([(m.is_me, m.is_substitute) for m in detail.crew], [(True, False)])

        with self.assertRaises(NotFoundError):
            await self.service.my_trip_detail(self.a, self.world.trip_b, uow=self.uow())
        with self.assertRaises(NotFoundError):
            await self.service.my_trip_detail(
                self.world.parent_a, self.world.trip_a, uow=self.uow()
            )

    # ---- crew and documents --------------------------------------------------------------------

    async def test_crew_of_the_buses_the_driver_works_on(self) -> None:
        (crew,) = await self.service.my_crew(self.a, uow=self.uow())

        self.assertEqual(crew.vehicle.plate_no, f"S{self.world.tag}")
        self.assertEqual([m.is_me for m in crew.members], [True])

    async def test_documents_are_the_drivers_own(self) -> None:
        mine = await self.service.my_documents(self.a, uow=self.uow())
        theirs = await self.service.my_documents(self.b, uow=self.uow())

        self.assertEqual([d.number for d in mine.documents], ["LIC-A"])
        self.assertEqual(mine.documents[0].type_name, "Driving licence")
        self.assertEqual(mine.documents[0].days_left, 10)
        self.assertEqual(mine.documents[0].status, "expiring")
        self.assertEqual(theirs.documents, [])

    # ---- unavailability ------------------------------------------------------------------------

    async def test_report_list_and_withdraw_own_unavailability(self) -> None:
        start = self.world.today + timedelta(days=2)
        created = await self.service.report_unavailability(
            self.a, starts_on=start, ends_on=start, reason="sick", note="Flu", uow=self.uow()
        )

        mine = await self.service.my_unavailability(self.a, uow=self.uow())
        self.assertEqual([(u.id, u.reason, u.note, u.is_withdrawn) for u in mine],
                         [(created.id, "sick", "Flu", False)])
        self.assertEqual(await self.service.my_unavailability(self.b, uow=self.uow()), [])

        with self.assertRaises(RuleViolationError):
            await self.service.report_unavailability(
                self.a, starts_on=start, ends_on=start, reason="personal", note=None, uow=self.uow()
            )
        with self.assertRaises(NotFoundError):
            await self.service.withdraw_my_unavailability(self.b, created.id, uow=self.uow())

        await self.service.withdraw_my_unavailability(self.a, created.id, uow=self.uow())
        mine = await self.service.my_unavailability(self.a, uow=self.uow())
        self.assertTrue(mine[0].is_withdrawn)

    async def test_unavailability_rules(self) -> None:
        today = self.world.today
        with self.assertRaises(ValidationError):
            await self.service.report_unavailability(
                self.a, starts_on=today - timedelta(days=1), ends_on=today, reason="sick",
                note=None, uow=self.uow(),
            )
        with self.assertRaises(ValidationError):
            await self.service.report_unavailability(
                self.a, starts_on=today + timedelta(days=3), ends_on=today + timedelta(days=2),
                reason="sick", note=None, uow=self.uow(),
            )
        with self.assertRaises(ValidationError):
            await self.service.report_unavailability(
                self.a, starts_on=today, ends_on=today + timedelta(days=60), reason="sick",
                note=None, uow=self.uow(),
            )
        with self.assertRaises(NotFoundError):
            await self.service.report_unavailability(
                self.world.parent_a, starts_on=today, ends_on=today, reason="sick", note=None,
                uow=self.uow(),
            )

    # ---- incidents -----------------------------------------------------------------------------

    async def test_report_an_incident_and_see_only_own_reports(self) -> None:
        created = await self.service.report_incident(
            self.a,
            category="breakdown",
            severity="high",
            occurred_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            title="Flat tyre near Stop 2",
            description="Changed the wheel, 20 minutes late.",
            trip_id=self.world.trip_a,
            uow=self.uow(),
        )

        mine = await self.service.my_incidents(self.a, uow=self.uow())
        self.assertEqual([i.id for i in mine], [created.id])
        self.assertEqual(mine[0].status, "open")
        self.assertEqual(mine[0].title, "Flat tyre near Stop 2")
        self.assertEqual(mine[0].trip_id, self.world.trip_a)
        self.assertEqual(await self.service.my_incidents(self.b, uow=self.uow()), [])

        # The office sees it in its own log, on the right bus, with the reporter attached.
        async with self.uow() as uow:
            (incident,) = await uow.incidents.list_filtered()
            self.assertEqual(str(incident.vehicle_id), self.world.vehicle_id)
            self.assertEqual(incident.reported_by_staff_id, str(self.world.driver_a["staff_id"]))
            self.assertEqual(incident.staff_ids, (str(self.world.driver_a["staff_id"]),))

    async def test_an_incident_cannot_name_another_drivers_trip(self) -> None:
        with self.assertRaises(NotFoundError):
            await self.service.report_incident(
                self.a,
                category="delay",
                severity="low",
                occurred_at=None,
                title="Late start",
                description=None,
                trip_id=self.world.trip_b,
                uow=self.uow(),
            )
        with self.assertRaises(NotFoundError):
            await self.service.report_incident(
                self.world.parent_a,
                category="delay",
                severity="low",
                occurred_at=None,
                title="Late start",
                description=None,
                trip_id=None,
                uow=self.uow(),
            )

    # ---- notification recipients ---------------------------------------------------------------

    async def test_notification_recipient_lookups(self) -> None:
        trip, user_id = await self.service.driver_user_id_for_trip(
            self.world.trip_a, uow=self.world.uow(scoped=False)
        )
        self.assertEqual(str(trip.id), self.world.trip_a)
        self.assertEqual(user_id, self.a.user_id)
        self.assertEqual(
            await self.service.user_id_for_staff(
                str(self.world.driver_b["staff_id"]), uow=self.world.uow(scoped=False)
            ),
            self.b.user_id,
        )
        self.assertEqual(
            await self.service.driver_user_id_for_trip(
                self.world.ids.new_id(), uow=self.world.uow(scoped=False)
            ),
            (None, None),
        )


if __name__ == "__main__":
    unittest.main()
