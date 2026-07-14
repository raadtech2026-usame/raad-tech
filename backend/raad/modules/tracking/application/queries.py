"""Tracking application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). DTOs
are plain dataclasses — the boundary between the domain's entities and any future API/infra
layer, so neither ever depends on the other's internal shape. Mirrors
`fleet_device.application.queries`'s shape exactly.

`GetCurrentVehiclePositionQuery` backs API Contracts §4.4's `GET /tracking/vehicles/{id}/
latest` (served via `LatestPositionPort`, not `VehiclePositionRepository` — see
`ports.py`). `GetVehiclePositionHistoryQuery` backs `GET /tracking/trips/{id}/positions`,
trip-scoped exactly as documented (no vehicle-scoped history query is defined here, even
though `VehiclePositionRepository.list_for_vehicle` exists, since no approved endpoint reads
it that way — `.claude/rules/workflow.md` #8: build only approved use-cases).

`GetGeofenceCrossingsQuery` has no dedicated REST endpoint in API Contracts today — flagged,
not silently assumed. It is included because it is an explicitly requested use case over a
table this module unambiguously owns and retains long-term (Database Design §7.2/§11.1), the
natural CQRS-read companion to `RecordGeofenceCrossing`'s write path; it is forward-looking
infrastructure for whichever future API/reporting phase exposes it, the same way a domain
repository method can exist before every caller does.

No query here carries an `actor: Principal`, matching `fleet_device.application.queries`'
`GetVehicleByIdQuery`/`GetDeviceByIdQuery` precedent exactly (authorization is a route
dependency's concern, not baked into the query DTO) — see `services.py`'s module docstring for
why `TrackingVisibilityPolicy` (Phase 8.1) is not invoked from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition


@dataclass(frozen=True)
class GetCurrentVehiclePositionQuery:
    vehicle_id: str


@dataclass(frozen=True)
class GetVehiclePositionHistoryQuery:
    trip_id: str


@dataclass(frozen=True)
class GetGeofenceCrossingsQuery:
    trip_id: str


@dataclass(frozen=True)
class VehiclePositionDTO:
    id: str
    organization_id: str
    vehicle_id: str
    device_id: str
    trip_id: str | None
    latitude: float
    longitude: float
    speed_kph: int | None
    heading_deg: int | None
    alarm_flags: int | None
    event_time: datetime
    received_at: datetime
    is_backfill: bool


@dataclass(frozen=True)
class GeofenceCrossingDTO:
    id: str
    organization_id: str
    trip_id: str
    stop_id: str | None
    event_type: str
    occurred_at: datetime


@dataclass(frozen=True)
class GeofenceEvaluationResultDTO:
    """The result of a pure `EvaluateGeofenceCommand` — no identity, since nothing is
    persisted (`services.py`'s `evaluate_geofence` performs no I/O)."""

    is_inside: bool
    distance_m: float
    transition: str


def vehicle_position_to_dto(position: VehiclePosition) -> VehiclePositionDTO:
    """Shared mapper — the only place a `VehiclePosition` entity is projected into its DTO."""
    return VehiclePositionDTO(
        id=str(position.id),
        organization_id=str(position.organization_id),
        vehicle_id=str(position.vehicle_id),
        device_id=str(position.device_id),
        trip_id=str(position.trip_id) if position.trip_id is not None else None,
        latitude=position.position.latitude,
        longitude=position.position.longitude,
        speed_kph=position.speed_kph.value if position.speed_kph is not None else None,
        heading_deg=(
            position.heading_deg.value if position.heading_deg is not None else None
        ),
        alarm_flags=(
            position.alarm_flags.value if position.alarm_flags is not None else None
        ),
        event_time=position.event_time,
        received_at=position.received_at,
        is_backfill=position.is_backfill,
    )


def geofence_crossing_to_dto(crossing: GeofenceCrossing) -> GeofenceCrossingDTO:
    """Shared mapper — the only place a `GeofenceCrossing` entity is projected into its DTO."""
    return GeofenceCrossingDTO(
        id=str(crossing.id),
        organization_id=str(crossing.organization_id),
        trip_id=str(crossing.trip_id),
        stop_id=str(crossing.stop_id) if crossing.stop_id is not None else None,
        event_type=crossing.event_type.value,
        occurred_at=crossing.occurred_at,
    )
