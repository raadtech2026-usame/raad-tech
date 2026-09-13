"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyParentRepository`
(Phase 10.6). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `4b43a835fc86`), not fakes — mirroring
`test_postgres_repository_invariants.py`'s skip-guard/cleanup pattern exactly.

`Parent` has no documented safety-critical DB-level invariant analogous to Fleet Device's
partial-unique-index or IAM's duplicate-email constraint (Database Design §6.3 declares no
unique constraint on `parents` beyond the primary key) — so what's meaningful to prove here,
that no in-memory unit test can, is the round trip through the real identity-map/
`flush_tracked_changes` mechanics `infra/repositories.py`'s module docstring describes: a
`get()` returns a detached domain object, mutating it in place and calling `commit()` (without a
second `add()`) must still persist the change, because the repository re-projects tracked
domain objects onto their ORM rows before the session flush.

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
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.core.errors.exceptions import DomainError
from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
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
class ParentRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
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
                    text("DELETE FROM parents WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        # organization_id/user_id are CHAR(26) columns (Database Design §6.3): a shorter opaque
        # string like f"org-{self.tag}" would round-trip space-padded by PostgreSQL's fixed-width
        # CHAR semantics, so use ULID-shaped (26-char) values here, matching what production
        # OrganizationId/UserId values actually look like.
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                full_name="Fatima Hassan",
                phone=PhoneNumber("+252700000000"),
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            parent_id = parent.id
            self._created_ids.append(str(parent_id))

        async with self._new_uow() as uow:
            fetched = await uow.parents.get(parent_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(str(fetched.user_id), user_id)
        self.assertEqual(fetched.full_name, "Fatima Hassan")
        self.assertEqual(str(fetched.phone), "+252700000000")
        self.assertEqual(fetched.status, ParentStatus.ACTIVE)

    async def test_round_trips_the_additive_profile_fields(self) -> None:
        """2026-09-10 explicit user directive (Parent & Student Domain Restructure) —
        `alternate_phone`/`address`/`emergency_contact_name`/`emergency_contact_phone`/`notes`
        must survive a real Postgres round trip."""
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                full_name="Fatima Hassan",
                phone=PhoneNumber("+252700000000"),
                alternate_phone=PhoneNumber("+252611111111"),
                address="Hodan District, Mogadishu",
                emergency_contact_name="Ahmed Hassan",
                emergency_contact_phone=PhoneNumber("+252622222222"),
                notes="Prefers SMS over calls.",
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            parent_id = parent.id
            self._created_ids.append(str(parent_id))

        async with self._new_uow() as uow:
            fetched = await uow.parents.get(parent_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.alternate_phone), "+252611111111")
        self.assertEqual(fetched.address, "Hodan District, Mogadishu")
        self.assertEqual(fetched.emergency_contact_name, "Ahmed Hassan")
        self.assertEqual(str(fetched.emergency_contact_phone), "+252622222222")
        self.assertEqual(fetched.notes, "Prefers SMS over calls.")

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge described in
        `infra/repositories.py`'s module docstring: `get()` returns a detached domain object,
        and calling a lifecycle method on it followed by `commit()` (no `add()` call) must still
        persist, because the repository re-projects the tracked object onto its ORM row.
        """
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                full_name="Fatima Hassan",
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            parent_id = parent.id
            self._created_ids.append(str(parent_id))

        async with self._new_uow() as uow:
            loaded = await uow.parents.get(parent_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.parents.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.parents.get(parent_id)

        self.assertEqual(refetched.status, ParentStatus.INACTIVE)

    async def test_list_all_includes_newly_added_parent(self) -> None:
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                full_name=f"List Test {self.tag}",
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(parent.id))

        async with self._new_uow() as uow:
            all_parents = await uow.parents.list_all()

        self.assertIn(str(parent.id), {str(p.id) for p in all_parents})

    async def test_get_missing_parent_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.parents.get(ParentId(self.id_generator.new_id()))
        self.assertIsNone(result)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class ParentPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyRepositoryBase.list_page` (`core/db/repository.py`) against real
    SQL, via `SqlAlchemyParentRepository`'s own whitelist — mirrors
    `OrganizationPaginationRepositoryTests`'s own shape exactly (Tier 2 pagination phase)."""

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
                    text("DELETE FROM parents WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(self, *, full_name: str, organization_id: str) -> Parent:
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name=full_name,
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(parent.id))
            return parent

    async def test_list_page_paginates_and_reports_total(self) -> None:
        org_id = self.id_generator.new_id()
        for i in range(3):
            await self._seed(full_name=f"Page Parent {self.tag} {i}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.parents.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="full_name")],
                filters=[],
                search=f"Page Parent {self.tag}",
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        org_id = self.id_generator.new_id()
        active = await self._seed(
            full_name=f"Active Parent {self.tag}", organization_id=org_id
        )
        disabled = await self._seed(
            full_name=f"Disabled Parent {self.tag}", organization_id=org_id
        )
        async with self._new_uow() as uow:
            loaded = await uow.parents.get(disabled.id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            page = await uow.parents.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="status", op="eq", value="inactive")],
                search=f"{self.tag}",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].full_name, f"Disabled Parent {self.tag}")
        self.assertNotEqual(str(page.data[0].id), str(active.id))

    async def test_list_page_sorts_descending_by_full_name(self) -> None:
        org_id = self.id_generator.new_id()
        for name in ("Alpha", "Beta", "Gamma"):
            await self._seed(full_name=f"{name}-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.parents.list_page(
                OffsetPageRequest(),
                sort=[SortSpec(field="full_name", descending=True)],
                filters=[],
                search=self.tag,
            )
        self.assertEqual(
            [p.full_name for p in page.data],
            [f"Gamma-{self.tag}", f"Beta-{self.tag}", f"Alpha-{self.tag}"],
        )

    async def test_list_page_filters_by_exact_phone(self) -> None:
        """2026-09-10 explicit user directive (Parent & Student Domain Restructure) — `phone`
        is now filterable, backing duplicate-parent detection: `GET /parents?filter[phone]=...`
        must find the one existing parent with that exact number within the caller's own
        organization."""
        org_id = self.id_generator.new_id()
        # E.164 (`\d` only) — `self.tag` is hex and may contain letters, so a distinct numeric
        # suffix is generated here rather than reused from it.
        phone_suffix = f"{uuid.uuid4().int % 10**8:08d}"
        target_phone = f"+2526{phone_suffix}"
        async with self._new_uow() as uow:
            match = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name=f"Match Parent {self.tag}",
                phone=PhoneNumber(target_phone),
                clock=self.clock,
            )
            other = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name=f"Other Parent {self.tag}",
                phone=PhoneNumber("+252699999999"),
                clock=self.clock,
            )
            uow.parents.add(match)
            uow.parents.add(other)
            uow.record_events(match.pull_domain_events())
            uow.record_events(other.pull_domain_events())
            await uow.commit()
            self._created_ids.extend([str(match.id), str(other.id)])

        async with self._new_uow() as uow:
            page = await uow.parents.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="phone", op="eq", value=target_phone)],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].id), str(match.id))

    async def test_list_page_search_matches_phone_substring(self) -> None:
        org_id = self.id_generator.new_id()
        phone_suffix = f"{uuid.uuid4().int % 10**8:08d}"
        target_phone = f"+2526{phone_suffix}"
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name="Searchable By Phone",
                phone=PhoneNumber(target_phone),
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(parent.id))

        async with self._new_uow() as uow:
            page = await uow.parents.list_page(
                OffsetPageRequest(), sort=[], filters=[], search=phone_suffix
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].id), str(parent.id))

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.parents.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="user_id", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.parents.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TenantIsolationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0021: proves `TenantRegionScope` bound at UoW construction is actually enforced by
    `SqlAlchemyParentRepository` against a real, live database — mirrors
    `test_transport_ops_student_repository.py`'s identical `TenantIsolationRepositoryTests`
    shape."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_a = self.id_generator.new_id()
        self.org_b = self.id_generator.new_id()
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM parents WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(
        self, *, scope: TenantRegionScope | None = None
    ) -> SqlAlchemyTransportOpsUnitOfWork:
        uow = SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        if scope is not None:
            uow.scope = scope
        return uow

    async def _seed_parent(self, *, organization_id: str) -> str:
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                user_id=UserId(self.id_generator.new_id()),
                full_name=f"Tenant Test {self.tag}",
                phone=None,
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(parent.id))
            return str(parent.id)

    async def test_org_a_cannot_get_org_bs_parent_by_id(self) -> None:
        parent_b = await self._seed_parent(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.parents.get(ParentId(parent_b))

        self.assertIsNone(result)

    async def test_org_a_can_still_get_its_own_parent_by_id(self) -> None:
        parent_a = await self._seed_parent(organization_id=self.org_a)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.parents.get(ParentId(parent_a))

        self.assertIsNotNone(result)
        self.assertEqual(str(result.id), parent_a)

    async def test_org_a_list_all_excludes_org_bs_parents(self) -> None:
        parent_a = await self._seed_parent(organization_id=self.org_a)
        parent_b = await self._seed_parent(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            visible = await uow.parents.list_all()

        visible_ids = {str(p.id) for p in visible}
        self.assertIn(parent_a, visible_ids)
        self.assertNotIn(parent_b, visible_ids)

    async def test_founder_unrestricted_scope_sees_both_organizations(self) -> None:
        parent_a = await self._seed_parent(organization_id=self.org_a)
        parent_b = await self._seed_parent(organization_id=self.org_b)

        unrestricted = TenantRegionScope(organization_ids=None)
        async with self._new_uow(scope=unrestricted) as uow:
            visible = await uow.parents.list_all()

        visible_ids = {str(p.id) for p in visible}
        self.assertIn(parent_a, visible_ids)
        self.assertIn(parent_b, visible_ids)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class RegisterParentWithChildrenTransactionTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0041 §2's real-database counterpart to `tests/unit/
    test_transport_ops_parent_application.py::RegisterParentWithChildrenTests` — proves the
    actual Postgres rollback guarantee the in-memory fakes there cannot model: when one child in
    a Parent+children registration is invalid, **nothing** from that attempt is left behind, not
    even the Parent or the valid sibling created earlier in the same `async with uow:` block."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_parent_ids: list[str] = []
        self._created_student_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_student_ids:
                await conn.execute(
                    text("DELETE FROM student_parents WHERE student_id = ANY(:ids)"),
                    {"ids": self._created_student_ids},
                )
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

    async def test_an_invalid_child_leaves_no_parent_and_no_valid_sibling_behind(self) -> None:
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        parent_id = ParentId(self.id_generator.new_id())
        valid_student_id = StudentId(self.id_generator.new_id())
        self._created_parent_ids.append(str(parent_id))
        self._created_student_ids.append(str(valid_student_id))

        with self.assertRaises(DomainError):
            async with self._new_uow() as uow:
                parent = Parent.register(
                    id=parent_id,
                    organization_id=OrganizationId(org_id),
                    user_id=UserId(user_id),
                    full_name=f"Ahmed Mohamed {self.tag}",
                    clock=self.clock,
                )
                uow.parents.add(parent)

                valid_child = Student.enroll(
                    id=valid_student_id,
                    organization_id=OrganizationId(org_id),
                    full_name=f"Mohamed Ahmed {self.tag}",
                    clock=self.clock,
                )
                uow.students.add(valid_child)
                link = StudentParent.link(
                    student_id=valid_child.id,
                    student_organization_id=valid_child.organization_id,
                    parent_id=parent.id,
                    parent_organization_id=parent.organization_id,
                    clock=self.clock,
                )
                uow.student_parents.add(link)

                # The invalid child — constructed only to prove the transaction never reaches
                # `commit()`. `Student.enroll` itself raises for an empty full_name before any
                # further code in this block runs.
                Student.enroll(
                    id=StudentId(self.id_generator.new_id()),
                    organization_id=OrganizationId(org_id),
                    full_name="",
                    clock=self.clock,
                )
                await uow.commit()

        # Real Postgres rollback: neither the Parent nor the valid sibling Student exist.
        async with self._new_uow() as uow:
            fetched_parent = await uow.parents.get(parent_id)
            fetched_student = await uow.students.get(valid_student_id)
        self.assertIsNone(fetched_parent)
        self.assertIsNone(fetched_student)


if __name__ == "__main__":
    unittest.main()
