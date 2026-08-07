"""PostgreSQL-backed integration test for `iam.application.services.MeApplicationService`
(ADR-0023 — closes `PROJECT_STATUS.md` Known Issue #17). Stdlib `unittest` — no `pytest`, using
`unittest.IsolatedAsyncioTestCase` against the real, DI-unwired-but-otherwise-real
`ParentApplicationService`/`DriverApplicationService`/`StudentParentApplicationService` and the
live migrated `transport_ops` schema — mirroring `test_transport_ops_student_parent_repository.
py`'s skip-guard/cleanup pattern.

This is the actual security regression proof `test_me_application.py`'s fake-backed unit tests
cannot provide: real Postgres rows, a real `SqlAlchemyTransportOpsUnitOfWork`, real repository
queries — proving Parent A's `MeApplicationService.get_my_students` call genuinely cannot reach
Parent B's students through the real database, not just through a hand-written fake that could
silently diverge from the real query.

`ParentApplicationService`/`DriverApplicationService` are constructed with
`user_provisioning=None` — safe here because every seeded `Parent`/`Driver` row is created
directly via the domain factory (`Parent.register`/`Driver.register`) and the repository's own
`add()`, the same pattern every other integration test in this suite already uses; only
`register_parent`/`register_driver` (never called here) touch that dependency.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import SystemClock
from raad.modules.iam.application.services import MeApplicationService
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    StudentParentApplicationService,
)
from raad.modules.transport_ops.domain.entities import Driver, Parent, Student, StudentParent
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    ParentId,
    StudentId,
    UserId,
)
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class MeApplicationServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_id = self.id_generator.new_id()
        self._created_student_ids: list[str] = []
        self._created_parent_ids: list[str] = []
        self._created_driver_ids: list[str] = []
        self.service = MeApplicationService(
            parent_service=ParentApplicationService(
                clock=self.clock,
                id_generator=self.id_generator,
                user_provisioning=None,  # type: ignore[arg-type]
            ),
            driver_service=DriverApplicationService(
                clock=self.clock,
                id_generator=self.id_generator,
                user_provisioning=None,  # type: ignore[arg-type]
            ),
            student_parent_service=StudentParentApplicationService(clock=self.clock),
        )

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_student_ids:
                await conn.execute(
                    text("DELETE FROM student_parents WHERE student_id = ANY(:ids)"),
                    {"ids": self._created_student_ids},
                )
            if self._created_parent_ids:
                await conn.execute(
                    text("DELETE FROM student_parents WHERE parent_id = ANY(:ids)"),
                    {"ids": self._created_parent_ids},
                )
            if self._created_student_ids:
                await conn.execute(
                    text("DELETE FROM students WHERE id = ANY(:ids)"),
                    {"ids": self._created_student_ids},
                )
            if self._created_parent_ids:
                await conn.execute(
                    text("DELETE FROM parents WHERE id = ANY(:ids)"),
                    {"ids": self._created_parent_ids},
                )
            if self._created_driver_ids:
                await conn.execute(
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_driver_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_parent_with_student(
        self, *, label: str
    ) -> tuple[Principal, str]:
        """Creates one Parent (with a fresh iam-shaped user_id), one Student, and links them —
        returns the Principal a real login as this Parent would produce, plus the seeded
        student_id for assertions."""
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_id),
                user_id=UserId(user_id),
                full_name=f"Parent {label} {self.tag}",
                clock=self.clock,
            )
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_id),
                full_name=f"Student {label} {self.tag}",
                clock=self.clock,
            )
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                relationship="parent",
                is_primary=True,
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.students.add(student)
            uow.student_parents.add(link)
            uow.record_events(
                [*parent.pull_domain_events(), *student.pull_domain_events()]
            )
            await uow.commit()
            self._created_parent_ids.append(str(parent.id))
            self._created_student_ids.append(str(student.id))
        principal = Principal(user_id=user_id, role=Role.PARENT, org_id=self.org_id)
        return principal, str(student.id)

    async def test_two_parents_are_fully_isolated_through_the_real_database(self) -> None:
        # MeApplicationService's own methods each manage their own `async with uow:` block
        # internally (mirroring every application service in this codebase) - the UoW passed
        # in here must stay un-entered, exactly like the real router's `Depends(
        # get_transport_ops_uow)` hands one over, not wrapped in another `async with` here too.
        principal_a, student_a_id = await self._seed_parent_with_student(label="A")
        principal_b, student_b_id = await self._seed_parent_with_student(label="B")

        students_a = await self.service.get_my_students(
            principal_a, uow=self._new_uow()
        )
        students_b = await self.service.get_my_students(
            principal_b, uow=self._new_uow()
        )

        self.assertEqual([s.student_id for s in students_a], [student_a_id])
        self.assertEqual([s.student_id for s in students_b], [student_b_id])
        self.assertNotIn(student_b_id, [s.student_id for s in students_a])
        self.assertNotIn(student_a_id, [s.student_id for s in students_b])

    async def test_principal_with_no_linked_parent_row_raises_not_found(self) -> None:
        principal = Principal(
            user_id=self.id_generator.new_id(), role=Role.PARENT, org_id=self.org_id
        )

        with self.assertRaises(NotFoundError):
            await self.service.get_my_students(principal, uow=self._new_uow())

    async def test_driver_profile_resolves_through_the_real_database(self) -> None:
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_id),
                user_id=UserId(user_id),
                license_no=f"ME-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_driver_ids.append(str(driver.id))
            driver_id = str(driver.id)

        principal = Principal(user_id=user_id, role=Role.DRIVER, org_id=self.org_id)
        profile = await self.service.get_my_driver_profile(
            principal, uow=self._new_uow()
        )

        self.assertEqual(profile.driver_id, driver_id)
        self.assertEqual(profile.organization_id, self.org_id)
        self.assertEqual(profile.license_no, f"ME-{self.tag}")

    async def test_principal_with_no_linked_driver_row_raises_not_found(self) -> None:
        principal = Principal(
            user_id=self.id_generator.new_id(), role=Role.DRIVER, org_id=self.org_id
        )

        with self.assertRaises(NotFoundError):
            await self.service.get_my_driver_profile(principal, uow=self._new_uow())


if __name__ == "__main__":
    unittest.main()
