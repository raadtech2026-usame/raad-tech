"""Mappers between data_transfer domain entities and SQLAlchemy ORM models."""

from __future__ import annotations

from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportStatus,
)
from raad.modules.data_transfer.infra.models import ImportBatchModel


def import_batch_to_model(entity: ImportBatch) -> ImportBatchModel:
    return ImportBatchModel(
        id=entity.id,
        organization_id=entity.organization_id,
        actor_user_id=entity.actor_user_id,
        resource_type=entity.resource_type,
        status=entity.status.value if isinstance(entity.status, ImportStatus) else str(entity.status),
        original_filename=entity.original_filename,
        file_size_bytes=entity.file_size_bytes,
        total_rows=entity.total_rows,
        created_count=entity.created_count,
        updated_count=entity.updated_count,
        skipped_count=entity.skipped_count,
        failed_count=entity.failed_count,
        conflict_strategy=(
            entity.conflict_strategy.value
            if isinstance(entity.conflict_strategy, ConflictStrategy)
            else str(entity.conflict_strategy)
        ) if entity.conflict_strategy else None,
        error_report_available=entity.error_report_available,
        committed_at=entity.committed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def model_to_import_batch(model: ImportBatchModel) -> ImportBatch:
    return ImportBatch(
        id=model.id,
        organization_id=model.organization_id,
        actor_user_id=model.actor_user_id,
        resource_type=model.resource_type,
        status=ImportStatus(model.status),
        original_filename=model.original_filename,
        file_size_bytes=model.file_size_bytes,
        total_rows=model.total_rows,
        created_count=model.created_count,
        updated_count=model.updated_count,
        skipped_count=model.skipped_count,
        failed_count=model.failed_count,
        conflict_strategy=ConflictStrategy(model.conflict_strategy) if model.conflict_strategy else ConflictStrategy.SKIP_INVALID,
        error_report_available=model.error_report_available,
        committed_at=model.committed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
