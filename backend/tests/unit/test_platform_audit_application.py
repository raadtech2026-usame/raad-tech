"""Application-layer tests for `platform_audit`'s `PlatformAuditApplicationService` (Backend
Stabilization phase; pagination coverage added under the Tier 2 pagination phase). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring `test_video_application.py`'s
exact structure. In-memory fakes for both repositories — no SQLAlchemy, no FastAPI, no real
database.

Covers: `list_audit_entries` (read-only, no create path from this module), `set_system_setting`'s
create-or-update orchestration, `list_system_settings`/`get_system_setting`, and — new this
phase — both list methods' pagination/filtering, plus a regression test proving
`list_system_settings` defaults an empty `sort` to `key` (`SystemSettingModel` has no `id`
column, unlike every other model in this codebase — see `application/services.py`'s own
docstring).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
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


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str | None = None,
    default_sort_field: str = "id",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), duplicated per module's own test file — mirrors
    `test_organization_application.py`'s identical helper exactly. `default_sort_field` lets
    `SystemSetting`'s fake mirror the real repository's own quirk: `SystemSettingModel` has no
    `id` column (unlike every other aggregate in this codebase), so its own fallback ordering key
    is `key`, not `id`."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search and search_field:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: _field_text(item, default_sort_field))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


class InMemoryAuditEntryRepository(AuditEntryRepository):
    def __init__(self, entries: list[AuditEntry] | None = None) -> None:
        self.entries = entries or []

    async def get(self, entry_id: AuditEntryId) -> AuditEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    async def list_all(self) -> list[AuditEntry]:
        return list(self.entries)

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[AuditEntry]:
        return _paginate_in_memory(
            list(self.entries),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            default_sort_field="id",
        )


class InMemorySystemSettingRepository(SystemSettingRepository):
    def __init__(self) -> None:
        self.by_key: dict[str, SystemSetting] = {}

    async def get(self, key: SystemSettingKey) -> SystemSetting | None:
        return self.by_key.get(str(key))

    def add(self, setting: SystemSetting) -> None:
        self.by_key[str(setting.key)] = setting

    async def list_all(self) -> list[SystemSetting]:
        return list(self.by_key.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[SystemSetting]:
        return _paginate_in_memory(
            list(self.by_key.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            default_sort_field="key",
        )


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
        page = await service.list_audit_entries(
            ListAuditEntriesQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.data[0].action, "TripStarted")

    async def test_list_audit_entries_empty(self) -> None:
        service = make_service()
        uow = make_uow()
        page = await service.list_audit_entries(
            ListAuditEntriesQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(page.data, [])
        self.assertEqual(page.total, 0)


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
        page = await service.list_system_settings(
            ListSystemSettingsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)


class AuditEntryPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    def _make_entry(self, *, suffix: str, action: str, entity_type: str = "Trip") -> AuditEntry:
        return AuditEntry(
            id=AuditEntryId(f"01J8Z3K9G6X8YV5T4N2R7QW3{suffix}"),
            organization_id=None,
            actor_user_id=None,
            action=action,
            entity_type=entity_type,
            entity_id=None,
            metadata=None,
            ip=None,
            correlation_id=None,
            created_at=CLOCK.now(),
        )

    async def test_list_audit_entries_paginates_and_reports_total(self) -> None:
        entries = [
            self._make_entry(suffix=f"A{i}", action=f"Action{i}") for i in range(3)
        ]
        service = make_service()
        uow = make_uow(entries=entries)

        page = await service.list_audit_entries(
            ListAuditEntriesQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_audit_entries(
            ListAuditEntriesQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_audit_entries_filters_by_action(self) -> None:
        entries = [
            self._make_entry(suffix="A1", action="TripStarted"),
            self._make_entry(suffix="A2", action="TripEnded"),
        ]
        service = make_service()
        uow = make_uow(entries=entries)

        page = await service.list_audit_entries(
            ListAuditEntriesQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="action", op="eq", value="TripStarted")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].action, "TripStarted")


class SystemSettingPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_system_settings_paginates_and_reports_total(self) -> None:
        service = make_service()
        uow = make_uow()
        for i in range(3):
            await service.set_system_setting(
                SetSystemSettingCommand(
                    key=f"setting.{i}", value={"x": i}, scope="platform", actor=make_actor()
                ),
                uow=uow,
            )

        page = await service.list_system_settings(
            ListSystemSettingsQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_system_settings_filters_by_scope(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.set_system_setting(
            SetSystemSettingCommand(
                key="maps.provider", value={"a": 1}, scope="platform", actor=make_actor()
            ),
            uow=uow,
        )
        await service.set_system_setting(
            SetSystemSettingCommand(
                key="org.feature", value={"b": 1}, scope="organization", actor=make_actor()
            ),
            uow=uow,
        )

        page = await service.list_system_settings(
            ListSystemSettingsQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="scope", op="eq", value="organization")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].key, "org.feature")

    async def test_list_system_settings_defaults_to_sort_by_key_when_no_sort_given(
        self,
    ) -> None:
        """Regression: `SystemSettingModel` has no `id` column (unlike every other aggregate in
        this codebase) — `PlatformAuditApplicationService.list_system_settings` must default an
        empty `sort` to `[SortSpec(field="key")]` itself, since `SqlAlchemyRepositoryBase.
        list_page`'s own empty-sort fallback (`.order_by(self.model.id.asc())`) would otherwise
        crash for this aggregate alone. The in-memory fake mirrors that same default (its own
        `default_sort_field="key"`), so this test would fail with a wrong order if the
        application-service-level guard were ever removed."""
        service = make_service()
        uow = make_uow()
        for key in ("zebra.setting", "alpha.setting", "mango.setting"):
            await service.set_system_setting(
                SetSystemSettingCommand(key=key, value={}, scope="platform", actor=make_actor()),
                uow=uow,
            )

        page = await service.list_system_settings(
            ListSystemSettingsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(
            [s.key for s in page.data],
            ["alpha.setting", "mango.setting", "zebra.setting"],
        )


if __name__ == "__main__":
    unittest.main()
