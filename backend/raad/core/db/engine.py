"""Async SQLAlchemy engine + session factory (Backend LLD §17 `db`: "engine, session
factory"). MySQL 8.x via the `asyncmy` driver (`.claude/rules/database.md` #1) — the
connection string is expected in `mysql+asyncmy://...` form.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from raad.core.config.settings import DbSettings


def build_engine(settings: DbSettings) -> AsyncEngine:
    """`pool_pre_ping=True` so a connection dropped by the server (idle timeout, restart) is
    detected and replaced rather than surfacing as a query-time error on the next checkout.
    """
    return create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        pool_pre_ping=True,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """`expire_on_commit=False`: the Unit of Work commits and then the request handler may
    still read attributes off already-fetched aggregates/rows for the response DTO — without
    this, every attribute access after `commit()` would trigger an implicit (and, on an async
    session, unsafe/erroring) lazy reload."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)
