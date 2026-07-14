"""Domain events for the `tracking` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`) — the existing abstraction, not a parallel one —
populated with `tracking`-specific `event_type`/`aggregate_type`/`payload`. Identical shape to
`fleet_device.domain.events`/`organization.domain.events`.

Factories take primitive values only, never the aggregate objects themselves — events must be
serializable (they land in `outbox.payload_json`, Database Design §8.8) and this also avoids a
circular import with `entities.py` (which calls these factories).

Only four event types are defined here — exactly Phase 2 §22.2's geofence-evaluation diagram
and API Contracts §13.2's event catalogue (`geofence.approaching_stop`, `geofence.arrived_org`
are the two catalogue rows; `entered_stop`/`exited` are named by §22.2's diagram and the
Database Design §7.2 `event_type` enum, which agrees on all four). Payloads are scoped to
exactly what §13.2's catalogue documents for the two rows it lists (`trip_id, stop_id` /
`trip_id`) and extended identically to the other two crossing types for consistency, since no
approved document gives them a distinct payload shape.

**`device.position_reported`/`DevicePositionReported` is deliberately not defined here** — it
is emitted by the JT808 device plane (Phase 2 §6.1, §5.1; `.claude/rules/jt808.md` #1), not by
this module; `tracking` only *consumes* it (a later application-layer phase). Persisting the
resulting `VehiclePosition` row is storage of an already-announced fact, not a new one — see
`entities.py`'s `VehiclePosition` docstring for why no event is recorded on `record()`.
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


# --- Geofence crossings (Phase 2 §22.2; API Contracts §13.2; Database Design §7.2) --------


def vehicle_approaching_stop(
    *,
    crossing_id: str,
    organization_id: str,
    trip_id: str,
    stop_id: str,
    occurred_at: datetime,
) -> DomainEvent:
    """API Contracts §13.2 `geofence.approaching_stop` — payload verbatim: `trip_id, stop_id`."""
    return _new_event(
        event_type="VehicleApproachingStop",
        aggregate_type="GeofenceCrossing",
        aggregate_id=crossing_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"trip_id": trip_id, "stop_id": stop_id},
    )


def vehicle_entered_stop_geofence(
    *,
    crossing_id: str,
    organization_id: str,
    trip_id: str,
    stop_id: str,
    occurred_at: datetime,
) -> DomainEvent:
    """Phase 2 §22.2's evaluation diagram names this event; not a separate row in API
    Contracts §13.2's catalogue table, so its payload mirrors `approaching_stop`'s documented
    shape (`trip_id, stop_id`) rather than inventing a distinct one."""
    return _new_event(
        event_type="VehicleEnteredStopGeofence",
        aggregate_type="GeofenceCrossing",
        aggregate_id=crossing_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"trip_id": trip_id, "stop_id": stop_id},
    )


def vehicle_arrived_at_organization(
    *,
    crossing_id: str,
    organization_id: str,
    trip_id: str,
    occurred_at: datetime,
) -> DomainEvent:
    """API Contracts §13.2 `geofence.arrived_org` — payload verbatim: `trip_id` (no stop —
    this is the organization/campus geofence, Phase 2 §22.1)."""
    return _new_event(
        event_type="VehicleArrivedAtOrganization",
        aggregate_type="GeofenceCrossing",
        aggregate_id=crossing_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"trip_id": trip_id},
    )


def vehicle_exited_geofence(
    *,
    crossing_id: str,
    organization_id: str,
    trip_id: str,
    stop_id: str | None,
    occurred_at: datetime,
) -> DomainEvent:
    """Phase 2 §22.2 names `VehicleExitedGeofence` generically — it can be exiting a stop's
    geofence or the organization's, matching `geofence_events.stop_id`'s nullability
    (Database Design §7.2: null for the org geofence)."""
    return _new_event(
        event_type="VehicleExitedGeofence",
        aggregate_type="GeofenceCrossing",
        aggregate_id=crossing_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"trip_id": trip_id, "stop_id": stop_id},
    )
