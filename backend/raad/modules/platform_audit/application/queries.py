"""Platform & Audit application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models).
Mirrors `billing.application.queries`'s single-DTO-per-aggregate convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.modules.billing.application.queries import BillingStatsDTO
from raad.modules.fleet_device.application.queries import DeviceStatsDTO, VehicleStatsDTO
from raad.modules.iam.application.queries import UserStatsDTO
from raad.modules.organization.application.queries import OrganizationStatsDTO
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting


@dataclass(frozen=True)
class ListAuditEntriesQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class AuditEntryDTO:
    id: str
    organization_id: str | None
    actor_user_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] | None
    ip: str | None
    correlation_id: str | None
    created_at: datetime


def audit_entry_to_dto(entry: AuditEntry) -> AuditEntryDTO:
    return AuditEntryDTO(
        id=str(entry.id),
        organization_id=str(entry.organization_id) if entry.organization_id else None,
        actor_user_id=str(entry.actor_user_id) if entry.actor_user_id else None,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        metadata=entry.metadata,
        ip=entry.ip,
        correlation_id=entry.correlation_id,
        created_at=entry.created_at,
    )


@dataclass(frozen=True)
class GetSystemSettingQuery:
    key: str


@dataclass(frozen=True)
class ListSystemSettingsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class SystemSettingDTO:
    key: str
    value: dict[str, Any]
    scope: str


def system_setting_to_dto(setting: SystemSetting) -> SystemSettingDTO:
    return SystemSettingDTO(key=str(setting.key), value=setting.value, scope=setting.scope)


@dataclass(frozen=True)
class SystemHealthDTO:
    """ADR-0020 §4: deliberately conservative — database reachability and whether the broker
    is bound, reusing `core.health.service.HealthCheckService` verbatim (Priority 1 Item 5),
    never a new observability mechanism. `database`/`broker` are each one of
    `HealthCheckService.DependencyStatus.label`'s three values ("ok"/"down"/"not_configured").
    **Background-worker heartbeat status is a real, flagged scope cut**: the ADR names it, but
    no existing heartbeat mechanism exists anywhere in this codebase to reuse (confirmed, not
    assumed) — inventing one would be new observability infrastructure, exactly what §4's own
    "not a new observability platform" scope limit rules out."""

    database: str
    broker: str


@dataclass(frozen=True)
class PlatformStatsDTO:
    """ADR-0020: the full platform-wide KPI grid, composed from four modules' own stats DTOs —
    `platform_audit` never reads another module's tables directly (`.claude/rules/backend.md`
    #3), only their application-layer DTOs. **Two KPIs from the ADR's own Context wishlist are
    a real, flagged scope cut, not silently dropped**: "Live Vehicle Locations" (would need
    `tracking`'s Redis state — no safe/cheap aggregate count exists there, `KEYS`/`SCAN` over
    live position keys is exactly the kind of production-risk operation this platform avoids)
    and "Active Drivers" (would need `transport_ops.Driver` — neither module is named in the
    ADR's own §1 Decision scope). Both are absent from this DTO entirely, not represented as a
    fabricated zero."""

    organizations: OrganizationStatsDTO
    vehicles: VehicleStatsDTO
    devices: DeviceStatsDTO
    users: UserStatsDTO
    billing: BillingStatsDTO
    system_health: SystemHealthDTO
