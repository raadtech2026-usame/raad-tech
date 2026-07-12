"""Domain events for the `organization` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`) — the existing abstraction, not a parallel one —
populated with `organization`-specific `event_type`/`aggregate_type`/`payload`.

Factories take primitive values (ids/enums as `str`), never the aggregate objects themselves —
events must be serializable (they land in `outbox.payload_json`, Database Design §8.8) and this
also avoids a circular import with `entities.py` (which calls these factories).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    org_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


def organization_registered(
    *,
    organization_id: str,
    name: str,
    org_type: str,
    parent_org_id: str | None,
    region_id: str,
    billing_model: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="OrganizationRegistered",
        aggregate_type="Organization",
        aggregate_id=organization_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "name": name,
            "org_type": org_type,
            "parent_org_id": parent_org_id,
            "region_id": region_id,
            "billing_model": billing_model,
            "actor_id": actor_id,
        },
    )


def organization_suspended(
    *, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="OrganizationSuspended",
        aggregate_type="Organization",
        aggregate_id=organization_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def organization_reactivated(
    *, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="OrganizationReactivated",
        aggregate_type="Organization",
        aggregate_id=organization_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def organization_deactivated(
    *, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="OrganizationDeactivated",
        aggregate_type="Organization",
        aggregate_id=organization_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def region_created(
    *,
    region_id: str,
    name: str,
    geographic_scope: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RegionCreated",
        aggregate_type="Region",
        aggregate_id=region_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={
            "name": name,
            "geographic_scope": geographic_scope,
            "actor_id": actor_id,
        },
    )


def region_activated(
    *, region_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="RegionActivated",
        aggregate_type="Region",
        aggregate_id=region_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def region_deactivated(
    *, region_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="RegionDeactivated",
        aggregate_type="Region",
        aggregate_id=region_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
