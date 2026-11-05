"""Application service for centralized bulk data transfer operations.

Coordinates template generation, file validation, transactional commit into the
target organization's tenant context, batch persistence, and audit trail.
Application purity: no direct FastAPI or SQLAlchemy imports.
"""

from __future__ import annotations

from typing import Any

from raad.core.errors.exceptions import NotFoundError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportStatus,
)
from raad.modules.transport_ops.application.import_services import (
    ImportApplicationService,
    ImportCommitResult,
    ImportValidationResult,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork


class DataTransferApplicationService:
    """Centralized Enterprise Bulk Data Import Service managed by Platform Administration."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        import_service: ImportApplicationService,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._import_service = import_service

    def generate_template(
        self, resource_type: str, format_type: str = "xlsx"
    ) -> tuple[bytes, str, str]:
        """Generates starter Excel or CSV template with headers, formatting and instructions."""
        return self._import_service.generate_template(resource_type, format_type=format_type)

    async def validate_import(
        self,
        *,
        organization_id: str,
        resource_type: str,
        file_bytes: bytes,
        filename: str,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ImportValidationResult:
        """Dry-run validation of uploaded workbook targeting the selected organization scope."""
        if not file_bytes:
            raise ValidationError("Uploaded file is empty.")

        # Enforce target organization scope on the transport_ops UoW
        return await self._import_service.validate_import(
            resource_type=resource_type,
            file_bytes=file_bytes,
            filename=filename,
            organization_id=organization_id,
            uow=transport_ops_uow,
        )

    async def commit_import(
        self,
        *,
        organization_id: str,
        resource_type: str,
        file_bytes: bytes,
        filename: str,
        conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP_INVALID,
        principal: Principal,
        data_transfer_uow: DataTransferUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> tuple[ImportCommitResult, ImportBatch]:
        """Executes atomic batch ingestion in target organization scope and records batch audit record."""
        # 1. First dry-run validation to get row counts
        validation = await self.validate_import(
            organization_id=organization_id,
            resource_type=resource_type,
            file_bytes=file_bytes,
            filename=filename,
            transport_ops_uow=transport_ops_uow,
        )

        batch_id = self._id_generator.new_id()
        batch = ImportBatch.record_new(
            id=batch_id,
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            resource_type=resource_type.strip().lower(),
            original_filename=filename,
            file_size_bytes=len(file_bytes),
            total_rows=validation.total_rows,
            conflict_strategy=conflict_strategy,
            clock=self._clock,
        )

        try:
            # 2. Atomic commit into target organization
            commit_result = await self._import_service.commit_import(
                resource_type=resource_type,
                file_bytes=file_bytes,
                filename=filename,
                organization_id=organization_id,
                principal=principal,
                uow=transport_ops_uow,
            )

            # 3. Mark batch committed and record audit record
            batch.mark_committed(
                created_count=commit_result.created_count,
                updated_count=commit_result.updated_count,
                skipped_count=commit_result.skipped_count,
                error_report_available=validation.invalid_rows > 0,
                clock=self._clock,
            )

            async with data_transfer_uow:
                data_transfer_uow.batches.add(batch)
                data_transfer_uow.record_events(batch.pull_domain_events())
                await data_transfer_uow.commit()

            return commit_result, batch

        except Exception:
            batch.mark_failed(clock=self._clock)
            try:
                async with data_transfer_uow:
                    data_transfer_uow.batches.add(batch)
                    await data_transfer_uow.commit()
            except Exception:
                pass  # preserve original error
            raise

    async def list_batches(
        self,
        organization_id: str,
        *,
        data_transfer_uow: DataTransferUnitOfWork,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ImportBatch]:
        """Lists historical import batches for the target organization."""
        async with data_transfer_uow:
            return await data_transfer_uow.batches.list_by_organization(
                organization_id, limit=limit, offset=offset
            )

    async def get_batch(
        self,
        batch_id: str,
        *,
        data_transfer_uow: DataTransferUnitOfWork,
    ) -> ImportBatch:
        """Retrieves an import batch by ID."""
        async with data_transfer_uow:
            batch = await data_transfer_uow.batches.get(batch_id)
            if batch is None:
                raise NotFoundError(f"Import batch '{batch_id}' not found.")
            return batch
