"""Application-layer tests for `platform_audit`'s `PlatformAuditApplicationService` (Backend
Stabilization phase). Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_video_application.py`'s exact structure. In-memory fakes for both repositories — no
SQLAlchemy, no FastAPI, no real database.

Covers: `list_audit_entries` (read-only, no create path from this module), `set_system_setting`'s
create-or-update orchestration, and `list_system_settings`/`get_system_setting`.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.time.clock import Clock
from raad.core.tenancy.principal import Principal, Role
from raad.modules.platform_audit.application.commands import SetSystemSettingCommand
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import (
    GetSystemSettingQuery,
    ListAuditEntriesQuery,
    ListSystemSettingsQuery,
)
from raad.modules.platform_audit.application.services import PlatformAuditApplicationService
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting
from raad.modules.platform_audit.domain.repositories import (
    AuditEntryRepository,
    SystemSettingRepository,
)
from raad.modules.platform_audit.domain.value_objects import AuditEntryId, SystemSettingKey

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc))


def make_actor() -> Principal:
    return Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)


class InMemoryAuditEntryRepository(AuditEntryRepository):
    def __init__(self, entries: list[AuditEntry] | None = None) -> None:
        self.entries = entries or []

    async def get(self, entry_id: AuditEntryId) -> AuditEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    async def list_all(self) -> list[AuditEntry]:
        return list(self.entries)


class InMemorySystemSettingRepository(SystemSettingRepository):
    def __init__(self) -> None:
        self.by_key: dict[str, SystemSetting] = {}

    async def get(self, key: SystemSettingKey) -> SystemSetting | None:
        return self.by_key.get(str(key))

    def add(self, setting: SystemSetting) -> None:
        self.by_key[str(setting.key)] = setting

    async def list_all(self) -> list[SystemSetting]:
        return list(self.by_key.values())


class FakePlatformAuditUnitOfWork(PlatformAuditUnitOfWork):
    def __init__(
        self,
        audit_entries: InMemoryAuditEntryRepository,
        system_settings: InMemorySystemSettingRepository,
    ) -> None:
        self.audit_entries = audit_entries
        self.system_settings = system_settings
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_uow(entries: list[AuditEntry] | None = None) -> FakePlatformAuditUnitOfWork:
    return FakePlatformAuditUnitOfWork(
        InMemoryAuditEntryRepository(entries), InMemorySystemSettingRepository()
    )


def make_service() -> PlatformAuditApplicationService:
    return PlatformAuditApplicationService(clock=CLOCK)


class ListAuditEntriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_audit_entries_returns_all(self) -> None:
        entry = AuditEntry(
            id=AuditEntryId("01J8Z3K9G6X8YV5T4N2R7QW3AE"),
            organization_id=None,
            actor_user_id=None,
            action="TripStarted",
            entity_type="Trip",
            entity_id="01J8Z3K9G6X8YV5T4N2R7QW3TR",
            metadata=None,
            ip=None,
            correlation_id=None,
            created_at=CLOCK.now(),
        )
        service = make_service()
        uow = make_uow(entries=[entry])
        dtos = await service.list_audit_entries(ListAuditEntriesQuery(), uow=uow)
        self.assertEqual(len(dtos), 1)
        self.assertEqual(dtos[0].action, "TripStarted")

    async def test_list_audit_entries_empty(self) -> None:
        service = make_service()
        uow = make_uow()
        dtos = await service.list_audit_entries(ListAuditEntriesQuery(), uow=uow)
        self.assertEqual(dtos, [])


class SetSystemSettingTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_creates_new_setting(self) -> None:
        service = make_service()
        uow = make_uow()
        setting = await service.set_system_setting(
            SetSystemSettingCommand(
                key="maps.provider",
                value={"provider": "google"},
                scope="platform",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(setting.key, "maps.provider")
        self.assertEqual(setting.value, {"provider": "google"})
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(len(uow.system_settings.by_key), 1)

    async def test_set_updates_existing_setting_without_duplicating(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.set_system_setting(
            SetSystemSettingCommand(
                key="maps.provider",
                value={"provider": "google"},
                scope="platform",
                actor=make_actor(),
            ),
            uow=uow,
        )
        updated = await service.set_system_setting(
            SetSystemSettingCommand(
                key="maps.provider",
                value={"provider": "mapbox"},
                scope="platform",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(updated.value, {"provider": "mapbox"})
        self.assertEqual(len(uow.system_settings.by_key), 1, "must update, not duplicate")

    async def test_get_system_setting_returns_none_when_missing(self) -> None:
        service = make_service()
        uow = make_uow()
        result = await service.get_system_setting(
            GetSystemSettingQuery(key="does.not.exist"), uow=uow
        )
        self.assertIsNone(result)

    async def test_list_system_settings_returns_all(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.set_system_setting(
            SetSystemSettingCommand(
                key="maps.provider", value={"x": 1}, scope="platform", actor=make_actor()
            ),
            uow=uow,
        )
        settings = await service.list_system_settings(ListSystemSettingsQuery(), uow=uow)
        self.assertEqual(len(settings), 1)


if __name__ == "__main__":
    unittest.main()
