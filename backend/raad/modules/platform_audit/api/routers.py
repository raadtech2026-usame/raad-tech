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

Two routes, matching API Contracts §4.8's documented table (lines 190-191):
- `GET /admin/audit` — Founder / in-scope admin, "audit log (scoped, read-only)".
- `GET /admin/settings` / `PATCH /admin/settings` — Founder / Org Admin, "system/org settings".

**No `/admin/integrations` route** — `domain/entities.py`'s own module docstring explains why
`Integration` is not built this phase at all (no documented lifecycle, no API Contracts row).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.platform_audit.api.deps import (
    get_platform_audit_service,
    get_platform_audit_uow,
)
from raad.modules.platform_audit.api.schemas import (
    AuditEntryResponse,
    SetSystemSettingRequest,
    SystemSettingResponse,
)
from raad.modules.platform_audit.application.commands import SetSystemSettingCommand
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import (
    AuditEntryDTO,
    ListAuditEntriesQuery,
    ListSystemSettingsQuery,
    SystemSettingDTO,
)
from raad.modules.platform_audit.application.services import PlatformAuditApplicationService

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


@admin_router.get(
    "/audit",
    response_model=list[AuditEntryResponse],
    status_code=status.HTTP_200_OK,
    summary="List audit entries",
    description=(
        "Founder / in-scope admin (API Contracts §4.8 line 190). Scoped, read-only. "
        "Every row is written transactionally by another module's own commit — see ADR-0007."
    ),
)
async def list_audit_entries(
    principal: Principal = Depends(require_permission(Permission("admin.audit.read"))),
    service: PlatformAuditApplicationService = Depends(get_platform_audit_service),
    uow: PlatformAuditUnitOfWork = Depends(get_platform_audit_uow),
) -> list[AuditEntryResponse]:
    entries = await service.list_audit_entries(ListAuditEntriesQuery(), uow=uow)
    return [_audit_entry_dto_to_response(entry) for entry in entries]


@admin_router.get(
    "/settings",
    response_model=list[SystemSettingResponse],
    status_code=status.HTTP_200_OK,
    summary="List system settings",
    description="Founder / Org Admin (API Contracts §4.8 line 191).",
)
async def list_system_settings(
    principal: Principal = Depends(require_permission(Permission("admin.settings.read"))),
    service: PlatformAuditApplicationService = Depends(get_platform_audit_service),
    uow: PlatformAuditUnitOfWork = Depends(get_platform_audit_uow),
) -> list[SystemSettingResponse]:
    settings = await service.list_system_settings(ListSystemSettingsQuery(), uow=uow)
    return [_system_setting_dto_to_response(setting) for setting in settings]


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
