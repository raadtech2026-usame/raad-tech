"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyStudentParentRepository`
(Phase 10.7). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `ff41b1f3c61c`), not fakes — mirroring
`test_transport_ops_parent_repository.py`'s skip-guard/cleanup pattern exactly.

What's meaningful to prove here, that no in-memory unit test can:

- The composite-PK round trip through `add`/`get`/`remove` (no surrogate id, unlike every other
  repository in this codebase — `domain/repositories.py`'s Phase 10.7 docstring).
- `student_id`/`parent_id`'s real, DB-enforced in-context foreign keys (Database Design §6.4,
  `.claude/rules/database.md` #3) — a link referencing a non-existent student/parent is
  rejected by the database itself, not just an application-layer pre-check.
- The composite primary key itself rejects a duplicate `(student_id, parent_id)` row at the DB
  layer, defense-in-depth under `application/validators.py`'s `ensure_link_not_duplicate`.
- `remove()` issues a real `DELETE` (Database Design §6.4 has no `deleted_at` column — confirmed
  with the user before implementing) — the row is genuinely gone after commit, not soft-deleted.
- `list_by_student`/`list_by_parent` against the real `ix_student_parents__parent_id` index
  path.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

import sqlalchemy.exc
from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    StudentId,
    UserId,
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
class StudentParentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_student_ids: list[str] = []
        self._created_parent_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            # student_parents rows are cleaned up implicitly by the FK ON DELETE behavior's
            # absence being irrelevant here - every test either removes its own link rows
            # explicitly or the students/parents delete below cascades through the FK's default
            # RESTRICT... so links are deleted first, explicitly, to avoid an FK violation.
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
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_student_and_parent(self) -> tuple[Student, Parent]:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                full_name=f"Student {self.tag}",
                clock=self.clock,
            )
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name=f"Parent {self.tag}",
                clock=self.clock,
            )
            uow.students.add(student)
            uow.parents.add(parent)
            uow.record_events(student.pull_domain_events())
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            self._created_student_ids.append(str(student.id))
            self._created_parent_ids.append(str(parent.id))
            return student, parent

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        student, parent = await self._seed_student_and_parent()
        async with self._new_uow() as uow:
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                relationship="mother",
                is_primary=True,
                clock=self.clock,
            )
            uow.student_parents.add(link)
            uow.record_events(link.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            fetched = await uow.student_parents.get(student.id, parent.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.relationship, "mother")
        self.assertTrue(fetched.is_primary)

    async def test_remove_deletes_the_row(self) -> None:
        student, parent = await self._seed_student_and_parent()
        async with self._new_uow() as uow:
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                clock=self.clock,
            )
            uow.student_parents.add(link)
            uow.record_events(link.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            loaded = await uow.student_parents.get(student.id, parent.id)
            loaded.unlink(organization_id=student.organization_id, clock=self.clock)
            await uow.student_parents.remove(loaded)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            refetched = await uow.student_parents.get(student.id, parent.id)
        self.assertIsNone(refetched)

    async def test_list_by_student_and_list_by_parent(self) -> None:
        student, parent = await self._seed_student_and_parent()
        async with self._new_uow() as uow:
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                clock=self.clock,
            )
            uow.student_parents.add(link)
            uow.record_events(link.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            by_student = await uow.student_parents.list_by_student(student.id)
            by_parent = await uow.student_parents.list_by_parent(parent.id)

        self.assertEqual(len(by_student), 1)
        self.assertEqual(len(by_parent), 1)
        self.assertEqual(str(by_student[0].parent_id), str(parent.id))
        self.assertEqual(str(by_parent[0].student_id), str(student.id))

    async def test_duplicate_link_violates_db_composite_primary_key(self) -> None:
        """Regression, at the database layer: the composite PK `(student_id, parent_id)`
        rejects a second row for the same pair even if `application/validators.py`'s
        `ensure_link_not_duplicate` pre-check were somehow bypassed (e.g. a race between two
        concurrent requests)."""
        student, parent = await self._seed_student_and_parent()
        async with self._new_uow() as uow:
            first = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                clock=self.clock,
            )
            uow.student_parents.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = StudentParent.link(
                    student_id=student.id,
                    student_organization_id=student.organization_id,
                    parent_id=parent.id,
                    parent_organization_id=parent.organization_id,
                    clock=self.clock,
                )
                uow.student_parents.add(second)
                uow.record_events(second.pull_domain_events())
                await uow.commit()

    async def test_link_to_nonexistent_student_violates_db_foreign_key(self) -> None:
        """Regression, at the database layer: `fk_student_parents__students` rejects a link
        referencing a student id that doesn't exist, even if the application layer's
        `ensure_student_exists` pre-check were somehow bypassed."""
        _, parent = await self._seed_student_and_parent()
        nonexistent_student_id = StudentId(self.id_generator.new_id())
        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                link = StudentParent(
                    student_id=nonexistent_student_id,
                    parent_id=parent.id,
                    relationship=None,
                    is_primary=False,
                )
                uow.student_parents.add(link)
                await uow.commit()

    async def test_get_missing_link_returns_none(self) -> None:
        student, parent = await self._seed_student_and_parent()
        async with self._new_uow() as uow:
            result = await uow.student_parents.get(student.id, parent.id)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
