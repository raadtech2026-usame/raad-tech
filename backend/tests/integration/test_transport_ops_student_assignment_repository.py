"""PostgreSQL-backed integration test for `transport_ops`'s
`SqlAlchemyStudentAssignmentRepository` (Phase 13). Stdlib `unittest` — no `pytest` (not an
approved dependency), using `unittest.IsolatedAsyncioTestCase` against the real
`SqlAlchemyTransportOpsUnitOfWork` and the live migrated schema (Alembic head `acfa30ebf4d8`),
not fakes — mirroring `test_transport_ops_trip_repository.py`'s skip-guard/cleanup pattern
exactly.

Covers what no in-memory unit test can prove: the round trip through the real
identity-map/`flush_tracked_changes` mechanics, and `active_assignment_for_student`'s
direct-`select()` correctness. The DB-level proof of the `ux_student_assignments__active_student`
partial unique index itself lives in `test_postgres_repository_invariants.py`, alongside the
analogous `device_assignments`/`trips` tests — not duplicated here.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown` (assignments before students/routes, respecting the FK
constraints), leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Route, Student, StudentAssignment
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    RouteStatus,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    StudentStatus,
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
class StudentAssignmentRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_assignment_ids: list[str] = []
        self._created_student_ids: list[str] = []
        self._created_route_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_assignment_ids:
                await conn.execute(
                    text("DELETE FROM student_assignments WHERE id = ANY(:ids)"),
                    {"ids": self._created_assignment_ids},
                )
            if self._created_student_ids:
                await conn.execute(
                    text("DELETE FROM students WHERE id = ANY(:ids)"),
                    {"ids": self._created_student_ids},
                )
            if self._created_route_ids:
                # stops cascade-delete with their route (ORM-level cascade only, per
                # `test_transport_ops_route_repository.py`'s identical precedent) - delete
                # stops explicitly first so this raw DELETE never violates the FK.
                await conn.execute(
                    text("DELETE FROM stops WHERE route_id = ANY(:ids)"),
                    {"ids": self._created_route_ids},
                )
                await conn.execute(
                    text("DELETE FROM routes WHERE id = ANY(:ids)"),
                    {"ids": self._created_route_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer
        )

    async def _seed_student_and_route(
        self, org_id: str
    ) -> tuple[StudentId, RouteId, StopId, StopId]:
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                full_name=f"Student {self.tag}",
                clock=self.clock,
            )
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            pickup = route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Pickup",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                clock=self.clock,
            )
            dropoff = route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Dropoff",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                clock=self.clock,
            )
            uow.students.add(student)
            uow.routes.add(route)
            uow.record_events(student.pull_domain_events())
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_student_ids.append(str(student.id))
            self._created_route_ids.append(str(route.id))
            return student.id, route.id, pickup.id, dropoff.id

    async def test_add_then_get_round_trips_assignment(self) -> None:
        org_id = self.id_generator.new_id()
        student_id, route_id, pickup_id, dropoff_id = await self._seed_student_and_route(
            org_id
        )

        async with self._new_uow() as uow:
            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                student_id=student_id,
                student_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                pickup_stop_id=pickup_id,
                dropoff_stop_id=dropoff_id,
                vehicle_id=VehicleId(self.id_generator.new_id()),
                clock=self.clock,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            assignment_id = assignment.id
            self._created_assignment_ids.append(str(assignment_id))

        async with self._new_uow() as uow:
            fetched = await uow.student_assignments.get(assignment_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.status, StudentAssignmentStatus.ACTIVE)
        self.assertEqual(str(fetched.pickup_stop_id), str(pickup_id))
        self.assertEqual(str(fetched.dropoff_stop_id), str(dropoff_id))
        self.assertIsNotNone(fetched.vehicle_id)

    async def test_assign_with_no_vehicle_round_trips_null(self) -> None:
        org_id = self.id_generator.new_id()
        student_id, route_id, pickup_id, dropoff_id = await self._seed_student_and_route(
            org_id
        )

        async with self._new_uow() as uow:
            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                student_id=student_id,
                student_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                pickup_stop_id=pickup_id,
                dropoff_stop_id=dropoff_id,
                vehicle_id=None,
                clock=self.clock,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            assignment_id = assignment.id
            self._created_assignment_ids.append(str(assignment_id))

        async with self._new_uow() as uow:
            fetched = await uow.student_assignments.get(assignment_id)

        self.assertIsNone(fetched.vehicle_id)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        org_id = self.id_generator.new_id()
        student_id, route_id, pickup_id, dropoff_id = await self._seed_student_and_route(
            org_id
        )

        async with self._new_uow() as uow:
            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                student_id=student_id,
                student_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                pickup_stop_id=pickup_id,
                dropoff_stop_id=dropoff_id,
                vehicle_id=None,
                clock=self.clock,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            assignment_id = assignment.id
            self._created_assignment_ids.append(str(assignment_id))

        async with self._new_uow() as uow:
            loaded = await uow.student_assignments.get(assignment_id)
            loaded.remove(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.student_assignments.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.student_assignments.get(assignment_id)

        self.assertEqual(refetched.status, StudentAssignmentStatus.REMOVED)
        self.assertIsNotNone(refetched.ended_at)

    async def test_active_assignment_for_student_finds_only_active_one(self) -> None:
        org_id = self.id_generator.new_id()
        student_id, route_id, pickup_id, dropoff_id = await self._seed_student_and_route(
            org_id
        )

        async with self._new_uow() as uow:
            none_yet = await uow.student_assignments.active_assignment_for_student(
                student_id
            )
        self.assertIsNone(none_yet)

        async with self._new_uow() as uow:
            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                student_id=student_id,
                student_organization_id=OrganizationId(org_id),
                route_id=route_id,
                route_organization_id=OrganizationId(org_id),
                pickup_stop_id=pickup_id,
                dropoff_stop_id=dropoff_id,
                vehicle_id=None,
                clock=self.clock,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            self._created_assignment_ids.append(str(assignment.id))

        async with self._new_uow() as uow:
            active = await uow.student_assignments.active_assignment_for_student(
                student_id
            )

        self.assertIsNotNone(active)
        self.assertEqual(str(active.id), str(assignment.id))


if __name__ == "__main__":
    unittest.main()
