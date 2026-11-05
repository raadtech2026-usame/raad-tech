"""The data_transfer bounded context.

Provides centralized enterprise bulk data collection, Excel template management,
validation engine, batch ingestion into tenant context, and persistent import history.
Managed exclusively by RAAD-TECH Platform Administration (Super Admin).
"""

from raad.modules.data_transfer.api.routers import data_transfer_admin_router
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.application.services import (
    DataTransferApplicationService,
)
from raad.modules.data_transfer.domain.entities import ImportBatch
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportBatchId,
    ImportResourceType,
    ImportStatus,
)

__all__ = [
    "ConflictStrategy",
    "DataTransferApplicationService",
    "DataTransferUnitOfWork",
    "ImportBatch",
    "ImportBatchId",
    "ImportResourceType",
    "ImportStatus",
    "data_transfer_admin_router",
]
