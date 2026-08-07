"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyDriverRepository`
(Phase 10.8). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `8bde77c847c0`), not fakes — mirroring
`test_transport_ops_parent_repository.py`'s skip-guard/cleanup pattern exactly.

`Driver` has no documented safety-critical DB-level invariant analogous to Fleet Device's
partial-unique-index or IAM's duplicate-email constraint (Database Design §6.1 declares no
unique constraint on `drivers` beyond the primary key) — so what's meaningful to prove here,
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
from raad.modules.transport_ops.domain.entities import Driver
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
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
class DriverRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
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
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        # organization_id/user_id are CHAR(26) columns (Database Design §6.1): a shorter opaque
        # string like f"org-{self.tag}" would round-trip space-padded by PostgreSQL's fixed-width
        # CHAR semantics, so use ULID-shaped (26-char) values here, matching what production
        # OrganizationId/UserId values actually look like.
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"DL-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            driver_id = driver.id
            self._created_ids.append(str(driver_id))

        async with self._new_uow() as uow:
            fetched = await uow.drivers.get(driver_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(str(fetched.user_id), user_id)
        self.assertEqual(fetched.license_no, f"DL-{self.tag}")
        self.assertEqual(fetched.status, DriverStatus.ACTIVE)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge described in
        `infra/repositories.py`'s module docstring: `get()` returns a detached domain object,
        and calling a lifecycle method on it followed by `commit()` (no `add()` call) must still
        persist, because the repository re-projects the tracked object onto its ORM row.
        """
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"DL-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            driver_id = driver.id
            self._created_ids.append(str(driver_id))

        async with self._new_uow() as uow:
            loaded = await uow.drivers.get(driver_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.drivers.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.drivers.get(driver_id)

        self.assertEqual(refetched.status, DriverStatus.INACTIVE)

    async def test_list_all_includes_newly_added_driver(self) -> None:
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"List Test {self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(driver.id))

        async with self._new_uow() as uow:
            all_drivers = await uow.drivers.list_all()

        self.assertIn(str(driver.id), {str(d.id) for d in all_drivers})

    async def test_get_missing_driver_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.drivers.get(DriverId(self.id_generator.new_id()))
        self.assertIsNone(result)

    async def test_get_by_user_id_returns_the_matching_driver(self) -> None:
        """ADR-0023: `get_by_user_id` is the real DB round trip `MeApplicationService.
        get_my_driver_profile` depends on to resolve a Principal to its own Driver record —
        mirrors `SqlAlchemyParentRepository.get_by_user_id`'s identical query shape."""
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"BYUSER-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(driver.id))
            driver_id = driver.id

        async with self._new_uow() as uow:
            fetched = await uow.drivers.get_by_user_id(UserId(user_id))

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.id), str(driver_id))
        self.assertEqual(str(fetched.user_id), user_id)

    async def test_get_by_user_id_returns_none_for_an_unknown_user_id(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.drivers.get_by_user_id(UserId(self.id_generator.new_id()))
        self.assertIsNone(result)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DriverPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyRepositoryBase.list_page` (`core/db/repository.py`) against real
    SQL, via `SqlAlchemyDriverRepository`'s own whitelist — mirrors
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
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(self, *, license_no: str, organization_id: str) -> Driver:
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                user_id=UserId(self.id_generator.new_id()),
                license_no=license_no,
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(driver.id))
            return driver

    async def test_list_page_paginates_and_reports_total(self) -> None:
        org_id = self.id_generator.new_id()
        for i in range(3):
            await self._seed(license_no=f"PAGE-{self.tag}-{i}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.drivers.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="license_no")],
                filters=[],
                search=f"PAGE-{self.tag}",
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        org_id = self.id_generator.new_id()
        active = await self._seed(
            license_no=f"ACTIVE-{self.tag}", organization_id=org_id
        )
        disabled = await self._seed(
            license_no=f"DISABLED-{self.tag}", organization_id=org_id
        )
        async with self._new_uow() as uow:
            loaded = await uow.drivers.get(disabled.id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            page = await uow.drivers.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="status", op="eq", value="inactive")],
                search=self.tag,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].license_no, f"DISABLED-{self.tag}")
        self.assertNotEqual(str(page.data[0].id), str(active.id))

    async def test_list_page_sorts_descending_by_license_no(self) -> None:
        org_id = self.id_generator.new_id()
        for suffix in ("Alpha", "Beta", "Gamma"):
            await self._seed(license_no=f"{suffix}-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.drivers.list_page(
                OffsetPageRequest(),
                sort=[SortSpec(field="license_no", descending=True)],
                filters=[],
                search=self.tag,
            )
        self.assertEqual(
            [d.license_no for d in page.data],
            [f"Gamma-{self.tag}", f"Beta-{self.tag}", f"Alpha-{self.tag}"],
        )

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.drivers.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="user_id", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.drivers.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TenantIsolationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0021: proves `TenantRegionScope` bound at UoW construction is actually enforced by
    `SqlAlchemyDriverRepository` against a real, live database — mirrors
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
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
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

    async def _seed_driver(self, *, organization_id: str) -> str:
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                user_id=UserId(self.id_generator.new_id()),
                license_no=f"LIC-{self.tag}-{organization_id[-4:]}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(driver.id))
            return str(driver.id)

    async def test_org_a_cannot_get_org_bs_driver_by_id(self) -> None:
        driver_b = await self._seed_driver(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.drivers.get(DriverId(driver_b))

        self.assertIsNone(result)

    async def test_org_a_can_still_get_its_own_driver_by_id(self) -> None:
        driver_a = await self._seed_driver(organization_id=self.org_a)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.drivers.get(DriverId(driver_a))

        self.assertIsNotNone(result)
        self.assertEqual(str(result.id), driver_a)

    async def test_org_a_list_all_excludes_org_bs_drivers(self) -> None:
        driver_a = await self._seed_driver(organization_id=self.org_a)
        driver_b = await self._seed_driver(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            visible = await uow.drivers.list_all()

        visible_ids = {str(d.id) for d in visible}
        self.assertIn(driver_a, visible_ids)
        self.assertNotIn(driver_b, visible_ids)

    async def test_founder_unrestricted_scope_sees_both_organizations(self) -> None:
        driver_a = await self._seed_driver(organization_id=self.org_a)
        driver_b = await self._seed_driver(organization_id=self.org_b)

        unrestricted = TenantRegionScope(organization_ids=None)
        async with self._new_uow(scope=unrestricted) as uow:
            visible = await uow.drivers.list_all()

        visible_ids = {str(d.id) for d in visible}
        self.assertIn(driver_a, visible_ids)
        self.assertIn(driver_b, visible_ids)


if __name__ == "__main__":
    unittest.main()
