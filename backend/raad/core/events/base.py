"""Domain event envelope (Backend LLD §10.3; outbox row shape per Database Design §8.8).

Every domain event, regardless of which module emits it, is carried in this shape once it
reaches the outbox/broker. Modules define their own event *payload* shapes under
`modules/<context>/domain/events.py`; this is the transport-level envelope around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_type: str
    version: int
    occurred_at: datetime
    org_id: str | None
    correlation_id: str | None
    payload: dict[str, Any]
    aggregate_type: str
    #: `None` for a handful of composite-key "aggregates" with no real minted ULID identity
    #: (`iam`'s `RolePermission`, `organization`'s `ScopeAssignment` — pure grant/revoke
    #: reference data, `RolePermissionRepository`'s own docstring). `audit_entries.entity_id`
    #: (`core/audit/writer.py`) is `CHAR(26)` — a composite string like `f"{role}:{permission}"`
    #: can (and, live-verified, does: `StringDataRightTruncationError`) exceed that length,
    #: unlike every ULID-keyed aggregate's `aggregate_id`. The full identifying data is never
    #: lost even when this is `None` — it's already carried in `payload` (e.g.
    #: `{"role": ..., "permission": ...}`), which is what these two events' own factories rely
    #: on instead of fabricating an oversized or truncated id.
    aggregate_id: str | None
