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


def _unpadded(value: str | None) -> str | None:
    """`audit_entries.organization_id`/`actor_user_id`/`entity_id`/`correlation_id` are all
    `CHAR(26)` (Database Design §8.7) — PostgreSQL blank-pads `CHAR(n)` storage on `SELECT`
    (unlike `VARCHAR`), the same permanent lesson `billing.infra.mappers.model_to_payment`
    already applies to `payments.idempotency_key`. A 26-character ULID happens to fill the
    column exactly, so this was invisible for every ordinary actor id — until `SYSTEM_PRINCIPAL`
    (`core/audit/writer.py`), whose `user_id` is the literal short string `"system"`, came back
    over the wire as `"system"` followed by twenty blank spaces. Live-reproduced via `GET
    /admin/audit?filter[entity_type]=Subscription...`: every system-triggered lifecycle event's
    `actor_user_id` carried the padding straight into the JSON response."""
    return value.rstrip() if value is not None else None


def audit_entry_model_to_domain(model: AuditEntryRecord) -> AuditEntry:
    organization_id = _unpadded(model.organization_id)
    actor_user_id = _unpadded(model.actor_user_id)
    return AuditEntry(
        id=AuditEntryId(model.id),
        organization_id=OrganizationId(organization_id) if organization_id else None,
        actor_user_id=UserId(actor_user_id) if actor_user_id else None,
        action=model.action,
        entity_type=model.entity_type,
        entity_id=_unpadded(model.entity_id),
        metadata=model.metadata_json,
        ip=model.ip,
        correlation_id=_unpadded(model.correlation_id),
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
