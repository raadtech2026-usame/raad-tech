"""Unit of Work (Backend LLD §8).

Owns the transaction boundary for a single command: wraps a database session, buffers
domain events, and commits business rows + outbox rows atomically. Per-module repository
properties (e.g. `trips: TripRepository`) are added by each module's own UoW extension once
that module's domain/infra exist — not hardcoded here, since no module has one yet.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Table
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from raad.core.db.base import Base
from raad.core.db.mixins import AuditActorMixin
from raad.core.events.base import DomainEvent
from raad.core.logging.context import principal_id_var
from raad.core.tenancy.scope import TenantRegionScope

_ACTOR_ID_LENGTH = 26  # `created_by`/`updated_by` are CHAR(26) user ULIDs.


def _stamp_actor_columns(session: AsyncSession) -> None:
    """Fills `created_by`/`updated_by` on every audited row this commit writes.

    The columns existed on every audited table and nothing ever wrote them — the actor was
    recorded only in `audit_entries`. The acting user is already bound per request by
    `interfaces/http/middleware.py` (the same context variable every log line reads), so it is
    read here, at the one point every write passes through, rather than threaded through every
    repository. Outside a request (workers, scheduled jobs, signed webhooks) nothing is bound
    and the columns stay NULL, which `AuditActorMixin` already defines as "system".

    `updated_by` is set only on rows with a real attribute change. Repositories re-project every
    tracked aggregate onto its row before commit, including ones that were only read; stamping
    those would turn a read into an UPDATE and bump their `row_version`.
    """
    actor_id = principal_id_var.get()
    if not actor_id or len(actor_id) > _ACTOR_ID_LENGTH:
        return
    sync_session = session.sync_session
    for instance in sync_session.new:
        if isinstance(instance, AuditActorMixin):
            if instance.created_by is None:
                instance.created_by = actor_id
            instance.updated_by = actor_id
    for instance in sync_session.dirty:
        if isinstance(instance, AuditActorMixin) and sync_session.is_modified(instance):
            instance.updated_by = actor_id

if TYPE_CHECKING:
    # Deferred to break the core.db <-> core.events / core.db <-> core.audit import cycles
    # (core.events.outbox and core.audit.writer both need `core.db.base.Base`; this module only
    # needs `OutboxWriter`/`AuditWriter` for type hints, which `from __future__ import
    # annotations` already makes lazily-evaluated strings, so no runtime import is required).
    from raad.core.audit.writer import AuditWriter
    from raad.core.events.outbox import OutboxWriter


class UnitOfWork(ABC):
    """Context-managed. One instance per command, request-scoped via DI (§9.1)."""

    async def __aenter__(self) -> "UnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    @abstractmethod
    def record_events(self, events: Sequence[DomainEvent]) -> None:
        """Buffers domain events raised by aggregate behavior for atomic, post-commit
        publication via the outbox (§4.3 step 5, §10)."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Persists business rows and buffered events' outbox rows in one transaction."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Concrete UoW (§8, §6.2). Opens one `AsyncSession` per instance (i.e. per command) on
    `__aenter__`, buffers events in memory, and on `commit()` writes them to the outbox
    (`OutboxWriter`) in the *same* flush/transaction as whatever business rows the command's
    repositories already added to the session — the "no event without a committed state
    change, and no committed state change silently without its event" guarantee (§8.3).

    Carries no module-specific repository properties — a future module extends this class
    (e.g. `class TransportOpsUnitOfWork(SqlAlchemyUnitOfWork): trips: TripRepository`) to add
    its own, constructing them from `self.session` once that module's `infra/repositories.py`
    exists.

    **`audit_writer` (ADR-0007, Backend Stabilization phase)** writes one `audit_entries` row
    per buffered event in `commit()`, the same transaction as `outbox_writer` and the business
    rows themselves — the resolution to the confirmed conflict between Database Design §10
    ("audit_entries... written transactionally by the domain") and `.claude/rules/backend.md`
    #3 (no module may write another module's tables; `audit_entries` is `platform_audit`-owned).
    See `core/audit/writer.py`'s module docstring for the full architecture. Required (not
    defaulted) — every module's `SqlAlchemy<Module>UnitOfWork` factory binding
    (`core/di/bootstrap.py`) passes the same DI-bound singleton, mirroring `outbox_writer`'s
    identical treatment exactly rather than self-constructing a default, so this class has
    exactly one way any dependency reaches it: the composition root.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        outbox_writer: OutboxWriter,
        audit_writer: AuditWriter,
    ) -> None:
        self._session_factory = session_factory
        self._outbox_writer = outbox_writer
        self._audit_writer = audit_writer
        self._session: AsyncSession | None = None
        self._events: list[DomainEvent] = []
        #: ADR-0021: the caller's resolved tenant/region scope, applied to every repository this
        #: UoW constructs on `__aenter__`. Defaults to unrestricted — matches this class's
        #: pre-ADR-0021 behavior for any construction path that never sets it (CLI scripts,
        #: background workers, tests). `get_<module>_uow` (each module's `api/deps.py`) is the
        #: only place that sets a real, resolved scope, before `__aenter__` is ever called (every
        #: `get_<module>_uow` today returns the UoW un-entered — see that dependency's own
        #: docstring) — never re-set mid-request.
        self.scope: TenantRegionScope = TenantRegionScope(organization_ids=None)

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("SqlAlchemyUnitOfWork used outside of 'async with'.")
        return self._session

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await super().__aexit__(exc_type, exc, tb)
        await self.session.close()
        self._session = None

    def record_events(self, events: Sequence[DomainEvent]) -> None:
        self._events.extend(events)

    async def _flush_in_dependency_order(self) -> None:
        """Flushes pending inserts table by table, parents before children.

        **Why this is necessary at all.** SQLAlchemy orders the INSERTs it emits during a flush
        by *mapper* dependency edges, and those edges come from `relationship()` — **not** from
        table-level `ForeignKey`s. This codebase declares `relationship()` only for
        intra-aggregate composition (`DeviceModel.cameras`, `RouteModel.stops`); two separate
        aggregates always reference each other by a plain FK column with no relationship, because
        a navigable attribute between aggregates is exactly the coupling DDD forbids here. So for
        every cross-aggregate FK the ORM has no edge, and the flush falls back to ordering mappers
        by `_sort_key` — the fully-qualified class name.

        That is alphabetical, and it is silently wrong. `billing` is the proven case:
        `InvoiceModel` sorts before `SubscriptionModel`, so `open_organization_subscription` —
        which creates a `Subscription` and its first `Invoice` in one Unit of Work — emitted
        `INSERT INTO invoices` first and died on `fk_invoices__subscriptions` every single time.
        No subscription has ever been persisted on a live database as a result.

        **Why the order is derived, not listed.** `MetaData.sorted_tables` is SQLAlchemy's own
        topological sort of tables *by their ForeignKeys*, which is precisely the information the
        mapper-level sort is missing. Deriving from it means a new table, a new module or a new
        FK is ordered correctly the day it is added — a hand-maintained list would be one more
        thing to forget, and forgetting it looks exactly like this bug.

        **Why not add `relationship()` instead.** It would fix the ordering and break the
        aggregate boundary: `Invoice` would become reachable from `Subscription`, inviting
        exactly the cross-aggregate navigation the repository-per-aggregate design exists to
        prevent. Ordering is a persistence concern and belongs here, in `infra`.

        Single-table flushes — the overwhelming majority — take the fast path and behave exactly
        as before: one `flush()`, no extra round trips.
        """
        session = self.session
        pending_by_table: dict[Table, list[object]] = {}
        for instance in session.new:
            mapper = sa_inspect(instance).mapper
            pending_by_table.setdefault(mapper.local_table, []).append(instance)

        if len(pending_by_table) < 2:
            await session.flush()
            return

        order = {table: index for index, table in enumerate(Base.metadata.sorted_tables)}
        # An unmapped/unknown table sorts last rather than first: it cannot be a dependency of
        # anything we know about, and guessing "first" would reintroduce the very failure above.
        for table in sorted(
            pending_by_table, key=lambda t: order.get(t, len(order))
        ):
            await session.flush(pending_by_table[table])
        # Catches anything the per-table passes left pending (cascades, mutations on existing
        # rows), so callers still see one fully-flushed session before the outbox is written.
        await session.flush()

    async def commit(self) -> None:
        # Before anything else writes to this session. `OutboxWriter`/`AuditWriter` both emit
        # their own statements, and a statement triggers autoflush — which would flush the
        # business rows in SQLAlchemy's own broken order before this method ever got the chance
        # to impose the right one.
        _stamp_actor_columns(self.session)
        await self._flush_in_dependency_order()
        await self._outbox_writer.write_all(self.session, self._events)
        await self._audit_writer.write_all(self.session, self._events)
        await self.session.commit()
        self._events.clear()

    async def rollback(self) -> None:
        await self.session.rollback()
        self._events.clear()
