"""HTTP surface of the `platform_audit` module (C10). Mounted at `/api/v1/admin` (Backend LLD
§16.1). Thin controllers only (Backend LLD §16.2): parse the request, call exactly one
application-service method, return the response DTO. Mirrors `billing.api.routers`'s shape.

**Architecture Resolution (Backend Stabilization phase, High finding #5 of the pre-production
review): `platform_audit` built for the first time.** See ADR-0007
(`docs/architecture/adr/0007-audit-entries-write-architecture.md`) for the full resolution of
the `audit_entries` write-architecture conflict this module's very existence is downstream of —
every row this module's own `GET /admin/audit` reads was written by the shared-kernel
`core.audit.writer.AuditWriter`, transactionally, from another module's own `UnitOfWork.commit()`;
this router never writes an `AuditEntry`.

Three routes. Two match API Contracts §4.8's documented table (lines 190-191):
- `GET /admin/audit` — Founder / in-scope admin, "audit log (scoped, read-only)".
- `GET /admin/settings` / `PATCH /admin/settings` — Founder / Org Admin, "system/org settings".

The third, `GET /admin/platform-stats` (ADR-0020), has no API Contracts row — built directly on
the ADR's own §2 route decision, the same "use-case exists, no approved endpoint yet, built on
the architecture-decision authority" posture `/drivers` (`transport_ops`) already established.

**No `/admin/integrations` route** — `domain/entities.py`'s own module docstring explains why
`Integration` is not built this phase at all (no documented lifecycle, no API Contracts row).

**Pagination/filtering/sorting (Tier 2 pagination phase) — both list routes.** `GET /admin/audit`
and `GET /admin/settings` previously returned a bare `list[...]`; both now return
`OffsetPageResponse[...]` (API Contracts §7/§8), mirroring `iam`'s `GET /users` and
`organization`'s `GET /organizations`/`GET /regions` exactly. `GET /admin/settings` has one
quirk unique to this module: `SystemSettingModel` has no `id` column at all
(`infra/models.py`'s own docstring) — see `application/services.py`'s `list_system_settings`
docstring for how the resulting empty-sort `AttributeError` risk is guarded, one layer below
this router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import (
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.billing.api.deps import get_billing_uow
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.fleet_device.api.deps import get_fleet_device_uow
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.iam.api.deps import get_scoped_iam_uow
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.organization.api.deps import get_organization_uow
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.platform_audit.api.deps import (
    get_platform_audit_service,
    get_platform_audit_uow,
    get_platform_stats_service,
)
from raad.modules.platform_audit.api.schemas import (
    AuditEntryResponse,
    BillingStatsResponse,
    DeviceStatsResponse,
    OrganizationStatsResponse,
    PlatformStatsResponse,
    SetSystemSettingRequest,
    SystemHealthResponse,
    SystemSettingResponse,
    UserStatsResponse,
    VehicleStatsResponse,
)
from raad.modules.platform_audit.application.commands import SetSystemSettingCommand
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import (
    AuditEntryDTO,
    ListAuditEntriesQuery,
    ListSystemSettingsQuery,
    PlatformStatsDTO,
    SystemSettingDTO,
)
from raad.modules.platform_audit.application.services import (
    PlatformAuditApplicationService,
    PlatformStatsApplicationService,
)

admin_router = APIRouter()


def _audit_entry_dto_to_response(entry: AuditEntryDTO) -> AuditEntryResponse:
    return AuditEntryResponse(
        id=entry.id,
        organization_id=entry.organization_id,
        actor_user_id=entry.actor_user_id,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        metadata=entry.metadata,
        ip=entry.ip,
        correlation_id=entry.correlation_id,
        created_at=entry.created_at,
    )


def _system_setting_dto_to_response(setting: SystemSettingDTO) -> SystemSettingResponse:
    return SystemSettingResponse(key=setting.key, value=setting.value, scope=setting.scope)


def _platform_stats_dto_to_response(stats: PlatformStatsDTO) -> PlatformStatsResponse:
    return PlatformStatsResponse(
        organizations=OrganizationStatsResponse(
            total=stats.organizations.total,
            by_status=stats.organizations.by_status,
            created_today=stats.organizations.created_today,
        ),
        vehicles=VehicleStatsResponse(total=stats.vehicles.total),
        devices=DeviceStatsResponse(
            total=stats.devices.total,
            online=stats.devices.online,
            offline=stats.devices.offline,
        ),
        users=UserStatsResponse(
            total=stats.users.total,
            by_status=stats.users.by_status,
            monthly_active=stats.users.monthly_active,
            created_today=stats.users.created_today,
        ),
        billing=BillingStatsResponse(
            subscription_by_status=stats.billing.subscription_by_status,
            expiring_soon=stats.billing.expiring_soon,
            revenue=stats.billing.revenue,
        ),
        system_health=SystemHealthResponse(
            database=stats.system_health.database, broker=stats.system_health.broker
        ),
    )


@admin_router.get(
    "/audit",
    response_model=OffsetPageResponse[AuditEntryResponse],
    status_code=status.HTTP_200_OK,
    summary="List audit entries",
    description=(
        "Founder / in-scope admin (API Contracts §4.8 line 190). Scoped, read-only. "
        "Every row is written transactionally by another module's own commit — see ADR-0007. "
        "Paginated/filterable/sortable per §7/§8: `?page&page_size`, `?filter[field]=value`, "
        "`?sort=field`."
    ),
)
async def list_audit_entries(
    principal: Principal = Depends(require_permission(Permission("admin.audit.read"))),
    service: PlatformAuditApplicationService = Depends(get_platform_audit_service),
    uow: PlatformAuditUnitOfWork = Depends(get_platform_audit_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[AuditEntryResponse]:
    page = await service.list_audit_entries(
        ListAuditEntriesQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _audit_entry_dto_to_response)


@admin_router.get(
    "/settings",
    response_model=OffsetPageResponse[SystemSettingResponse],
    status_code=status.HTTP_200_OK,
    summary="List system settings",
    description=(
        "Founder / Org Admin (API Contracts §4.8 line 191). Paginated/filterable/sortable per "
        "§7/§8: `?page&page_size`, `?filter[field]=value`, `?sort=field`. Defaults to sorting "
        "by `key` when no `?sort=` is given — see `application/services.py`'s "
        "`list_system_settings` docstring for why (`SystemSettingModel` has no `id` column)."
    ),
)
async def list_system_settings(
    principal: Principal = Depends(require_permission(Permission("admin.settings.read"))),
    service: PlatformAuditApplicationService = Depends(get_platform_audit_service),
    uow: PlatformAuditUnitOfWork = Depends(get_platform_audit_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[SystemSettingResponse]:
    page = await service.list_system_settings(
        ListSystemSettingsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _system_setting_dto_to_response)


@admin_router.patch(
    "/settings",
    response_model=SystemSettingResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update a system setting",
    description=(
        "Founder / Org Admin (API Contracts §4.8 line 191). Create-or-update in one operation "
        "— see `application/services.py`'s module docstring."
    ),
)
async def set_system_setting(
    body: SetSystemSettingRequest,
    principal: Principal = Depends(require_permission(Permission("admin.settings.update"))),
    service: PlatformAuditApplicationService = Depends(get_platform_audit_service),
    uow: PlatformAuditUnitOfWork = Depends(get_platform_audit_uow),
) -> SystemSettingResponse:
    command = SetSystemSettingCommand(
        key=body.key, value=body.value, scope=body.scope, actor=principal
    )
    setting = await service.set_system_setting(command, uow=uow)
    return _system_setting_dto_to_response(setting)


@admin_router.get(
    "/platform-stats",
    response_model=PlatformStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform-wide KPI grid",
    description=(
        "ADR-0020. Founder / Regional Manager / Support Staff / Finance Staff (a new dedicated "
        "`admin.platform_stats.read` permission — the ADR's own anticipated fallback once "
        "`admin.audit.read` was confirmed not held by Finance Staff in the seeded matrix). "
        "Scoped like every other route under `/admin` (`TenantRegionScope` — unrestricted for "
        "Founder, region-limited for Regional Manager). Two KPIs named in the ADR's own Context "
        "('Live Vehicle Locations', 'Active Drivers') are a real, flagged scope cut — see "
        "`application/queries.py`'s `PlatformStatsDTO` docstring."
    ),
)
async def get_platform_stats(
    principal: Principal = Depends(
        require_permission(Permission("admin.platform_stats.read"))
    ),
    service: PlatformStatsApplicationService = Depends(get_platform_stats_service),
    org_uow: OrganizationUnitOfWork = Depends(get_organization_uow),
    iam_uow: IamUnitOfWork = Depends(get_scoped_iam_uow),
    fleet_device_uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
    billing_uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PlatformStatsResponse:
    stats = await service.get_platform_stats(
        org_uow=org_uow,
        iam_uow=iam_uow,
        fleet_device_uow=fleet_device_uow,
        billing_uow=billing_uow,
    )
    return _platform_stats_dto_to_response(stats)
