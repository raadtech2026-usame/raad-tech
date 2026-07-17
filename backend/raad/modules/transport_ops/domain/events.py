"""Domain events for the `transport_ops` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`) — the existing abstraction, not a parallel one —
populated with `transport_ops`-specific `event_type`/`aggregate_type`/`payload`.

Factories take primitive values (ids/enums as `str`), never the aggregate objects themselves —
events must be serializable (they land in `outbox.payload_json`, Database Design §8.8) and this
also avoids a circular import with `entities.py` (which calls these factories).

**Naming note:** no approved document names a creation/status-change event for the `Student`
aggregate itself — Backend LLD §5.2 gives no `Student` use-case skeleton, and the only
`Student*`-prefixed event names anywhere in the approved documentation
(`StudentAssignmentRemoved`/`StudentTransferred`/`StudentGraduated`/`StudentDisabled`, Backend
LLD §10.3) belong to `student_assignments` — a distinct, out-of-scope-this-phase aggregate (see
`entities.py`'s module docstring). `StudentEnrolled`/`StudentActivated`/`StudentDisabled`/
`StudentGraduated`/`StudentTransferred` below are this phase's own choice, following the
established PascalCase-past-tense convention and the Ch. 6 ubiquitous language ("Student") —
not a verbatim-documented name. Flagged, not silently assumed to be pre-approved.

**Phase 10.2 addition:** `student_details_updated`, backing `Student.update_details`
(`entities.py`'s module docstring addendum) — same naming-note caveat applies.

**Phase 10.6 addition:** `parent_registered`/`parent_details_updated`/`parent_activated`/
`parent_disabled`, backing the new `Parent` aggregate (`entities.py`). Same naming-note caveat:
no approved document names a `Parent` event either — these follow the identical
PascalCase-past-tense convention and the Ch. 6 ubiquitous language ("Parent"), 1:1 with
`Parent`'s own domain method names, exactly mirroring `Student`'s event set shape (minus
`graduated`/`transferred`, which have no `Parent`-domain equivalent — `ParentStatus` is a flat
active/inactive toggle, see `value_objects.py`).
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


def student_enrolled(
    *,
    student_id: str,
    organization_id: str,
    full_name: str,
    external_ref: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentEnrolled",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "full_name": full_name,
            "external_ref": external_ref,
            "actor_id": actor_id,
        },
    )


def student_details_updated(
    *,
    student_id: str,
    organization_id: str,
    full_name: str,
    external_ref: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentDetailsUpdated",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "full_name": full_name,
            "external_ref": external_ref,
            "actor_id": actor_id,
        },
    )


def student_activated(
    *,
    student_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentActivated",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_disabled(
    *,
    student_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentDisabled",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_graduated(
    *,
    student_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentGraduated",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_transferred(
    *,
    student_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentTransferred",
        aggregate_type="Student",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def parent_registered(
    *,
    parent_id: str,
    organization_id: str,
    user_id: str,
    full_name: str,
    phone: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentRegistered",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "user_id": user_id,
            "full_name": full_name,
            "phone": phone,
            "actor_id": actor_id,
        },
    )


def parent_details_updated(
    *,
    parent_id: str,
    organization_id: str,
    full_name: str,
    phone: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentDetailsUpdated",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"full_name": full_name, "phone": phone, "actor_id": actor_id},
    )


def parent_activated(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentActivated",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def parent_disabled(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentDisabled",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
