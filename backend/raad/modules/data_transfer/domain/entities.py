"""Domain entities for data_transfer bounded context.

The ImportBatch aggregate root tracks the lifecycle, audit metadata, and metrics
of a bulk data import operation.
Framework-free (Domain Purity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.data_transfer.domain.events import import_batch_committed
from raad.modules.data_transfer.domain.value_objects import (
    ConflictStrategy,
    ImportStatus,
)


@dataclass
class ImportBatch:
    id: str
    organization_id: str
    actor_user_id: str
    resource_type: str
    status: ImportStatus
    original_filename: str | None
    file_size_bytes: int | None
    total_rows: int
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    conflict_strategy: ConflictStrategy
    error_report_available: bool
    committed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def record_new(
        cls,
        *,
        id: str,
        organization_id: str,
        actor_user_id: str,
        resource_type: str,
        original_filename: str | None,
        file_size_bytes: int | None,
        total_rows: int,
        conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP_INVALID,
        clock: Clock,
    ) -> ImportBatch:
        now = clock.now()
        return cls(
            id=id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            status=ImportStatus.PENDING,
            original_filename=original_filename,
            file_size_bytes=file_size_bytes,
            total_rows=total_rows,
            created_count=0,
            updated_count=0,
            skipped_count=0,
            failed_count=0,
            conflict_strategy=conflict_strategy,
            error_report_available=False,
            committed_at=None,
            created_at=now,
            updated_at=now,
        )

    def mark_committed(
        self,
        *,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_report_available: bool = False,
        clock: Clock,
    ) -> None:
        now = clock.now()
        self.status = ImportStatus.COMMITTED
        self.created_count = created_count
        self.updated_count = updated_count
        self.skipped_count = skipped_count
        self.error_report_available = error_report_available
        self.committed_at = now
        self.updated_at = now

        self._events.append(
            import_batch_committed(
                batch_id=self.id,
                organization_id=self.organization_id,
                actor_user_id=self.actor_user_id,
                resource_type=self.resource_type,
                total_rows=self.total_rows,
                created_count=self.created_count,
                updated_count=self.updated_count,
                skipped_count=self.skipped_count,
                occurred_at=now,
            )
        )

    def mark_failed(self, *, clock: Clock) -> None:
        now = clock.now()
        self.status = ImportStatus.FAILED
        self.updated_at = now

    def pull_domain_events(self) -> list[DomainEvent]:
        events = list(self._events)
        self._events.clear()
        return events
