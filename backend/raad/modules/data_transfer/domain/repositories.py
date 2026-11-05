"""Repository interfaces for data_transfer domain.

Framework-free protocols (Domain Purity).
"""

from __future__ import annotations

from typing import Protocol

from raad.modules.data_transfer.domain.entities import ImportBatch


class ImportBatchRepository(Protocol):
    """Persistence operations for ImportBatch aggregate roots."""

    def add(self, batch: ImportBatch) -> None:
        """Stage an import batch record for insertion."""
        ...

    async def get(self, batch_id: str) -> ImportBatch | None:
        """Fetch an import batch by its unique ULID identifier."""
        ...

    async def list_by_organization(
        self, organization_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ImportBatch]:
        """List historical import batches for an organization in reverse chronological order."""
        ...
