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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from raad.core.events.base import DomainEvent

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

    async def commit(self) -> None:
        await self._outbox_writer.write_all(self.session, self._events)
        await self._audit_writer.write_all(self.session, self._events)
        await self.session.commit()
        self._events.clear()

    async def rollback(self) -> None:
        await self.session.rollback()
        self._events.clear()
