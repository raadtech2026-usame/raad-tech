"""HTTP response DTOs for `tracking` (Backend LLD §16; API Contracts §4.4). Pydantic models
are transport-only — the boundary at which JSON comes from the application layer's plain-
dataclass DTOs. No business logic lives here; routers do that translation (`routers.py`),
never the schemas themselves. Mirrors `fleet_device`/`organization`/`iam.api.schemas`'s shape
exactly.

No request-body schema is defined — both approved REST endpoints (API Contracts §4.4) are
`GET`s taking only a path parameter, unlike `fleet_device`'s `POST`/`PATCH` routes.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VehiclePositionResponse(BaseModel):
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


class OnlineVehiclePositionResponse(BaseModel):
    """ADR-0031 (Fleet Overview read model). `None` on the parent row today, universally — see
    `OnlineVehicleResponse`'s own docstring."""

    latitude: float
    longitude: float
    heading_deg: int | None
    speed_kph: int | None
    event_time: datetime


class OnlineVehicleResponse(BaseModel):
    """ADR-0031 — one row of `GET /tracking/vehicles/online`. `position` is a disclosed,
    confirmed gap, not a bug: the live JT808 adapter doesn't yet wire a `LatestPositionWriter`
    (`services/device-gateway/src/gateway.py`), so `LatestPositionPort` has no cached key for
    any vehicle in this environment today — this field is `null` for that reason, populating
    automatically once that gap is separately closed, with zero change needed here."""

    vehicle_id: str
    plate_no: str
    label: str | None
    device_id: str
    is_online: bool
    position: OnlineVehiclePositionResponse | None


class FleetOnlineVehiclesResponse(BaseModel):
    """`total_online` is the *pre-cap* count (`FLEET_OVERVIEW_MAX_ONLINE_VEHICLES`,
    `application/services.py`) — lets a caller with more online vehicles than the cap show an
    honest "showing X of Y online" indicator instead of silently truncating with no signal."""

    vehicles: list[OnlineVehicleResponse]
    total_online: int
