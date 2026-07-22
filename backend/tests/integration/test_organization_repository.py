"""PostgreSQL-backed integration test for `organization`'s `SqlAlchemyRegionRepository`/
`SqlAlchemyOrganizationRepository`. Stdlib `unittest` — no `pytest` (not an approved
dependency) — against the real `SqlAlchemyOrganizationUnitOfWork` and the live migrated
schema, not fakes, mirroring `test_transport_ops_driver_repository.py`'s skip-guard/cleanup
pattern exactly.

**Closes a real, previously-flagged gap**: CLAUDE.md's own "Known gaps" section names
Organization as one of four modules with no dedicated live-DB integration test file.

`organizations.region_id` is a real, `NOT NULL` in-context foreign key to `regions.id`
(`infra/models.py`), so every `Organization` test creates its own `Region` row first — this
also gives the DB-enforced FK itself a real round-trip proof, not just the identity-map
mechanics `test_mutation_after_get_persists_without_a_second_add` targets.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them (organizations before regions, respecting the FK) in `tearDown`.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.time.clock import SystemClock
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrganizationId,
    OrganizationStatus,
    OrgType,
    RegionId,
    RegionStatus,
)
from raad.modules.organization.infra.repositories import SqlAlchemyOrganizationUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class RegionAndOrganizationRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_org_ids: list[str] = []
        self._created_region_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_org_ids:
                await conn.execute(
                    text("DELETE FROM organizations WHERE id = ANY(:ids)"),
                    {"ids": self._created_org_ids},
                )
            if self._created_region_ids:
                await conn.execute(
                    text("DELETE FROM regions WHERE id = ANY(:ids)"),
                    {"ids": self._created_region_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyOrganizationUnitOfWork:
        return SqlAlchemyOrganizationUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _create_committed_region(self) -> RegionId:
        """Commits the `Region` in its own transaction before returning — matching real usage:
        `OrganizationApplicationService.register_organization` calls `ensure_region_exists`,
        which requires the region to already be readable via `uow.regions.get(...)`, i.e.
        already committed in a prior transaction, never created alongside its referencing
        `Organization` in the same one. `organizations.region_id`'s in-context FK is enforced
        by the database only (no ORM `relationship()` declared, per this codebase's own
        minimal-ORM convention) — so, unlike `relationship()`-mapped inserts, SQLAlchemy's
        unit-of-work flush does not topologically reorder same-transaction inserts across the
        two tables purely from the raw FK column, and committing them together is not a
        pattern any real code path here relies on."""
        async with self._new_uow() as uow:
            region = Region.create(
                id=RegionId(self.id_generator.new_id()),
                name=f"Region {self.tag}",
                clock=self.clock,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            self._created_region_ids.append(str(region.id))
            return region.id

    async def test_region_add_then_get_round_trips(self) -> None:
        region_id = await self._create_committed_region()

        async with self._new_uow() as uow:
            fetched = await uow.regions.get(region_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, f"Region {self.tag}")
        self.assertEqual(fetched.status, RegionStatus.ACTIVE)

    async def test_organization_add_then_get_round_trips_with_real_region_fk(self) -> None:
        region_id = await self._create_committed_region()
        async with self._new_uow() as uow:
            organization = Organization.register(
                id=OrganizationId(self.id_generator.new_id()),
                name=f"Org {self.tag}",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                billing_model=BillingModel.ORGANIZATION_PAYS,
                clock=self.clock,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            org_id = organization.id
            self._created_org_ids.append(str(org_id))

        async with self._new_uow() as uow:
            fetched = await uow.organizations.get(org_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, f"Org {self.tag}")
        self.assertEqual(str(fetched.region_id), str(region_id))
        self.assertEqual(fetched.status, OrganizationStatus.ACTIVE)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge: `get()` returns a detached
        domain object, and calling a lifecycle method on it followed by `commit()` (no `add()`
        call) must still persist, because the repository re-projects the tracked object onto
        its ORM row."""
        region_id = await self._create_committed_region()
        async with self._new_uow() as uow:
            organization = Organization.register(
                id=OrganizationId(self.id_generator.new_id()),
                name=f"Mutate Org {self.tag}",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                billing_model=BillingModel.ORGANIZATION_PAYS,
                clock=self.clock,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            org_id = organization.id
            self._created_org_ids.append(str(org_id))

        async with self._new_uow() as uow:
            loaded = await uow.organizations.get(org_id)
            loaded.suspend(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.organizations.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.organizations.get(org_id)

        self.assertEqual(refetched.status, OrganizationStatus.SUSPENDED)

    async def test_organization_list_all_includes_newly_added_organization(self) -> None:
        region_id = await self._create_committed_region()
        async with self._new_uow() as uow:
            organization = Organization.register(
                id=OrganizationId(self.id_generator.new_id()),
                name=f"List Org {self.tag}",
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                billing_model=BillingModel.ORGANIZATION_PAYS,
                clock=self.clock,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            self._created_org_ids.append(str(organization.id))

        async with self._new_uow() as uow:
            all_orgs = await uow.organizations.list_all()

        self.assertIn(str(organization.id), {str(o.id) for o in all_orgs})

    async def test_get_missing_organization_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.organizations.get(OrganizationId(self.id_generator.new_id()))
        self.assertIsNone(result)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class OrganizationPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyRepositoryBase.list_page` (`core/db/repository.py`) against real
    SQL, via `organization`'s own whitelists — this is the one place real Postgres behavior
    (offset/limit, `ILIKE` search, whitelisted filter/sort, `func.count()` over the same
    filtered predicate) is actually proven, since unit tests use in-memory fakes."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_org_ids: list[str] = []
        self._created_region_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_org_ids:
                await conn.execute(
                    text("DELETE FROM organizations WHERE id = ANY(:ids)"),
                    {"ids": self._created_org_ids},
                )
            if self._created_region_ids:
                await conn.execute(
                    text("DELETE FROM regions WHERE id = ANY(:ids)"),
                    {"ids": self._created_region_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyOrganizationUnitOfWork:
        return SqlAlchemyOrganizationUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(self, *, name: str, billing_model: BillingModel, region_id: RegionId) -> None:
        async with self._new_uow() as uow:
            organization = Organization.register(
                id=OrganizationId(self.id_generator.new_id()),
                name=name,
                org_type=OrgType.SCHOOL,
                region_id=region_id,
                billing_model=billing_model,
                clock=self.clock,
            )
            uow.organizations.add(organization)
            uow.record_events(organization.pull_domain_events())
            await uow.commit()
            self._created_org_ids.append(str(organization.id))

    async def test_list_page_paginates_and_reports_total(self) -> None:
        async with self._new_uow() as uow:
            region = Region.create(
                id=RegionId(self.id_generator.new_id()),
                name=f"Region {self.tag}",
                clock=self.clock,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            region_id = region.id
            self._created_region_ids.append(str(region_id))

        for i in range(3):
            await self._seed(
                name=f"Page Org {self.tag} {i}",
                billing_model=BillingModel.ORGANIZATION_PAYS,
                region_id=region_id,
            )

        async with self._new_uow() as uow:
            page = await uow.organizations.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="name")],
                filters=[FilterCondition(field="region_id", op="eq", value=str(region_id))],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_billing_model(self) -> None:
        async with self._new_uow() as uow:
            region = Region.create(
                id=RegionId(self.id_generator.new_id()),
                name=f"Region Filter {self.tag}",
                clock=self.clock,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            region_id = region.id
            self._created_region_ids.append(str(region_id))

        await self._seed(
            name=f"Org Pays {self.tag}",
            billing_model=BillingModel.ORGANIZATION_PAYS,
            region_id=region_id,
        )
        await self._seed(
            name=f"Parent Pays {self.tag}",
            billing_model=BillingModel.PARENT_PAYS,
            region_id=region_id,
        )

        async with self._new_uow() as uow:
            page = await uow.organizations.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="region_id", op="eq", value=str(region_id)),
                    FilterCondition(field="billing_model", op="eq", value="parent_pays"),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, f"Parent Pays {self.tag}")

    async def test_list_page_search_matches_name_substring(self) -> None:
        async with self._new_uow() as uow:
            region = Region.create(
                id=RegionId(self.id_generator.new_id()),
                name=f"Region Search {self.tag}",
                clock=self.clock,
            )
            uow.regions.add(region)
            uow.record_events(region.pull_domain_events())
            await uow.commit()
            region_id = region.id
            self._created_region_ids.append(str(region_id))

        await self._seed(
            name=f"Findable-{self.tag}",
            billing_model=BillingModel.ORGANIZATION_PAYS,
            region_id=region_id,
        )
        await self._seed(
            name=f"Other-{self.tag}",
            billing_model=BillingModel.ORGANIZATION_PAYS,
            region_id=region_id,
        )

        async with self._new_uow() as uow:
            page = await uow.organizations.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="region_id", op="eq", value=str(region_id))
                ],
                search="findable",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, f"Findable-{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.organizations.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="password_hash", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.organizations.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


if __name__ == "__main__":
    unittest.main()
