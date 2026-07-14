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
