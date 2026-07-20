"""Platform & Audit entities (Backend LLD §5.2; Database Design §8.7/§8.9). Framework-free — no
SQLAlchemy/FastAPI/Pydantic, no I/O.

**`AuditEntry` is a read-model, not a mutable aggregate — deliberately no `_AggregateRoot`
base, no domain events, no behavior methods.** It is never created or mutated through this
module: every row is written transactionally by the shared-kernel `core.audit.writer.AuditWriter`
(ADR-0007) from every *other* module's own `UnitOfWork.commit()`. This module's only relationship
to `audit_entries` is read-only (`GET /admin/audit`), so `AuditEntry` here is a plain frozen
dataclass — the identical "immutable projection, no lifecycle" shape a query-side DTO would have,
just kept in `domain/` (rather than `application/queries.py`) because Database Design §2.1 names
it as one of this bounded context's three owned entities (`AuditEntry`, `SystemSetting`,
`Integration`), the same module-ownership listing every other aggregate in this codebase traces
back to.

**`SystemSetting` (Database Design §8.9: `system_settings(key PK, value_json, scope)`) is a real,
mutable aggregate** — `GET/PATCH /admin/settings` (API Contracts §4.8) gives it actual documented
write semantics, unlike `Integration` below.

**`Integration` (Database Design §8.9: `integrations(id, organization_id?, type, config_json,
status, +audit)`) is deliberately not built this phase — flagged, not silently dropped.** Unlike
`TransportFee`/`Route.remove_stop` (the codebase's established "use-case exists, no approved
endpoint yet" precedent — a *complete* domain/application layer with no HTTP route), no approved
document gives `Integration` any lifecycle verbs, status enum values, or even a create/read use
case description at all — API Contracts §4.8's table has no `/admin/integrations` row of any
kind. Building domain behavior methods for it would mean inventing a lifecycle no document
specifies, which the task's own "don't invent it" discipline forbids; the column list alone
(without any documented behavior) is not a sufficient basis for a DDD aggregate with real
invariants. Deferred pending a future phase that documents its actual use case.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.platform_audit.domain import events as platform_audit_events
from raad.modules.platform_audit.domain.value_objects import (
    AuditEntryId,
    OrganizationId,
    SystemSettingKey,
    UserId,
)

_SCOPE_MAX_LENGTH = 60  # Database Design §8.9 gives no explicit length (compact notation)


class AuditEntry:
    """`audit_entries` (Database Design §8.7) — see module docstring for why this is a plain
    read-model, not an `_AggregateRoot`."""

    def __init__(
        self,
        *,
        id: AuditEntryId,
        organization_id: OrganizationId | None,
        actor_user_id: UserId | None,
        action: str,
        entity_type: str | None,
        entity_id: str | None,
        metadata: dict[str, Any] | None,
        ip: str | None,
        correlation_id: str | None,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.action = action
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.metadata = metadata
        self.ip = ip
        self.correlation_id = correlation_id
        self.created_at = created_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AuditEntry) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics, duplicated per module deliberately —
    `.claude/rules/backend.md` #1 forbids one module reaching into another's internals (identical
    to every other module's own `_AggregateRoot` copy)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class SystemSetting(_AggregateRoot):
    """`system_settings` (Database Design §8.9). Keyed by `key`, not a ULID `id` — the table's
    own documented primary key."""

    def __init__(
        self,
        *,
        key: SystemSettingKey,
        value: dict[str, Any],
        scope: str,
    ) -> None:
        super().__init__()
        _validate_scope(scope)
        self.key = key
        self.value = value
        self.scope = scope

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SystemSetting) and self.key == other.key

    def __hash__(self) -> int:
        return hash(self.key)

    @classmethod
    def set(
        cls,
        *,
        key: SystemSettingKey,
        value: dict[str, Any],
        scope: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "SystemSetting":
        """`PATCH /admin/settings` (API Contracts §4.8) when `key` doesn't exist yet —
        create-or-update in one operation, since §8.9 documents no separate "does not exist yet"
        error case for a settings key the way e.g. `ensure_email_available` guards a real
        uniqueness constraint elsewhere; a system setting is closer to a config map entry than an
        aggregate with a creation-vs-update distinction worth enforcing. `SystemSettingSet` has no
        approved document naming it — this phase's own flagged choice, matching every prior
        phase's own unnamed creation events."""
        setting = cls(key=key, value=value, scope=scope)
        setting._record(
            platform_audit_events.system_setting_set(
                key=str(key),
                scope=scope,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return setting

    def update_value(
        self, value: dict[str, Any], *, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Idempotent same-value no-op, matching every other module's "no event for no real
        change" convention."""
        if value == self.value:
            return
        self.value = value
        self._record(
            platform_audit_events.system_setting_updated(
                key=str(self.key),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


def _validate_scope(scope: str) -> None:
    if not scope:
        raise DomainError("SystemSetting scope must not be empty")
    if len(scope) > _SCOPE_MAX_LENGTH:
        raise DomainError(
            f"SystemSetting scope must be at most {_SCOPE_MAX_LENGTH} characters: {len(scope)}"
        )
