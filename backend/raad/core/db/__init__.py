"""Database foundation (Backend LLD §7, §8, §17 `db`): async engine, session factory,
declarative base + naming convention, audit-column mixins, Unit of Work, and repository
infrastructure. No module ORM models, no business tables, no repositories for any module —
those are added by each module's own `infra/` once its domain layer exists.
"""

from raad.core.db.base import NAMING_CONVENTION, Base
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.db.mixins import (
    AuditActorMixin,
    AuditedTableMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UlidPrimaryKeyMixin,
    utcnow,
)
from raad.core.db.repository import (
    Page,
    Repository,
    Specification,
    SqlAlchemyRepositoryBase,
    TenantScopedRepository,
)
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork

__all__ = [
    "NAMING_CONVENTION",
    "AuditActorMixin",
    "AuditedTableMixin",
    "Base",
    "Page",
    "Repository",
    "Specification",
    "SoftDeleteMixin",
    "SqlAlchemyRepositoryBase",
    "SqlAlchemyUnitOfWork",
    "TenantScopedRepository",
    "TimestampMixin",
    "UlidPrimaryKeyMixin",
    "UnitOfWork",
    "build_engine",
    "build_session_factory",
    "utcnow",
]
