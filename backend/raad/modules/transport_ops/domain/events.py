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

**Phase 12 addition:** `trip_scheduled`/`trip_started`/`trip_ended`/`trip_interrupted`/
`trip_resumed`/`trip_driver_changed`, backing the new `Trip` aggregate (`entities.py`, Database
Design §6.8, Phase-2 §6.2). Unlike every prior addition's naming-note caveat, `TripStarted` and
`TripEnded` **are** approved, documented names — Backend LLD §5.2's aggregate skeleton
(`start(actor, clock) -> [TripStarted]`, `end(actor, clock) -> [TripEnded]`) and Phase-2 §6.1's
event catalog both name them verbatim. `TripInterrupted` is likewise LLD-documented verbatim
(`interrupt(reason) -> [TripInterrupted]`). `TripScheduled`/`TripResumed`/`TripDriverChanged`
have no approved document naming them — the same "flagged, not silently assumed" caveat every
prior phase's own unnamed events already carry — chosen to match this class's own domain method
names 1:1 (`Trip.schedule`/`resume`/`change_driver`) and the established PascalCase-past-tense
convention exactly.

**Phase 13 addition:** `student_assignment_created`/`student_assignment_removed`/
`student_assignment_transferred`/`student_assignment_graduated`/`student_assignment_disabled`,
backing the new `StudentAssignment` aggregate (`entities.py`, Database Design §6.7). Four of the
five event *types* are LLD-documented verbatim (§5.4): `StudentAssignmentRemoved`,
`StudentTransferred`, `StudentGraduated`, `StudentDisabled`. `student_assignment_created`'s
`"StudentAssignmentCreated"` has no approved document naming it — same "flagged, not silently
assumed" caveat as every prior creation event in this file.

**Event-name collision, called out explicitly — see this file's own opening "naming note"
above.** That note, written in Phase 10.1, already flagged that `StudentAssignmentRemoved`/
`StudentTransferred`/`StudentGraduated`/`StudentDisabled` are "a distinct, out-of-scope-this-
phase aggregate['s]" event names — yet `student_graduated`/`student_transferred`/
`student_disabled` (above, Phase 10.1) went ahead and used the exact same three `event_type`
strings (`"StudentGraduated"`/`"StudentTransferred"`/`"StudentDisabled"`) for the **`Student`**
aggregate's own status-change events, `aggregate_type="Student"`. This phase's
`student_assignment_transferred`/`_graduated`/`_disabled` (below) now use those identical three
strings again, `aggregate_type="StudentAssignment"`. The two families of events are
distinguishable only by `aggregate_type`, never by `event_type` alone — a real collision, not
introduced by this phase (it was already latent in Phase 10.1's own choice, made concrete now
that the LLD-documented aggregate the names actually belong to is finally being built), flagged
here and in `entities.py`'s module docstring rather than silently worked around by inventing an
undocumented rename on either side."""

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


def parent_video_live_access_granted(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0026 §2. Flows through the same `UnitOfWork.commit()` -> outbox + `audit_entries`
    pipeline (ADR-0007) every other event in this file already does - no separate audit
    mechanism needed for who granted video access to which parent, when."""
    return _new_event(
        event_type="ParentVideoLiveAccessGranted",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def parent_video_live_access_revoked(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentVideoLiveAccessRevoked",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def parent_video_playback_access_granted(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentVideoPlaybackAccessGranted",
        aggregate_type="Parent",
        aggregate_id=parent_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def parent_video_playback_access_revoked(
    *,
    parent_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ParentVideoPlaybackAccessRevoked",
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
    staff_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="DriverRegistered",
        aggregate_type="Driver",
        aggregate_id=driver_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "user_id": user_id,
            "staff_id": staff_id,
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


def trip_scheduled(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    driver_id: str,
    route_id: str,
    trip_type: str,
    scheduled_date: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripScheduled",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "route_id": route_id,
            "trip_type": trip_type,
            "scheduled_date": scheduled_date,
            "actor_id": actor_id,
        },
    )


def trip_started(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    driver_id: str,
    route_id: str,
    started_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripStarted",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=started_at,
        payload={
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "route_id": route_id,
            "started_at": started_at.isoformat(),
            "actor_id": actor_id,
        },
    )


def trip_ended(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    driver_id: str,
    route_id: str,
    ended_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripEnded",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=ended_at,
        payload={
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "route_id": route_id,
            "ended_at": ended_at.isoformat(),
            "actor_id": actor_id,
        },
    )


def trip_interrupted(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    reason: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripInterrupted",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"vehicle_id": vehicle_id, "reason": reason, "actor_id": actor_id},
    )


def trip_resumed(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripResumed",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"vehicle_id": vehicle_id, "actor_id": actor_id},
    )


def trip_driver_changed(
    *,
    trip_id: str,
    organization_id: str,
    driver_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TripDriverChanged",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"driver_id": driver_id, "actor_id": actor_id},
    )


def student_assignment_created(
    *,
    student_assignment_id: str,
    organization_id: str,
    student_id: str,
    route_id: str,
    pickup_stop_id: str,
    dropoff_stop_id: str,
    vehicle_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StudentAssignmentCreated",
        aggregate_type="StudentAssignment",
        aggregate_id=student_assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "student_id": student_id,
            "route_id": route_id,
            "pickup_stop_id": pickup_stop_id,
            "dropoff_stop_id": dropoff_stop_id,
            "vehicle_id": vehicle_id,
            "actor_id": actor_id,
        },
    )


def student_assignment_removed(
    *,
    student_assignment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`StudentAssignmentRemoved` (Backend LLD §5.4 verbatim) — CR-1 revocation event."""
    return _new_event(
        event_type="StudentAssignmentRemoved",
        aggregate_type="StudentAssignment",
        aggregate_id=student_assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_assignment_transferred(
    *,
    student_assignment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`StudentTransferred` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
    addition for the flagged collision with `student_transferred`'s identical `event_type`."""
    return _new_event(
        event_type="StudentTransferred",
        aggregate_type="StudentAssignment",
        aggregate_id=student_assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_assignment_graduated(
    *,
    student_assignment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`StudentGraduated` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
    addition for the flagged collision with `student_graduated`'s identical `event_type`."""
    return _new_event(
        event_type="StudentGraduated",
        aggregate_type="StudentAssignment",
        aggregate_id=student_assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def student_assignment_disabled(
    *,
    student_assignment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`StudentDisabled` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
    addition for the flagged collision with `student_disabled`'s identical `event_type`."""
    return _new_event(
        event_type="StudentDisabled",
        aggregate_type="StudentAssignment",
        aggregate_id=student_assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


# ---- ADR-0049/0050/0051: transport staff, bus crew, staff documents ----------------------------
#
# Payloads carry ids, statuses and dates only. Names, phone numbers, emergency contacts and
# document numbers are personal data: they are never written into an event, so they never reach
# the outbox or `audit_entries.metadata_json`. The audit row still says who changed what, when.


def transport_staff_registered(
    *,
    staff_id: str,
    organization_id: str,
    role_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportStaffRegistered",
        aggregate_type="TransportStaff",
        aggregate_id=staff_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"role_id": role_id, "actor_id": actor_id},
    )


def transport_staff_profile_updated(
    *,
    staff_id: str,
    organization_id: str,
    changed_fields: list[str],
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportStaffProfileUpdated",
        aggregate_type="TransportStaff",
        aggregate_id=staff_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"changed_fields": sorted(changed_fields), "actor_id": actor_id},
    )


def transport_staff_status_changed(
    *,
    staff_id: str,
    organization_id: str,
    status: str,
    previous_status: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportStaffStatusChanged",
        aggregate_type="TransportStaff",
        aggregate_id=staff_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"status": status, "previous_status": previous_status, "actor_id": actor_id},
    )


def transport_staff_role_saved(
    *,
    role_id: str,
    organization_id: str,
    is_archived: bool,
    created: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportStaffRoleCreated" if created else "TransportStaffRoleUpdated",
        aggregate_type="TransportStaffRole",
        aggregate_id=role_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"is_archived": is_archived, "actor_id": actor_id},
    )


def vehicle_staff_assigned(
    *,
    assignment_id: str,
    organization_id: str,
    staff_id: str,
    vehicle_id: str,
    route_id: str | None,
    role_id: str | None,
    kind: str,
    starts_on: str,
    ends_on: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleStaffAssigned",
        aggregate_type="VehicleStaffAssignment",
        aggregate_id=assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "staff_id": staff_id,
            "vehicle_id": vehicle_id,
            "route_id": route_id,
            "role_id": role_id,
            "kind": kind,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "actor_id": actor_id,
        },
    )


def vehicle_staff_assignment_ended(
    *,
    assignment_id: str,
    organization_id: str,
    staff_id: str,
    vehicle_id: str,
    ends_on: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleStaffAssignmentEnded",
        aggregate_type="VehicleStaffAssignment",
        aggregate_id=assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "staff_id": staff_id,
            "vehicle_id": vehicle_id,
            "ends_on": ends_on,
            "actor_id": actor_id,
        },
    )


def staff_document_type_saved(
    *,
    type_id: str,
    organization_id: str,
    alert_lead_days: list[int],
    is_archived: bool,
    created: bool,
    occurred_at: datetime,
    actor_id: str | None,
    required_for: str = "none",
    enforcement: str = "warn",
) -> DomainEvent:
    return _new_event(
        event_type="StaffDocumentTypeCreated" if created else "StaffDocumentTypeUpdated",
        aggregate_type="StaffDocumentType",
        aggregate_id=type_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "alert_lead_days": alert_lead_days,
            "is_archived": is_archived,
            "required_for": required_for,
            "enforcement": enforcement,
            "actor_id": actor_id,
        },
    )


def staff_document_recorded(
    *,
    document_id: str,
    organization_id: str,
    staff_id: str,
    type_id: str,
    expires_on: str | None,
    replaces_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StaffDocumentRecorded",
        aggregate_type="StaffDocument",
        aggregate_id=document_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "staff_id": staff_id,
            "type_id": type_id,
            "expires_on": expires_on,
            "replaces_id": replaces_id,
            "actor_id": actor_id,
        },
    )


def staff_document_updated(
    *,
    document_id: str,
    organization_id: str,
    changed_fields: list[str],
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StaffDocumentUpdated",
        aggregate_type="StaffDocument",
        aggregate_id=document_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"changed_fields": sorted(changed_fields), "actor_id": actor_id},
    )


def staff_document_expiry_alerted(
    *,
    document_id: str,
    organization_id: str,
    threshold_days: int,
    occurred_at: datetime,
) -> DomainEvent:
    return _new_event(
        event_type="StaffDocumentExpiryAlerted",
        aggregate_type="StaffDocument",
        aggregate_id=document_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"threshold_days": threshold_days, "actor_id": None},
    )


# ---- ADR-0052/0053/0054: daily transport operations ------------------------------------------
# Payloads carry ids, dates and categories only: never an unavailability note.


def trip_cancelled(
    *,
    trip_id: str,
    organization_id: str,
    vehicle_id: str,
    route_id: str,
    trip_type: str,
    scheduled_date: str,
    reason: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """The reason is the admin's own text and is shown to parents (ADR-0054 §2), so it is not
    personal data about staff."""
    return _new_event(
        event_type="TripCancelled",
        aggregate_type="Trip",
        aggregate_id=trip_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "vehicle_id": vehicle_id,
            "route_id": route_id,
            "trip_type": trip_type,
            "scheduled_date": scheduled_date,
            "reason": reason,
            "actor_id": actor_id,
        },
    )


def route_timetable_entry_saved(
    *,
    entry_id: str,
    organization_id: str,
    route_id: str,
    vehicle_id: str,
    trip_type: str,
    weekdays: list[int],
    is_active: bool,
    created: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="RouteTimetableEntryCreated" if created else "RouteTimetableEntryUpdated",
        aggregate_type="RouteTimetableEntry",
        aggregate_id=entry_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "route_id": route_id,
            "vehicle_id": vehicle_id,
            "trip_type": trip_type,
            "weekdays": weekdays,
            "is_active": is_active,
            "actor_id": actor_id,
        },
    )


def operating_closure_saved(
    *,
    closure_id: str,
    organization_id: str,
    starts_on: str,
    ends_on: str,
    withdrawn: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="OperatingClosureWithdrawn" if withdrawn else "OperatingClosureRecorded",
        aggregate_type="OperatingClosure",
        aggregate_id=closure_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"starts_on": starts_on, "ends_on": ends_on, "actor_id": actor_id},
    )


def staff_unavailability_saved(
    *,
    unavailability_id: str,
    organization_id: str,
    staff_id: str,
    starts_on: str,
    ends_on: str,
    reason: str,
    withdrawn: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StaffUnavailabilityWithdrawn" if withdrawn else "StaffUnavailabilityRecorded",
        aggregate_type="StaffUnavailability",
        aggregate_id=unavailability_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "staff_id": staff_id,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "reason": reason,
            "actor_id": actor_id,
        },
    )


def staff_cover_saved(
    *,
    cover_id: str,
    organization_id: str,
    unavailability_id: str,
    substitute_staff_id: str,
    vehicle_id: str,
    starts_on: str,
    ends_on: str,
    withdrawn: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="StaffCoverWithdrawn" if withdrawn else "StaffCoverCreated",
        aggregate_type="StaffCover",
        aggregate_id=cover_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "unavailability_id": unavailability_id,
            "substitute_staff_id": substitute_staff_id,
            "vehicle_id": vehicle_id,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "actor_id": actor_id,
        },
    )


# ---- ADR-0056: incident log ------------------------------------------------------------------
# Ids, category, severity and status only: never the text or the people.


def incident_recorded(
    *,
    incident_id: str,
    organization_id: str,
    category: str,
    severity: str,
    vehicle_id: str | None,
    trip_id: str | None,
    source_alert_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="IncidentRecorded",
        aggregate_type="Incident",
        aggregate_id=incident_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "category": category,
            "severity": severity,
            "vehicle_id": vehicle_id,
            "trip_id": trip_id,
            "source_alert_id": source_alert_id,
            "actor_id": actor_id,
        },
    )


def incident_updated(
    *,
    incident_id: str,
    organization_id: str,
    changed_fields: list[str],
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="IncidentUpdated",
        aggregate_type="Incident",
        aggregate_id=incident_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"changed_fields": changed_fields, "actor_id": actor_id},
    )


def incident_status_changed(
    *,
    incident_id: str,
    organization_id: str,
    status: str,
    previous_status: str,
    recorded_in_error: bool,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="IncidentStatusChanged",
        aggregate_type="Incident",
        aggregate_id=incident_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "status": status,
            "previous_status": previous_status,
            "recorded_in_error": recorded_in_error,
            "actor_id": actor_id,
        },
    )


def incident_note_added(
    *,
    note_id: str,
    organization_id: str,
    incident_id: str,
    kind: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`IncidentParentNoticeSent` for a parent notice (the Notification Worker sends it, reading
    the message through `transport_ops`, never from this payload); `IncidentNoteAdded` otherwise."""
    return _new_event(
        event_type="IncidentParentNoticeSent" if kind == "parent_notice" else "IncidentNoteAdded",
        aggregate_type="IncidentNote",
        aggregate_id=note_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"incident_id": incident_id, "kind": kind, "actor_id": actor_id},
    )
