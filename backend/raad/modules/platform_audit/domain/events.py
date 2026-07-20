"""Domain events for the `platform_audit` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Mirrors `billing.domain.events`'s exact
`_new_event` factory pattern.

**Only `SystemSetting` emits events here** — `AuditEntry` is a read-only projection
(`entities.py`'s own docstring); it has no lifecycle of its own within this module and so no
events of its own either. `SystemSettingSet`/`SystemSettingUpdated` have no approved document
naming them — this phase's own flagged choice, matching every prior phase's own unnamed
creation/update events.

**No `organization_id` on either event** — `system_settings` (Database Design §8.9) has no
`organization_id` column at all (its own `scope` column is the closest analogous field, but is a
free-form label, not a tenant reference — same "don't model a column no approved document
defines" discipline `billing.domain.entities.Plan`'s docstring already establishes for its own
not-tenant-owned aggregate).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=None,
        correlation_id=None,
        payload=payload,
        aggregate_type="SystemSetting",
        aggregate_id=aggregate_id,
    )


def system_setting_set(
    *, key: str, scope: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="SystemSettingSet",
        aggregate_id=key,
        occurred_at=occurred_at,
        payload={"scope": scope, "actor_id": actor_id},
    )


def system_setting_updated(
    *, key: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="SystemSettingUpdated",
        aggregate_id=key,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
