"""SQLAlchemy repository implementations for data_transfer bounded context.

Confined strictly to infra. ADR-0021 tenant scoping applied.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.repositories import ImportBatchRepository
from raad.modules.data_transfer.infra.mappers import (
    import_batch_to_model,
    model_to_import_batch,
)
from raad.modules.data_transfer.infra.models import ImportBatchModel


class SqlAlchemyImportBatchRepository(
    SqlAlchemyRepositoryBase[ImportBatchModel], ImportBatchRepository
):
    model = ImportBatchModel

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[ImportBatch, ImportBatchModel]] = {}

    def add(self, batch: ImportBatch) -> None:
        orm_model = import_batch_to_model(batch)
        self._session.add(orm_model)
        self._tracked[batch.id] = (batch, orm_model)

    async def get(self, batch_id: str) -> ImportBatch | None:
        stmt = select(ImportBatchModel).where(ImportBatchModel.id == batch_id)
        if self._scope is not None and not self._scope.is_unrestricted:
            stmt = stmt.where(ImportBatchModel.organization_id.in_(self._scope.organization_ids or ()))
        result = await self._session.execute(stmt)
        orm_model = result.scalar_one_or_none()
        if orm_model is None:
            return None
        entity = model_to_import_batch(orm_model)
        self._tracked[entity.id] = (entity, orm_model)
        return entity

    get_by_id = get

    async def list_by_organization(
        self, organization_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ImportBatch]:
        stmt = (
            select(ImportBatchModel)
            .where(ImportBatchModel.organization_id == organization_id)
            .order_by(ImportBatchModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if self._scope is not None and not self._scope.is_unrestricted:
            stmt = stmt.where(ImportBatchModel.organization_id.in_(self._scope.organization_ids or ()))
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        entities = []
        for row in records:
            e = model_to_import_batch(row)
            self._tracked[e.id] = (e, row)
            entities.append(e)
        return entities

    def flush_tracked_changes(self) -> None:
        """Syncs modified aggregate fields back onto attached ORM models before flush."""
        for entity, orm_model in self._tracked.values():
            orm_model.status = (
                entity.status.value
                if hasattr(entity.status, "value")
                else str(entity.status)
            )
            orm_model.total_rows = entity.total_rows
            orm_model.created_count = entity.created_count
            orm_model.updated_count = entity.updated_count
            orm_model.skipped_count = entity.skipped_count
            orm_model.failed_count = entity.failed_count
            orm_model.error_report_available = entity.error_report_available
            orm_model.committed_at = entity.committed_at
            orm_model.updated_at = entity.updated_at


class SqlAlchemyDataTransferUnitOfWork(SqlAlchemyUnitOfWork, DataTransferUnitOfWork):
    """Transactional Unit of Work for data_transfer bounded context."""

    def __init__(
        self,
        session_factory,
        outbox_writer,
        audit_writer,
        *,
        scope: TenantRegionScope | None = None,
    ) -> None:
        super().__init__(
            session_factory,
            outbox_writer,
            audit_writer,
        )
        if scope is not None:
            self.scope = scope
        self.batches: SqlAlchemyImportBatchRepository = None  # type: ignore

    @property
    def import_batches(self) -> SqlAlchemyImportBatchRepository:
        return self.batches

    async def __aenter__(self) -> SqlAlchemyDataTransferUnitOfWork:
        await super().__aenter__()
        self.batches = SqlAlchemyImportBatchRepository(
            self._session, scope=self.scope
        )
        return self

    async def commit(self) -> None:
        if self.batches is not None:
            self.batches.flush_tracked_changes()
        await super().commit()
