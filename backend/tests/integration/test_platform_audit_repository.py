"""PostgreSQL-backed integration test for `platform_audit`'s `SqlAlchemyPlatformAuditUnitOfWork`
(Backend Stabilization phase; pagination coverage added under the Tier 2 pagination phase).
Stdlib `unittest`, mirroring `test_reporting_repository.py`'s skip-guard/cleanup pattern exactly.

Covers: `SystemSetting` add/get/update round trip (including the `key`-not-`id` finder), and
`AuditEntryRepository.get`/`list_all` reading real rows written by the shared-kernel
`AuditWriter` (ADR-0007) — proving `platform_audit`'s own repository can see rows it never wrote
itself, via the same `audit_entries` table `core.audit.writer.AuditEntryRecord` owns. Also, new
this phase: `list_page` against real SQL for both aggregates (mirroring
`test_organization_repository.py`'s `OrganizationPaginationRepositoryTests`), and a regression
test proving `PlatformAuditApplicationService.list_system_settings`'s empty-sort default
(`[SortSpec(field="key")]`) actually prevents the `AttributeError`
`SqlAlchemyRepositoryBase.list_page`'s own fallback (`.order_by(self.model.id.asc())`) would
otherwise raise for `SystemSettingModel` — the one model in this codebase with no `id` column.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable.

**`audit_entries` is append-only** (`.claude/rules/database.md` #7: audit rows are "never
soft/hard deleted") — pagination tests below never assert a bare `page.total` against the whole
table (other tests/runs leave rows behind permanently), instead scoping every filter to this
test's own unique `entity_type`/`action` tag, the same isolation discipline the pre-existing
`test_audit_entry_repository_reads_a_row_written_by_the_shared_audit_writer` test above already
uses. `system_settings` rows, by contrast, are deleted in `asyncTearDown` like every other
mutable-aggregate integration test in this codebase, so its own pagination tests additionally use
a per-test-unique `scope` value to keep `page.total` exact even under concurrent test runs.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime

from sqlalchemy import select, text

from raad.core.audit.writer import AuditEntryRecord, AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.base import DomainEvent
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator, generate_ulid
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.time.clock import SystemClock
from raad.modules.platform_audit.application.queries import ListSystemSettingsQuery
from raad.modules.platform_audit.application.services import PlatformAuditApplicationService
from raad.modules.platform_audit.domain.entities import SystemSetting
from raad.modules.platform_audit.domain.value_objects import AuditEntryId, SystemSettingKey
from raad.modules.platform_audit.infra.repositories import (
    SqlAlchemyPlatformAuditUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class PlatformAuditRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_setting_keys: list[str] = []
        self._created_audit_entry_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_setting_keys:
                await conn.execute(
                    text("DELETE FROM system_settings WHERE key = ANY(:keys)"),
                    {"keys": self._created_setting_keys},
                )
            if self._created_audit_entry_ids:
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE id = ANY(:ids)"),
                    {"ids": self._created_audit_entry_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyPlatformAuditUnitOfWork:
        return SqlAlchemyPlatformAuditUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_system_setting_add_then_get_round_trips(self) -> None:
        key = f"k{self.tag}"[:26]
        async with self._new_uow() as uow:
            setting = SystemSetting.set(
                key=SystemSettingKey(key),
                value={"provider": "google"},
                scope="platform",
                clock=self.clock,
            )
            uow.system_settings.add(setting)
            uow.record_events(setting.pull_domain_events())
            await uow.commit()
            self._created_setting_keys.append(key)

        async with self._new_uow() as uow:
            fetched = await uow.system_settings.get(SystemSettingKey(key))

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.value, {"provider": "google"})
        self.assertEqual(fetched.scope, "platform")

    async def test_system_setting_mutation_after_get_persists_without_a_second_add(
        self,
    ) -> None:
        key = f"m{self.tag}"[:26]
        async with self._new_uow() as uow:
            setting = SystemSetting.set(
                key=SystemSettingKey(key), value={"a": 1}, scope="platform", clock=self.clock
            )
            uow.system_settings.add(setting)
            uow.record_events(setting.pull_domain_events())
            await uow.commit()
            self._created_setting_keys.append(key)

        async with self._new_uow() as uow:
            loaded = await uow.system_settings.get(SystemSettingKey(key))
            loaded.update_value({"a": 2}, clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.system_settings.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.system_settings.get(SystemSettingKey(key))

        self.assertEqual(refetched.value, {"a": 2})

    async def test_get_missing_setting_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.system_settings.get(SystemSettingKey("does-not-exist"))
        self.assertIsNone(result)

    async def test_audit_entry_repository_reads_a_row_written_by_the_shared_audit_writer(
        self,
    ) -> None:
        """Proves the ADR-0007 split: this module's own repository can read a row it never
        wrote — the row below is inserted exactly the way `SqlAlchemyUnitOfWork.commit()`
        inserts one for every other module's own domain events, not through any
        `platform_audit` code path."""
        entry_id = generate_ulid()
        event = DomainEvent(
            event_id=generate_ulid(),
            event_type=f"ProbeEvent{self.tag}",
            version=1,
            occurred_at=datetime(2026, 7, 21, 12, 0, 0),
            org_id=None,
            correlation_id=None,
            payload={"actor_id": None},
            aggregate_type="Probe",
            aggregate_id=entry_id,
        )
        async with self.session_factory() as session:
            await self.audit_writer.write(session, event)
            await session.commit()
            # Recover the actual generated AuditEntryRecord.id via its distinctive action.
            result = await session.execute(
                select(AuditEntryRecord).where(
                    AuditEntryRecord.action == f"ProbeEvent{self.tag}"
                )
            )
            row = result.scalar_one()
            self._created_audit_entry_ids.append(row.id)

        async with self._new_uow() as uow:
            fetched = await uow.audit_entries.get(AuditEntryId(row.id))
            all_entries = await uow.audit_entries.list_all()

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.action, f"ProbeEvent{self.tag}")
        self.assertEqual(fetched.entity_type, "Probe")
        self.assertTrue(any(e.id == fetched.id for e in all_entries))


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class AuditEntryPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyAuditEntryRepository.list_page` against real SQL, via
    `platform_audit`'s own whitelist — mirrors `OrganizationPaginationRepositoryTests`
    (`test_organization_repository.py`) exactly, except every assertion scopes to this test's
    own tagged `entity_type`/`action`, never a bare `page.total`, since `audit_entries` is
    append-only (module docstring) and may already carry rows from other tests/runs."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.audit_writer = AuditWriter()
        self.tag = uuid.uuid4().hex[:8]
        self._created_audit_entry_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_audit_entry_ids:
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE id = ANY(:ids)"),
                    {"ids": self._created_audit_entry_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyPlatformAuditUnitOfWork:
        return SqlAlchemyPlatformAuditUnitOfWork(
            self.session_factory, OutboxWriter(), self.audit_writer
        )

    async def _write_probe_event(self, *, action: str, entity_type: str) -> str:
        event = DomainEvent(
            event_id=generate_ulid(),
            event_type=action,
            version=1,
            occurred_at=datetime(2026, 7, 21, 12, 0, 0),
            org_id=None,
            correlation_id=None,
            payload={"actor_id": None},
            aggregate_type=entity_type,
            aggregate_id=generate_ulid(),
        )
        async with self.session_factory() as session:
            await self.audit_writer.write(session, event)
            await session.commit()
            result = await session.execute(
                select(AuditEntryRecord).where(AuditEntryRecord.action == action)
            )
            row = result.scalar_one()
            self._created_audit_entry_ids.append(row.id)
            return row.id

    async def test_list_page_paginates_and_reports_total_within_a_tagged_entity_type(
        self,
    ) -> None:
        entity_type = f"Probe{self.tag}"
        for i in range(3):
            await self._write_probe_event(
                action=f"ProbeEvent{self.tag}{i}", entity_type=entity_type
            )

        async with self._new_uow() as uow:
            page = await uow.audit_entries.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="action")],
                filters=[FilterCondition(field="entity_type", op="eq", value=entity_type)],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_action(self) -> None:
        entity_type = f"ProbeFilter{self.tag}"
        await self._write_probe_event(action=f"Match{self.tag}", entity_type=entity_type)
        await self._write_probe_event(action=f"NoMatch{self.tag}", entity_type=entity_type)

        async with self._new_uow() as uow:
            page = await uow.audit_entries.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="entity_type", op="eq", value=entity_type),
                    FilterCondition(field="action", op="eq", value=f"Match{self.tag}"),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].action, f"Match{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.audit_entries.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="metadata_json", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.audit_entries.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SystemSettingPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemySystemSettingRepository.list_page` against real SQL — including the
    regression proof this module's whole pagination phase exists to close: `SystemSettingModel`
    has no `id` column (`infra/models.py`'s own docstring), so `SqlAlchemyRepositoryBase.
    list_page`'s own empty-sort fallback (`.order_by(self.model.id.asc())`) would raise
    `AttributeError` if this aggregate's `list_page` were ever reached with an empty `sort` —
    which is exactly what `PlatformAuditApplicationService.list_system_settings`'s own
    `sort = query.sort or [SortSpec(field="key")]` guard prevents, one layer above the
    repository. Every test below uses a per-test-unique `scope` value (not the shared literal
    `"platform"` other tests in this file use) so `page.total` stays exact even under concurrent
    test runs — `system_settings` rows *are* deleted in `asyncTearDown`, unlike `audit_entries`,
    but nothing else in this file guarantees test isolation on `scope` alone."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_setting_keys: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_setting_keys:
                await conn.execute(
                    text("DELETE FROM system_settings WHERE key = ANY(:keys)"),
                    {"keys": self._created_setting_keys},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyPlatformAuditUnitOfWork:
        return SqlAlchemyPlatformAuditUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(self, *, key: str, scope: str) -> None:
        async with self._new_uow() as uow:
            setting = SystemSetting.set(
                key=SystemSettingKey(key), value={}, scope=scope, clock=self.clock
            )
            uow.system_settings.add(setting)
            uow.record_events(setting.pull_domain_events())
            await uow.commit()
            self._created_setting_keys.append(key)

    async def test_list_page_paginates_and_reports_total(self) -> None:
        scope = f"platform-{self.tag}"
        for i in range(3):
            await self._seed(key=f"page.{self.tag}.{i}", scope=scope)

        async with self._new_uow() as uow:
            page = await uow.system_settings.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="key")],
                filters=[FilterCondition(field="scope", op="eq", value=scope)],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)
        self.assertEqual(
            [str(s.key) for s in page.data],
            [f"page.{self.tag}.0", f"page.{self.tag}.1"],
        )

    async def test_list_page_filters_by_scope(self) -> None:
        scope_a = f"scope-a-{self.tag}"
        scope_b = f"scope-b-{self.tag}"
        await self._seed(key=f"filter.a.{self.tag}", scope=scope_a)
        await self._seed(key=f"filter.b.{self.tag}", scope=scope_b)

        async with self._new_uow() as uow:
            page = await uow.system_settings.list_page(
                OffsetPageRequest(),
                sort=[SortSpec(field="key")],
                filters=[FilterCondition(field="scope", op="eq", value=scope_b)],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].key), f"filter.b.{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.system_settings.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="key")],
                    filters=[FilterCondition(field="value_json", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.system_settings.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="value")],
                    filters=[],
                    search=None,
                )

    async def test_list_page_with_empty_sort_called_directly_raises_attribute_error(
        self,
    ) -> None:
        """Documents the actual quirk, not just the fix: calling this repository's own
        `list_page` directly with an empty `sort` (bypassing the application-service guard)
        crashes exactly as `infra/repositories.py`'s own docstring warns — `SystemSettingModel`
        has no `.id` for `SqlAlchemyRepositoryBase.list_page`'s fallback `.order_by(self.model.
        id.asc())` to bind to. This is a deliberate non-guard (see that docstring), so this test
        pins the crash itself, not a graceful fallback."""
        scope = f"crash-{self.tag}"
        await self._seed(key=f"crash.{self.tag}", scope=scope)

        async with self._new_uow() as uow:
            with self.assertRaises(AttributeError):
                await uow.system_settings.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="scope", op="eq", value=scope)],
                    search=None,
                )

    async def test_list_system_settings_service_defaults_empty_sort_to_key_without_crashing(
        self,
    ) -> None:
        """The actual regression test: going through `PlatformAuditApplicationService.
        list_system_settings` (not the raw repository) with an empty `sort` — i.e. exactly what
        `GET /admin/settings` sends when no `?sort=` query param is given — must NOT raise
        `AttributeError`, and must return rows ordered by `key`. Proves the application-service-
        level default (`application/services.py`) is what actually prevents the crash the test
        above pins at the repository layer."""
        scope = f"service-default-{self.tag}"
        for key in (f"zebra.{self.tag}", f"alpha.{self.tag}", f"mango.{self.tag}"):
            await self._seed(key=key, scope=scope)

        service = PlatformAuditApplicationService(clock=self.clock)
        uow = self._new_uow()
        page = await service.list_system_settings(
            ListSystemSettingsQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="scope", op="eq", value=scope)],
            ),
            uow=uow,
        )
        self.assertEqual(
            [s.key for s in page.data],
            [f"alpha.{self.tag}", f"mango.{self.tag}", f"zebra.{self.tag}"],
        )


if __name__ == "__main__":
    unittest.main()
