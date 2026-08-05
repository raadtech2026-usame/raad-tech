"""Platform & Audit application service (Backend LLD §4.1/§4.3). One
`PlatformAuditApplicationService` class covering both aggregates, mirroring
`video.application.services.VideoApplicationService`'s single-service-per-phase shape.
"""

from __future__ import annotations

from datetime import timedelta

from raad.core.health.service import HealthCheckService
from raad.core.pagination import OffsetPage, SortSpec
from raad.core.time.clock import Clock
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.platform_audit.application.commands import SetSystemSettingCommand
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import (
    AuditEntryDTO,
    GetSystemSettingQuery,
    ListAuditEntriesQuery,
    ListSystemSettingsQuery,
    PlatformStatsDTO,
    SystemHealthDTO,
    SystemSettingDTO,
    audit_entry_to_dto,
    system_setting_to_dto,
)
from raad.modules.platform_audit.domain.entities import SystemSetting
from raad.modules.platform_audit.domain.value_objects import SystemSettingKey

_MAU_WINDOW_DAYS = 30
_EXPIRING_WINDOW_DAYS = 30


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


class PlatformStatsApplicationService:
    """ADR-0020: `GET /admin/platform-stats`. Composes the response by calling each owning
    module's own application service — never a direct read of another module's tables
    (`.claude/rules/backend.md` #1/#3), the same guarantee `interfaces/http/policy_guards.py`
    already demonstrates is achievable for cross-module orchestration in this codebase.

    **A distinct class from `PlatformAuditApplicationService` above**, not a method added to
    it — the ADR's own §1 names it separately ("A new `PlatformStatsApplicationService`"), and
    the two have no overlapping dependencies (this one needs four other modules' services; the
    other needs none).

    Each dependency's own Unit of Work is still resolved by the caller (the router, via that
    module's own `get_<module>_uow` FastAPI dependency) and passed in per call — this service
    holds no UoW of its own, mirroring how `interfaces/http/policy_guards.py`'s functions
    receive already-resolved UoWs rather than constructing them internally.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        organization_service: OrganizationApplicationService,
        user_service: UserApplicationService,
        vehicle_service: VehicleApplicationService,
        device_service: DeviceApplicationService,
        billing_service: BillingApplicationService,
        health_check_service: HealthCheckService,
    ) -> None:
        self._clock = clock
        self._organization_service = organization_service
        self._user_service = user_service
        self._vehicle_service = vehicle_service
        self._device_service = device_service
        self._billing_service = billing_service
        self._health_check_service = health_check_service

    async def get_platform_stats(
        self,
        *,
        org_uow: OrganizationUnitOfWork,
        iam_uow: IamUnitOfWork,
        fleet_device_uow: FleetDeviceUnitOfWork,
        billing_uow: BillingUnitOfWork,
    ) -> PlatformStatsDTO:
        # All time boundaries resolved once, here, for the whole composed response — never
        # re-derived per module (each module's own `get_*_stats` docstring gives the full
        # "policy resolved by caller" reasoning, first established by ADR-0019's
        # `SessionLimitPolicy`).
        now = self._clock.now()
        since_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        mau_since = now - timedelta(days=_MAU_WINDOW_DAYS)
        expiring_window_end = now + timedelta(days=_EXPIRING_WINDOW_DAYS)
        # "Revenue" has no documented period (ADR-0020's Context names the KPI, not a window) —
        # month-to-date is this phase's own flagged interpretive choice, the common admin-
        # dashboard framing, not silently invented without disclosure.
        revenue_window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        organizations = await self._organization_service.get_organization_stats(
            since_today=since_today, uow=org_uow
        )
        users = await self._user_service.get_user_stats(
            since_today=since_today, mau_since=mau_since, uow=iam_uow
        )
        vehicles = await self._vehicle_service.get_vehicle_stats(uow=fleet_device_uow)
        devices = await self._device_service.get_device_stats(uow=fleet_device_uow)
        billing = await self._billing_service.get_billing_stats(
            expiring_window_start=now,
            expiring_window_end=expiring_window_end,
            revenue_window_start=revenue_window_start,
            revenue_window_end=now,
            uow=billing_uow,
        )
        database_status = await self._health_check_service.check_database()
        broker_status = await self._health_check_service.check_broker()

        return PlatformStatsDTO(
            organizations=organizations,
            vehicles=vehicles,
            devices=devices,
            users=users,
            billing=billing,
            system_health=SystemHealthDTO(
                database=database_status.label, broker=broker_status.label
            ),
        )
