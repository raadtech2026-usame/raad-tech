"""ORM ↔ Domain mappers for `tracking` (Backend LLD §7.1 "aggregate-in/aggregate-out"; §17
`db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions, and never return an ORM model to a caller. Mirrors
`fleet_device`/`organization`/`iam.infra.mappers`'s `existing=` in-place-update pattern
exactly.

Both `VehiclePosition` and `GeofenceCrossing` are immutable after creation (Phase 8.1: neither
entity has a mutation method), so in practice `*_to_model`'s `existing=` branch is never hit by
current use-cases — `add()` is the only write path either aggregate takes. The parameter is
kept anyway, for the same reason `repositories.py` still implements `flush_tracked_changes()`
for both: uniform shape across every module's infra layer, and a no-op today is cheap insurance
against a future phase adding a legitimate mutation (there is precedent for exactly this — nothing about vehicle_positions/geofence_events forecloses it) without a silent gap.
"""

from __future__ import annotations

from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)
from raad.modules.tracking.infra.models import (
    GeofenceCrossingModel,
    VehiclePositionModel,
)

# --- VehiclePosition ------------------------------------------------------------------------


def vehicle_position_to_model(
    position: VehiclePosition, *, existing: VehiclePositionModel | None = None
) -> VehiclePositionModel:
    """Projects a `VehiclePosition` entity onto its ORM row. If `existing` is given, mutates
    and returns that same instance (so the SQLAlchemy session keeps tracking the one row it
    already knows about) — otherwise constructs a new `VehiclePositionModel`. `event_time` is
    part of the composite primary key (module docstring, `models.py`) — set once, on
    construction, never reassigned on `existing` (an already-persisted row's partition key
    never changes)."""
    if existing is not None:
        model = existing
    else:
        model = VehiclePositionModel(
            id=str(position.id), event_time=position.event_time
        )
    model.organization_id = str(position.organization_id)
    model.vehicle_id = str(position.vehicle_id)
    model.device_id = str(position.device_id)
    model.trip_id = str(position.trip_id) if position.trip_id is not None else None
    model.latitude = position.position.latitude
    model.longitude = position.position.longitude
    model.speed_kph = (
        position.speed_kph.value if position.speed_kph is not None else None
    )
    model.heading_deg = (
        position.heading_deg.value if position.heading_deg is not None else None
    )
    model.alarm_flags = (
        position.alarm_flags.value if position.alarm_flags is not None else None
    )
    model.is_backfill = position.is_backfill
    model.received_at = position.received_at
    return model


def model_to_vehicle_position(model: VehiclePositionModel) -> VehiclePosition:
    return VehiclePosition(
        id=VehiclePositionId(model.id),
        organization_id=OrganizationId(model.organization_id),
        vehicle_id=VehicleId(model.vehicle_id),
        device_id=DeviceId(model.device_id),
        trip_id=TripId(model.trip_id) if model.trip_id is not None else None,
        position=GeoPoint(latitude=model.latitude, longitude=model.longitude),
        speed_kph=SpeedKph(model.speed_kph) if model.speed_kph is not None else None,
        heading_deg=(
            HeadingDegrees(model.heading_deg) if model.heading_deg is not None else None
        ),
        alarm_flags=(
            AlarmFlags(model.alarm_flags) if model.alarm_flags is not None else None
        ),
        event_time=model.event_time,
        received_at=model.received_at,
        is_backfill=model.is_backfill,
    )


# --- GeofenceCrossing -----------------------------------------------------------------------


def geofence_crossing_to_model(
    crossing: GeofenceCrossing, *, existing: GeofenceCrossingModel | None = None
) -> GeofenceCrossingModel:
    model = (
        existing if existing is not None else GeofenceCrossingModel(id=str(crossing.id))
    )
    model.organization_id = str(crossing.organization_id)
    model.trip_id = str(crossing.trip_id)
    model.stop_id = str(crossing.stop_id) if crossing.stop_id is not None else None
    model.event_type = crossing.event_type.value
    model.occurred_at = crossing.occurred_at
    return model


def model_to_geofence_crossing(model: GeofenceCrossingModel) -> GeofenceCrossing:
    return GeofenceCrossing(
        id=GeofenceCrossingId(model.id),
        organization_id=OrganizationId(model.organization_id),
        trip_id=TripId(model.trip_id),
        stop_id=StopId(model.stop_id) if model.stop_id is not None else None,
        event_type=GeofenceEventType(model.event_type),
        occurred_at=model.occurred_at,
    )
