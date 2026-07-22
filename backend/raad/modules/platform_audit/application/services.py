"""Platform & Audit application service (Backend LLD §4.1/§4.3). One
`PlatformAuditApplicationService` class covering both aggregates, mirroring
`video.application.services.VideoApplicationService`'s single-service-per-phase shape.
"""

from __future__ import annotations

from raad.core.pagination import OffsetPage, SortSpec
from raad.core.time.clock import Clock
from raad.modules.platform_audit.application.commands import SetSystemSettingCommand
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import (
    AuditEntryDTO,
    GetSystemSettingQuery,
    ListAuditEntriesQuery,
    ListSystemSettingsQuery,
    SystemSettingDTO,
    audit_entry_to_dto,
    system_setting_to_dto,
)
from raad.modules.platform_audit.domain.entities import SystemSetting
from raad.modules.platform_audit.domain.value_objects import SystemSettingKey


class PlatformAuditApplicationService:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    # --- AuditEntry (read-only) --------------------------------------------------------------

    async def list_audit_entries(
        self, query: ListAuditEntriesQuery, *, uow: PlatformAuditUnitOfWork
    ) -> OffsetPage[AuditEntryDTO]:
        """`GET /admin/audit` (API Contracts §4.8/§7/§8: "Founder / in-scope admin | audit log
        (scoped, read-only)", paginated/filterable/sortable). Tenant/region scoping is applied
        at the infra layer (`domain/repositories.py`'s `AuditEntryRepository.list_page`
        docstring)."""
        async with uow:
            page = await uow.audit_entries.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[audit_entry_to_dto(entry) for entry in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    # --- SystemSetting -----------------------------------------------------------------------

    async def set_system_setting(
        self, command: SetSystemSettingCommand, *, uow: PlatformAuditUnitOfWork
    ) -> SystemSettingDTO:
        """`PATCH /admin/settings` (API Contracts §4.8). Create-or-update in one operation — see
        `domain/entities.py`'s `SystemSetting.set` docstring for why."""
        async with uow:
            key = SystemSettingKey(command.key)
            existing = await uow.system_settings.get(key)
            if existing is None:
                setting = SystemSetting.set(
                    key=key,
                    value=command.value,
                    scope=command.scope,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.system_settings.add(setting)
            else:
                setting = existing
                setting.update_value(
                    command.value, clock=self._clock, actor_id=command.actor.user_id
                )
            uow.record_events(setting.pull_domain_events())
            await uow.commit()
            return system_setting_to_dto(setting)

    async def get_system_setting(
        self, query: GetSystemSettingQuery, *, uow: PlatformAuditUnitOfWork
    ) -> SystemSettingDTO | None:
        async with uow:
            setting = await uow.system_settings.get(SystemSettingKey(query.key))
            return system_setting_to_dto(setting) if setting is not None else None

    async def list_system_settings(
        self, query: ListSystemSettingsQuery, *, uow: PlatformAuditUnitOfWork
    ) -> OffsetPage[SystemSettingDTO]:
        """`GET /admin/settings` (API Contracts §4.8/§7/§8). Defaults an empty `query.sort` to
        `[SortSpec(field="key")]` before ever calling the repository — `SystemSettingModel` has
        no `id` column (`infra/models.py`'s own docstring), so
        `SqlAlchemyRepositoryBase.list_page`'s own empty-sort fallback
        (`.order_by(self.model.id.asc())`) would raise `AttributeError` for this aggregate
        alone, unlike every other model in this codebase. This is the one and only place that
        guard is applied."""
        async with uow:
            sort = query.sort or [SortSpec(field="key")]
            page = await uow.system_settings.list_page(
                query.page_request,
                sort=sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[system_setting_to_dto(setting) for setting in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )
