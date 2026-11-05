"""Domain events for data_transfer bounded context.

Represents completed or failed bulk import batches for audit trail and notification subscribers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent


def import_batch_committed(
    *,
    batch_id: str,
    organization_id: str,
    actor_user_id: str,
    resource_type: str,
    total_rows: int,
    created_count: int,
    updated_count: int,
    skipped_count: int,
    occurred_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        event_id=str(uuid.uuid4()),
        event_type="data_transfer.import_batch_committed",
        version=1,
        occurred_at=occurred_at,
        org_id=organization_id,
        correlation_id=None,
        aggregate_type="ImportBatch",
        aggregate_id=batch_id,
        payload={
            "batch_id": batch_id,
            "organization_id": organization_id,
            "actor_user_id": actor_user_id,
            "resource_type": resource_type,
            "total_rows": total_rows,
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
        },
    )
