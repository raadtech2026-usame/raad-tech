"""ORM <-> Domain mappers for `platform_audit` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mirrors `billing.infra.mappers`'s `existing=` in-place-update pattern for
`SystemSetting`.

**`audit_entry_model_to_domain` has no `domain_to_model` counterpart** — `AuditEntry` is never
written through this module (`domain/entities.py`'s own docstring); only the read direction
exists.
"""

from __future__ import annotations

from raad.core.audit.writer import AuditEntryRecord
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting
from raad.modules.platform_audit.domain.value_objects import (
    AuditEntryId,
    OrganizationId,
    SystemSettingKey,
    UserId,
)
from raad.modules.platform_audit.infra.models import SystemSettingModel


def audit_entry_model_to_domain(model: AuditEntryRecord) -> AuditEntry:
    return AuditEntry(
        id=AuditEntryId(model.id),
        organization_id=OrganizationId(model.organization_id)
        if model.organization_id
        else None,
        actor_user_id=UserId(model.actor_user_id) if model.actor_user_id else None,
        action=model.action,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        metadata=model.metadata_json,
        ip=model.ip,
        correlation_id=model.correlation_id,
        created_at=model.created_at,
    )


def system_setting_to_model(
    setting: SystemSetting, *, existing: SystemSettingModel | None = None
) -> SystemSettingModel:
    model = existing if existing is not None else SystemSettingModel(key=str(setting.key))
    model.value_json = setting.value
    model.scope = setting.scope
    return model


def model_to_system_setting(model: SystemSettingModel) -> SystemSetting:
    return SystemSetting(
        key=SystemSettingKey(model.key), value=model.value_json, scope=model.scope
    )
