"""Application-layer ports for data_transfer bounded context.

Abstract UnitOfWork and repository dependencies. Application purity: no SQLAlchemy or FastAPI imports.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import AsyncContextManager

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.data_transfer.domain.repositories import ImportBatchRepository


class DataTransferUnitOfWork(UnitOfWork, AsyncContextManager["DataTransferUnitOfWork"]):
    """Per-request unit of work for persisting data_transfer batch aggregates."""

    batches: ImportBatchRepository
