"""PostgreSQL integration tests for `MeApplicationService.get_my_transport` (ADR-0060,
`GET /me/transport`).

The unit tests prove the composition against fakes. These prove it against the real
repositories: the real assignment, route, stop, trip and vehicle queries, and the real tenant
scope the route's `Depends(get_transport_ops_uow)`/`Depends(get_fleet_device_uow)` apply.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL`. Skipped (not
failed) when unavailable. Every row is created under organization ids minted for this run and
deleted in `asyncTearDown`.
"""

from __future__ import annotations

import unittest
import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy import text

from _transport_staff_helpers import register_test_driver
from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.fleet_device.application.services import VehicleApplicationService
from raad.modules.fleet_device.domain import value_objects as fleet_vo
from raad.modules.fleet_device.domain.entities import Vehicle
from raad.modules.fleet_device.infra.repositories import SqlAlchemyFleetDeviceUnitOfWork
from raad.modules.iam.application.services import MeApplicationService
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)
from raad.modules.transport_ops.domain.entities import (
    Parent,
    Route,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    ParentId,
    RouteId,
    StopId,
    StudentAssignmentId,
    StudentId,
    TripId,
    TripType,
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


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class MeTransportIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_id = self.ids.new_id()
        self.other_org_id = self.ids.new_id()
        self.service = MeApplicationService(
            parent_service=ParentApplicationService(
                clock=self.clock,
                id_generator=self.ids,
                user_provisioning=None,  # type: ignore[arg-type]
            ),
            driver_service=DriverApplicationService(
                clock=self.clock,
                id_generator=self.ids,
                user_provisioning=None,  # type: ignore[arg-type]
            ),
            student_parent_service=StudentParentApplicationService(clock=self.clock),
            student_assignment_service=StudentAssignmentApplicationService(
                clock=self.clock, id_generator=self.ids
            ),
            route_service=RouteApplicationService(clock=self.clock, id_generator=self.ids),
            trip_service=TripApplicationService(clock=self.clock, id_generator=self.ids),
            vehicle_service=VehicleApplicationService(clock=self.clock, id_generator=self.ids),
        )

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for statement in _CLEANUP:
                await conn.execute(
                    text(statement), {"orgs": [self.org_id, self.other_org_id]}
                )
        await self.engine.dispose()

    # --- units of work, scoped the way the HTTP dependencies scope them ------------------

    def _scope(self, organization_id: str | None) -> TenantRegionScope:
        return TenantRegionScope(
            organization_ids=None if organization_id is None else frozenset({organization_id})
        )

    def _transport_uow(self, organization_id: str | None = None):
        uow = SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        # Set the way `get_transport_ops_uow` sets it (ADR-0021).
        uow.scope = self._scope(organization_id)
        return uow

    def _fleet_uow(self, organization_id: str | None = None):
        uow = SqlAlchemyFleetDeviceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        uow.scope = self._scope(organization_id)
        return uow

    async def _call(self, principal: Principal):
        return await self.service.get_my_transport(
            principal,
            uow=self._transport_uow(self.org_id),
            fleet_device_uow=self._fleet_uow(self.org_id),
        )

    # --- seeding ------------------------------------------------------------------------

    async def _seed_vehicle(self, *, label: str, organization_id: str | None = None) -> str:
        organization_id = organization_id or self.org_id
        async with self._fleet_uow() as uow:
            vehicle = Vehicle.register(
                id=fleet_vo.VehicleId(self.ids.new_id()),
                organization_id=fleet_vo.OrganizationId(organization_id),
                plate_no=f"T{self.tag}{label}",
                label=f"Bus {label}",
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            return str(vehicle.id)

    async def _seed_route(self, *, label: str, stop_count: int) -> tuple[str, list[str]]:
        async with self._transport_uow() as uow:
            route = Route.create(
                id=RouteId(self.ids.new_id()),
                organization_id=OrganizationId(self.org_id),
                name=f"Route {label} {self.tag}",
                clock=self.clock,
            )
            stop_ids: list[str] = []
            for sequence_no in range(1, stop_count + 1):
                stop_id = StopId(self.ids.new_id())
                route.add_stop(
                    id=stop_id,
                    name=f"Stop {label}{sequence_no}",
                    latitude=2.0 + sequence_no / 100,
                    longitude=45.0 + sequence_no / 100,
                    sequence_no=sequence_no,
                    geofence_radius_m=150,
                    clock=self.clock,
                )
                stop_ids.append(str(stop_id))
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return str(route.id), stop_ids

    async def _seed_family(
        self,
        *,
        label: str,
        route_id: str | None,
        pickup: str | None = None,
        dropoff: str | None = None,
        vehicle_id: str | None = None,
    ) -> tuple[Principal, str]:
        user_id = self.ids.new_id()
        org = OrganizationId(self.org_id)
        async with self._transport_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.ids.new_id()),
                organization_id=org,
                user_id=UserId(user_id),
                full_name=f"Parent {label} {self.tag}",
                clock=self.clock,
            )
            student = Student.enroll(
                id=StudentId(self.ids.new_id()),
                organization_id=org,
                full_name=f"Student {label} {self.tag}",
                clock=self.clock,
            )
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=org,
                parent_id=parent.id,
                parent_organization_id=org,
                relationship="parent",
                is_primary=True,
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.students.add(student)
            uow.student_parents.add(link)
            events = [*parent.pull_domain_events(), *student.pull_domain_events()]
            if route_id is not None:
                assignment = StudentAssignment.assign(
                    id=StudentAssignmentId(self.ids.new_id()),
                    organization_id=org,
                    student_id=student.id,
                    student_organization_id=org,
                    route_id=RouteId(route_id),
                    route_organization_id=org,
                    pickup_stop_id=StopId(pickup),
                    dropoff_stop_id=StopId(dropoff),
                    vehicle_id=VehicleId(vehicle_id) if vehicle_id is not None else None,
                    clock=self.clock,
                )
                uow.student_assignments.add(assignment)
                events.extend(assignment.pull_domain_events())
            uow.record_events(events)
            await uow.commit()
        return Principal(user_id=user_id, role=Role.PARENT, org_id=self.org_id), str(student.id)

    async def _seed_trip(self, *, vehicle_id: str, route_id: str, start: bool) -> str:
        org = OrganizationId(self.org_id)
        async with self._transport_uow() as uow:
            driver = register_test_driver(
                uow,
                id=DriverId(self.ids.new_id()),
                organization_id=org,
                user_id=UserId(self.ids.new_id()),
                license_no=f"L{self.tag}{vehicle_id[-4:]}",
                clock=self.clock,
            )
            trip = Trip.schedule(
                id=TripId(self.ids.new_id()),
                organization_id=org,
                vehicle_id=VehicleId(vehicle_id),
                driver_id=driver.id,
                driver_organization_id=org,
                route_id=RouteId(route_id),
                route_organization_id=org,
                trip_type=TripType.MORNING,
                scheduled_date=date.today(),
                clock=self.clock,
            )
            if start:
                trip.start(clock=self.clock)
            uow.drivers.add(driver)
            uow.trips.add(trip)
            uow.record_events([*driver.pull_domain_events(), *trip.pull_domain_events()])
            await uow.commit()
            return str(trip.id)

    # --- tests --------------------------------------------------------------------------

    async def test_child_bus_route_own_stops_and_running_trip(self) -> None:
        vehicle_id = await self._seed_vehicle(label="A")
        route_id, stops = await self._seed_route(label="A", stop_count=4)
        principal, student_id = await self._seed_family(
            label="A", route_id=route_id, pickup=stops[1], dropoff=stops[3], vehicle_id=vehicle_id
        )
        trip_id = await self._seed_trip(vehicle_id=vehicle_id, route_id=route_id, start=True)

        (item,) = await self._call(principal)

        self.assertEqual(item.student_id, student_id)
        self.assertEqual(item.assignment.route.id, route_id)
        self.assertEqual(item.assignment.route.name, f"Route A {self.tag}")
        self.assertEqual(item.assignment.pickup_stop.id, stops[1])
        self.assertEqual(item.assignment.pickup_stop.name, "Stop A2")
        self.assertAlmostEqual(item.assignment.pickup_stop.latitude, 2.02, places=5)
        self.assertAlmostEqual(item.assignment.pickup_stop.longitude, 45.02, places=5)
        self.assertEqual(item.assignment.dropoff_stop.id, stops[3])
        self.assertEqual(item.assignment.vehicle.id, vehicle_id)
        self.assertEqual(item.assignment.vehicle.plate_no, f"T{self.tag}A")
        self.assertEqual(item.current_trip.id, trip_id)
        self.assertEqual(item.current_trip.status, "in_progress")
        self.assertEqual(item.current_trip.trip_type, "morning")
        self.assertIsNotNone(item.current_trip.started_at)
        # The route's other two stops belong to other families.
        payload = repr(asdict(item))
        self.assertNotIn(stops[0], payload)
        self.assertNotIn(stops[2], payload)

    async def test_a_scheduled_trip_is_not_the_current_trip(self) -> None:
        vehicle_id = await self._seed_vehicle(label="S")
        route_id, stops = await self._seed_route(label="S", stop_count=2)
        principal, _ = await self._seed_family(
            label="S", route_id=route_id, pickup=stops[0], dropoff=stops[1], vehicle_id=vehicle_id
        )
        await self._seed_trip(vehicle_id=vehicle_id, route_id=route_id, start=False)

        (item,) = await self._call(principal)

        self.assertIsNone(item.current_trip)
        self.assertEqual(item.assignment.vehicle.id, vehicle_id)

    async def test_a_trip_on_another_route_is_not_the_childs(self) -> None:
        vehicle_id = await self._seed_vehicle(label="R")
        route_id, stops = await self._seed_route(label="R", stop_count=2)
        other_route_id, _ = await self._seed_route(label="X", stop_count=2)
        principal, _ = await self._seed_family(
            label="R", route_id=route_id, pickup=stops[0], dropoff=stops[1], vehicle_id=vehicle_id
        )
        await self._seed_trip(vehicle_id=vehicle_id, route_id=other_route_id, start=True)

        (item,) = await self._call(principal)

        self.assertIsNone(item.current_trip)

    async def test_two_families_see_nothing_of_each_other(self) -> None:
        vehicle_a = await self._seed_vehicle(label="A")
        vehicle_b = await self._seed_vehicle(label="B")
        route_a, stops_a = await self._seed_route(label="A", stop_count=2)
        route_b, stops_b = await self._seed_route(label="B", stop_count=2)
        principal_a, student_a = await self._seed_family(
            label="A", route_id=route_a, pickup=stops_a[0], dropoff=stops_a[1], vehicle_id=vehicle_a
        )
        principal_b, student_b = await self._seed_family(
            label="B", route_id=route_b, pickup=stops_b[0], dropoff=stops_b[1], vehicle_id=vehicle_b
        )
        await self._seed_trip(vehicle_id=vehicle_b, route_id=route_b, start=True)

        result_a = await self._call(principal_a)
        result_b = await self._call(principal_b)

        payload_a = repr([asdict(item) for item in result_a])
        payload_b = repr([asdict(item) for item in result_b])
        for leaked in (student_b, vehicle_b, route_b, *stops_b, f"T{self.tag}B"):
            self.assertNotIn(leaked, payload_a)
        for leaked in (student_a, vehicle_a, route_a, *stops_a, f"T{self.tag}A"):
            self.assertNotIn(leaked, payload_b)
        self.assertIsNone(result_a[0].current_trip)
        self.assertIsNotNone(result_b[0].current_trip)

    async def test_child_without_an_assignment(self) -> None:
        principal, student_id = await self._seed_family(label="N", route_id=None)

        (item,) = await self._call(principal)

        self.assertEqual(item.student_id, student_id)
        self.assertIsNone(item.assignment)
        self.assertIsNone(item.current_trip)

    async def test_a_bus_in_another_organization_is_not_resolved(self) -> None:
        """`StudentAssignment.vehicle_id` is an unchecked cross-module id. If it ever named a
        bus of another organization, the tenant-scoped vehicle read must not return it."""
        foreign_vehicle = await self._seed_vehicle(label="F", organization_id=self.other_org_id)
        route_id, stops = await self._seed_route(label="F", stop_count=2)
        principal, _ = await self._seed_family(
            label="F",
            route_id=route_id,
            pickup=stops[0],
            dropoff=stops[1],
            vehicle_id=foreign_vehicle,
        )

        (item,) = await self._call(principal)

        self.assertIsNone(item.assignment.vehicle)
        self.assertEqual(item.assignment.route.id, route_id)
        self.assertNotIn(f"T{self.tag}F", repr(asdict(item)))


if __name__ == "__main__":
    unittest.main()
