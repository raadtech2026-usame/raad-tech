"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyStudentRepository`
(Phase 10.1/10.2). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema, not fakes — mirroring `test_transport_ops_driver_repository.py`'s
skip-guard/cleanup pattern exactly.

**Closes a real, previously-flagged gap**: `Student` round-trips were previously exercised only
indirectly (as setup fixtures inside `test_transport_ops_student_parent_repository.py`/
`test_transport_ops_student_assignment_repository.py`), never through a dedicated repository
test file of its own — every other single-column-PK aggregate in this module
(`Driver`/`Parent`/`Route`/`Trip`/`StudentAssignment`) already has one. This file closes that
gap, added alongside the Tier 2 pagination phase's own `SqlAlchemyStudentRepository.list_page`
addition (`infra/repositories.py`), which is the one repository method in this module that had
no live-DB proof anywhere before this file existed.

`Student` has no documented safety-critical DB-level invariant analogous to Fleet Device's
partial-unique-index or IAM's duplicate-email constraint (Database Design §6.2 declares no
unique constraint on `students` beyond the primary key) — so what's meaningful to prove here,
that no in-memory unit test can, is the round trip through the real identity-map/
`flush_tracked_changes` mechanics `infra/repositories.py`'s module docstring describes, plus
`list_page`'s real-SQL offset/limit, `ILIKE` search, and whitelisted filter/sort behavior.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable, per this project's established live-verification
posture. Every test inserts rows tagged with a unique per-run marker and deletes them in
`tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Student
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    StudentId,
    StudentStatus,
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
class StudentRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM students WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                full_name=f"Amina {self.tag}",
                external_ref=f"SCH-{self.tag}",
                clock=self.clock,
            )
            uow.students.add(student)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            student_id = student.id
            self._created_ids.append(str(student_id))

        async with self._new_uow() as uow:
            fetched = await uow.students.get(student_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.full_name, f"Amina {self.tag}")
        self.assertEqual(fetched.external_ref, f"SCH-{self.tag}")
        self.assertEqual(fetched.status, StudentStatus.ACTIVE)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge described in
        `infra/repositories.py`'s module docstring: `get()` returns a detached domain object,
        and calling a lifecycle method on it followed by `commit()` (no `add()` call) must still
        persist, because the repository re-projects the tracked object onto its ORM row.
        """
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                full_name=f"Amina {self.tag}",
                external_ref=None,
                clock=self.clock,
            )
            uow.students.add(student)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            student_id = student.id
            self._created_ids.append(str(student_id))

        async with self._new_uow() as uow:
            loaded = await uow.students.get(student_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.students.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.students.get(student_id)

        self.assertEqual(refetched.status, StudentStatus.DISABLED)

    async def test_list_all_includes_newly_added_student(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                full_name=f"List Test {self.tag}",
                external_ref=None,
                clock=self.clock,
            )
            uow.students.add(student)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(student.id))

        async with self._new_uow() as uow:
            all_students = await uow.students.list_all()

        self.assertIn(str(student.id), {str(s.id) for s in all_students})

    async def test_get_missing_student_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.students.get(StudentId(self.id_generator.new_id()))
        self.assertIsNone(result)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class StudentPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyRepositoryBase.list_page` (`core/db/repository.py`) against real
    SQL, via `SqlAlchemyStudentRepository`'s own whitelist — this is the one place real
    Postgres behavior (offset/limit, `ILIKE` search, whitelisted filter/sort, `func.count()`
    over the same filtered predicate) is actually proven for `Student`, since unit tests use
    in-memory fakes. Mirrors `OrganizationPaginationRepositoryTests`'s own shape exactly."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM students WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(self, *, full_name: str, organization_id: str) -> Student:
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                full_name=full_name,
                external_ref=None,
                clock=self.clock,
            )
            uow.students.add(student)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(student.id))
            return student

    async def test_list_page_paginates_and_reports_total(self) -> None:
        org_id = self.id_generator.new_id()
        for i in range(3):
            await self._seed(full_name=f"Page Student {self.tag} {i}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.students.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="full_name")],
                filters=[],
                search=f"Page Student {self.tag}",
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        org_id = self.id_generator.new_id()
        active = await self._seed(
            full_name=f"Active Student {self.tag}", organization_id=org_id
        )
        disabled = await self._seed(
            full_name=f"Disabled Student {self.tag}", organization_id=org_id
        )
        async with self._new_uow() as uow:
            loaded = await uow.students.get(disabled.id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            page = await uow.students.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="status", op="eq", value="disabled")
                ],
                search=f"{self.tag}",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].full_name, f"Disabled Student {self.tag}")
        self.assertNotEqual(str(page.data[0].id), str(active.id))

    async def test_list_page_search_matches_full_name_substring(self) -> None:
        org_id = self.id_generator.new_id()
        await self._seed(full_name=f"Findable-{self.tag}", organization_id=org_id)
        await self._seed(full_name=f"Other-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.students.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[],
                search=f"findable-{self.tag}",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].full_name, f"Findable-{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.students.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[
                        FilterCondition(field="organization_id", op="eq", value="x")
                    ],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.students.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


if __name__ == "__main__":
    unittest.main()
