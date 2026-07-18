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

**Phase 10.7 addition:** `student_parent_linked`/`student_parent_unlinked`, backing the new
`StudentParent` aggregate (`entities.py`, Database Design §6.4). `aggregate_id` is `student_id`
alone, **not** a composite `student_id:parent_id` string — a composite string was tried first
and rejected after live-database verification: `core.events.outbox.OutboxModel.aggregate_id` is
a shared `CHAR(26)` column (`core/events/outbox.py`), sized for exactly one ULID and used
identically by every other module's events, so a 53-character composite value fails at
`INSERT` (`StringDataRightTruncationError`) — this is a hard, foundation-layer constraint, not
one this module can widen unilaterally. `student_id` is chosen over `parent_id` as the single
id to carry (both are still fully available in `payload`, so no information is lost) because
the REST surface nests this relationship under `/students/{id}/parents` first
(`api/routers.py`). `org_id` is threaded through explicitly by the caller (`entities.py`'s
`StudentParent.link`/`unlink`) even though `student_parents` has no `organization_id` column of
its own, so that outbox/event consumers still get tenant-scoping information consistent with
every other event in this module.

**Phase 10.8 addition:** `driver_registered`/`driver_details_updated`/`driver_activated`/
`driver_disabled`, backing the new `Driver` aggregate (`entities.py`, Database Design §6.1).
Same naming-note caveat as `Parent`'s own event set above: no approved document names a
`Driver` event either — these follow the identical PascalCase-past-tense convention and the
Ch. 6 ubiquitous language ("Driver"), 1:1 with `Driver`'s own domain method names, exactly
mirroring `Parent`'s event set shape (`registered`/`details_updated`/`activated`/`disabled` —
no `graduated`/`transferred` equivalent, since `DriverStatus` is likewise a flat active/inactive
toggle, `value_objects.py`).

**Phase 11 addition:** `route_created`/`route_details_updated`/`route_activated`/
`route_disabled`/`route_stop_added`/`route_stop_removed`/`route_stop_reordered`, backing the
new `Route`/`Stop` aggregate (`entities.py`, Database Design §6.5/§6.6). Same naming-note
caveat: no approved document names any of these events. The three `route_stop_*` events all
carry `aggregate_type="Route"`/`aggregate_id=route_id` (never `"Stop"`/`stop_id`) — `Stop` has
no aggregate identity of its own to record against (it is a child entity, `entities.py`'s Phase
11 addition), exactly mirroring `fleet_device.domain.events.camera_registered`'s identical
`aggregate_type="Device"` choice for an intra-aggregate child fact.
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


def student_parent_linked(
    *,
    student_id: str,
    parent_id: str,
    organization_id: str,
    relationship: str | None,
    is_primary: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentParentLinked",
        aggregate_type="StudentParent",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "student_id": student_id,
            "parent_id": parent_id,
            "relationship": relationship,
            "is_primary": is_primary,
            "actor_id": actor_id,
        },
    )


def student_parent_unlinked(
    *,
    student_id: str,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentParentUnlinked",
        aggregate_type="StudentParent",
        aggregate_id=student_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "student_id": student_id,
            "parent_id": parent_id,
            "actor_id": actor_id,
        },
    )


def driver_registered(
    *,
    driver_id: str,
    organization_id: str,
    user_id: str,
    license_no: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DriverRegistered",
        aggregate_type="Driver",
        aggregate_id=driver_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "user_id": user_id,
            "license_no": license_no,
            "actor_id": actor_id,
        },
    )


def driver_details_updated(
    *,
    driver_id: str,
    organization_id: str,
    license_no: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DriverDetailsUpdated",
        aggregate_type="Driver",
        aggregate_id=driver_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"license_no": license_no, "actor_id": actor_id},
    )


def driver_activated(
    *,
    driver_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DriverActivated",
        aggregate_type="Driver",
        aggregate_id=driver_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def driver_disabled(
    *,
    driver_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DriverDisabled",
        aggregate_type="Driver",
        aggregate_id=driver_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def route_created(
    *,
    route_id: str,
    organization_id: str,
    name: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteCreated",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"name": name, "actor_id": actor_id},
    )


def route_details_updated(
    *,
    route_id: str,
    organization_id: str,
    name: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteDetailsUpdated",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"name": name, "actor_id": actor_id},
    )


def route_activated(
    *,
    route_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteActivated",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def route_disabled(
    *,
    route_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteDisabled",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def route_stop_added(
    *,
    route_id: str,
    organization_id: str,
    stop_id: str,
    name: str,
    latitude: float,
    longitude: float,
    sequence_no: int,
    geofence_radius_m: int | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteStopAdded",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "stop_id": stop_id,
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "sequence_no": sequence_no,
            "geofence_radius_m": geofence_radius_m,
            "actor_id": actor_id,
        },
    )


def route_stop_removed(
    *,
    route_id: str,
    organization_id: str,
    stop_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteStopRemoved",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"stop_id": stop_id, "actor_id": actor_id},
    )


def route_stop_reordered(
    *,
    route_id: str,
    organization_id: str,
    stop_id: str,
    new_sequence_no: int,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteStopReordered",
        aggregate_type="Route",
        aggregate_id=route_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "stop_id": stop_id,
            "new_sequence_no": new_sequence_no,
            "actor_id": actor_id,
        },
    )
