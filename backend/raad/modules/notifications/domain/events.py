"""Domain events for the `notifications` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`), populated with `notifications`-specific
`event_type`/`aggregate_type`/`payload`, mirroring every other module's identical `_new_event`
pattern.

**No approved document names any event this module itself produces.** Database Design §7.5/§7.6
document the `notifications`/`device_tokens` *tables*; Backend LLD §11.2/§11.3 document the
Notification *Worker's* behavior (a consumer of upstream events, not a producer of its own);
API Contracts §13.2's event catalogue lists `notifications` only as a **consumer** ("Primary
consumers" column), never a producer. All four events below are this phase's own flagged
choice — PascalCase past-tense, named 1:1 with each aggregate's own domain method, the same
"flagged, not silently assumed" posture every prior phase's own unnamed events already carry
(e.g. `TripResumed`, `PlanCreated`).

**Event-contract conflict, documented per the task's explicit instruction, not resolved by
invention:** API Contracts §13.2 documents `student.assignment_changed` (payload `student_id,
assignment_id, new_status`) as the single CR-1-revocation wire event this module should
consume. The actual, already-implemented Backend LLD event contract in `transport_ops` is four
separate events — `StudentAssignmentRemoved`/`StudentTransferred`/`StudentGraduated`/
`StudentDisabled` (`transport_ops.domain.events`) — each carrying only `{actor_id}`, no
`new_status` field, and no unified event name. Per this phase's explicit instruction ("preserve
the implemented Backend LLD event contracts... do NOT invent compatibility behavior"), no
translation/normalization layer is added here or anywhere else. This module does not consume
events this phase at all (event consumption/broker wiring is out of scope), so the conflict is
recorded but does not block anything built here — it will need resolving before the Notification
Worker itself can be built.
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


def notification_created(
    *,
    notification_id: str,
    organization_id: str,
    recipient_user_id: str,
    type: str,
    trip_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="NotificationCreated",
        aggregate_type="Notification",
        aggregate_id=notification_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "recipient_user_id": recipient_user_id,
            "type": type,
            "trip_id": trip_id,
            "actor_id": actor_id,
        },
    )


def notification_read(
    *,
    notification_id: str,
    organization_id: str,
    recipient_user_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="NotificationRead",
        aggregate_type="Notification",
        aggregate_id=notification_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"recipient_user_id": recipient_user_id, "actor_id": actor_id},
    )


def device_token_registered(
    *,
    device_token_id: str,
    user_id: str,
    platform: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DeviceTokenRegistered",
        aggregate_type="DeviceToken",
        aggregate_id=device_token_id,
        org_id=None,  # device_tokens has no organization_id column (§7.6) - user-owned, not
        # tenant-owned, the same reasoning Plan's org_id=None already establishes for billing.
        occurred_at=occurred_at,
        payload={"user_id": user_id, "platform": platform, "actor_id": actor_id},
    )


def device_token_revoked(
    *,
    device_token_id: str,
    user_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DeviceTokenRevoked",
        aggregate_type="DeviceToken",
        aggregate_id=device_token_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"user_id": user_id, "actor_id": actor_id},
    )
