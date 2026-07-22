"""Platform & Audit application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models).
Mirrors `billing.application.queries`'s single-DTO-per-aggregate convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
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
