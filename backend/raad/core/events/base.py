"""Domain event envelope (Backend LLD §10.3; outbox row shape per Database Design §8.8).

Every domain event, regardless of which module emits it, is carried in this shape once it
reaches the outbox/broker. Modules define their own event *payload* shapes under
`modules/<context>/domain/events.py`; this is the transport-level envelope around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_type: str
    version: int
    occurred_at: datetime
    org_id: str | None
    correlation_id: str | None
    payload: dict[str, Any]
    aggregate_type: str
    aggregate_id: str
