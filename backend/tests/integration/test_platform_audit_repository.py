"""PostgreSQL-backed integration test for `platform_audit`'s `SqlAlchemyPlatformAuditUnitOfWork`
(Backend Stabilization phase). Stdlib `unittest`, mirroring `test_reporting_repository.py`'s
skip-guard/cleanup pattern exactly.

Covers: `SystemSetting` add/get/update round trip (including the `key`-not-`id` finder), and
`AuditEntryRepository.get`/`list_all` reading real rows written by the shared-kernel
`AuditWriter` (ADR-0007) — proving `platform_audit`'s own repository can see rows it never wrote
itself, via the same `audit_entries` table `core.audit.writer.AuditEntryRecord` owns.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.base import DomainEvent
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator, generate_ulid
from raad.core.time.clock import SystemClock
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
            from sqlalchemy import select

            from raad.core.audit.writer import AuditEntryRecord

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


if __name__ == "__main__":
    unittest.main()
