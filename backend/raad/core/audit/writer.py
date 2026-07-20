"""Audit-trail infrastructure (Database Design §8.7/§10; Backend LLD §13.1). `AuditEntryRecord`
is the ORM model for the `audit_entries` table; `AuditWriter` writes one row per `DomainEvent`
into it using the caller's own `AsyncSession` — deliberately *not* committing that session
itself, so the insert lands in the same transaction as the business change that raised the
event. This is the exact same shape as `core.events.outbox.OutboxRecord`/`OutboxWriter`,
deliberately: see ADR-0007
(`docs/architecture/adr/0007-audit-entries-write-architecture.md`) for the full resolution this
implements.

**Why this lives in `core/`, not `modules/platform_audit/`.** Database Design §10 requires
`audit_entries` to be "written **transactionally** by the domain" for every one of the ten
bounded contexts' business-meaningful actions — but `.claude/rules/backend.md` #3 forbids any
module from writing into another module's tables, and `audit_entries` is `platform_audit`
(C10)-owned per `docs/architecture/adr/0001-business-entity-module-mapping.md`. Nine other
modules each needing to write into a tenth module's table transactionally is architecturally
identical to the problem the transactional outbox already solves for domain-event publication
(Database Design DB-8 groups `audit_entries` and `outbox` together explicitly: "Immutable
`audit_entries` + `outbox` ledger — Traceability + reliable events"). ADR-0007 resolves it the
same way: `AuditWriter` lives in the shared kernel (`core/`, like `OutboxWriter`), threaded
through the one shared `SqlAlchemyUnitOfWork.commit()` every module's own UnitOfWork subclass
already extends (`core/db/unit_of_work.py`) — so every module's already-recorded domain events
also produce an audit row, transactionally, with **zero changes to any of the nine already-
shipped bounded-context modules' own source files**. `platform_audit` itself becomes purely the
**read** side (`GET /admin/audit`) — its own `infra/repositories.py` queries `AuditEntryRecord`
directly (composing `core.db.repository.SqlAlchemyRepositoryBase` exactly like every other
module's own repositories already do, since `AuditEntryRecord` has the same `UlidPrimaryKeyMixin`
shape they expect), the same "shared-kernel model, module-owned read repository" split
`core.events.outbox`/every module's own event-consuming code already uses.

**Field derivation from `DomainEvent` — deliberate, flagged mapping, not a literal transcription
of Database Design §8.7's own illustrative example.** §87's `action` column note gives one
example value, `video.session.start` (lowercase dot-notation) — but no document specifies a
transformation algorithm from this codebase's own enforced PascalCase event-naming convention
(`.claude/rules/naming.md`) to that illustrative shape, and every event already has a stable,
meaningful, already-logged name. Rather than inventing an unspecified string-splitting algorithm
that risks producing a *different*, harder-to-correlate string than what's already in
`outbox.event_type`, `action` stores `event.event_type` verbatim (e.g. `VideoSessionStarted`) —
trivially joinable against the outbox ledger DB-8 explicitly pairs it with. `entity_type`/
`entity_id` map from `aggregate_type`/`aggregate_id` (identical semantics). `actor_user_id` reads
`payload["actor_id"]` — every event factory in this codebase already includes this key (verified
across all ten modules' `domain/events.py`). `ip` has no source at the domain-event level (no
event factory in this codebase captures a request IP) and is left `NULL` — a flagged, known gap,
not silently invented; closing it would require IP capture at the HTTP-edge layer
(`interfaces/http/middleware.py`) threaded all the way through to the domain event payload, which
no approved document specifies and which changing every module's own event factories to do would
directly violate this phase's "prefer minimal changes over large redesigns" constraint.
`metadata_json` stores the event's own `payload` — already reviewed, redaction-conscious data
(the same payload already written to `outbox.payload_json`), not a second, independently-shaped
metadata structure.

**Not every domain event is filtered out as "not business-meaningful."** LLD §10's "every
important action" is read here as "every domain event this codebase already chooses to record" —
domain events in this codebase are only ever raised on genuine aggregate state changes
(`_AggregateRoot._record()`, called exclusively from behavior methods, never from read paths), so
by construction there is no noisy/trivial event stream to filter. Introducing a second,
independent audit-worthiness classification would be inventing a new business rule no document
states.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CHAR, JSON, VARCHAR, DateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin, utcnow
from raad.core.events.base import DomainEvent

_ACTION_LENGTH = 80  # Database Design §8.7: action VARCHAR(80)
_ENTITY_TYPE_LENGTH = 60  # §8.7: entity_type VARCHAR(60)
_IP_LENGTH = 45  # §8.7: ip VARCHAR(45) (IPv6-max)


class AuditEntryRecord(UlidPrimaryKeyMixin, Base):
    """`audit_entries` (Database Design §8.7) — append-only, no `updated_at`/`deleted_at`
    (§8.7's own note: "audit rows are immutable and never soft/hard deleted")."""

    __tablename__ = "audit_entries"

    organization_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    action: Mapped[str] = mapped_column(VARCHAR(_ACTION_LENGTH), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(
        VARCHAR(_ENTITY_TYPE_LENGTH), nullable=True
    )
    entity_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(VARCHAR(_IP_LENGTH), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utcnow, index=True
    )


class AuditWriter:
    """Persistence-support class writing one audit row per `DomainEvent`, in the caller's own
    session (LLD §13.1: "written transactionally by the domain, not a logging side-effect") —
    mirrors `core.events.outbox.OutboxWriter`'s identical shape exactly."""

    async def write(self, session: AsyncSession, event: DomainEvent) -> None:
        actor_user_id = event.payload.get("actor_id") if event.payload else None
        session.add(
            AuditEntryRecord(
                organization_id=event.org_id,
                actor_user_id=actor_user_id if isinstance(actor_user_id, str) else None,
                action=event.event_type,
                entity_type=event.aggregate_type,
                entity_id=event.aggregate_id,
                metadata_json=event.payload,
                ip=None,  # see module docstring — no source at the domain-event level
                correlation_id=event.correlation_id,
                created_at=event.occurred_at.replace(tzinfo=None)
                if event.occurred_at.tzinfo is not None
                else event.occurred_at,
            )
        )

    async def write_all(self, session: AsyncSession, events: list[DomainEvent]) -> None:
        for event in events:
            await self.write(session, event)
