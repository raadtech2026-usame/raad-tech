"""HTTP surface of the `tracking` module (C5) — Phase 8.4. `tracking_router` mounts at
`/api/v1/tracking` (`interfaces/http/api_v1.py`); the realtime `/ws/tracking` WebSocket
endpoint (API Contracts §11.2) has its own session/subscription lifecycle entirely unlike a
REST route and is out of this phase's scope — `api/ws.py` is not touched here.

Thin controllers only (Backend LLD §16.2): parse the request, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access. Mirrors `fleet_device`/`organization`/`iam.api.routers`'s shape exactly,
including the `require_permission`-pending-RBAC-matrix posture: every route below is
authorization-gated the same way, so it currently raises `NotImplementedError` (500) rather
than a guessed permission matrix, per API Contracts §4.4's role column.

Two routes, exactly API Contracts §4.4's two REST rows:
- `GET /tracking/vehicles/{vehicle_id}/latest`
- `GET /tracking/trips/{trip_id}/positions`

**`GET /tracking/vehicles/{vehicle_id}/latest` has a second, independent pending-capability
gap beyond RBAC.** `TrackingApplicationService` requires a `LatestPositionPort`
(`application/ports.py`, Phase 8.2) whose only approved backing store is Redis (Database
Design §7.1: "Latest position is NOT read from" the MySQL history table) — no concrete
implementation exists yet, deliberately deferred by Phase 8.3's infra layer. `core/di/
bootstrap.py` follows the same "fail loudly, don't fake it" policy already established for
`OutboxPublisher`/`BrokerPort` and leaves `TrackingApplicationService` unbound until
`LatestPositionPort` has a real implementation — so `get_tracking_service` (`api/deps.py`)
raises `LookupError` (500) for *both* routes today, and this route specifically will keep
raising it even after RBAC lands, until the Redis-backed port is implemented.

**No pagination on `GET /tracking/trips/{trip_id}/positions`**, despite API Contracts §4.4
noting the endpoint is "paginated" — `GetVehiclePositionHistoryQuery`/`list_for_trip`
deliberately take no page parameters yet (Phase 8.2's own documented deferral, the same
"domain repos return entities, not pages" stance `fleet_device`'s interfaces take). Adding
pagination here would mean inventing application-layer behavior ahead of that approved
design, so this route returns the full history list as-is.

**No `GET` for geofence crossings is exposed** — API Contracts documents no REST endpoint for
geofence-crossing history; `GetGeofenceCrossingsQuery`/`get_geofence_crossings`
(Phase 8.2) stay reachable for whichever future contract revision documents one, the same
"routes are contract-driven, not capability-driven" stance `fleet_device`'s undocumented
camera-registration route takes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import NotFoundError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.tracking.api.deps import get_tracking_service, get_tracking_uow
from raad.modules.tracking.api.schemas import VehiclePositionResponse
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.queries import (
    GetCurrentVehiclePositionQuery,
    GetVehiclePositionHistoryQuery,
    VehiclePositionDTO,
)
from raad.modules.tracking.application.services import TrackingApplicationService

tracking_router = APIRouter()


def _position_dto_to_response(position: VehiclePositionDTO) -> VehiclePositionResponse:
    return VehiclePositionResponse(
        id=position.id,
        organization_id=position.organization_id,
        vehicle_id=position.vehicle_id,
        device_id=position.device_id,
        trip_id=position.trip_id,
        latitude=position.latitude,
        longitude=position.longitude,
        speed_kph=position.speed_kph,
        heading_deg=position.heading_deg,
        alarm_flags=position.alarm_flags,
        event_time=position.event_time,
        received_at=position.received_at,
        is_backfill=position.is_backfill,
    )


@tracking_router.get(
    "/vehicles/{vehicle_id}/latest",
    response_model=VehiclePositionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a vehicle's latest known position",
    description=(
        "Org Admin 24/7; Parent active-trip+granted (API Contracts §4.4). Served from "
        "Redis via `LatestPositionPort`, not the `vehicle_positions` history table "
        "(Database Design §7.1). Pending the approved RBAC permission matrix (500) and a "
        "concrete `LatestPositionPort` implementation (500) — see this module's docstring."
    ),
)
async def get_latest_vehicle_position(
    vehicle_id: str,
    principal: Principal = Depends(
        require_permission(Permission("tracking.vehicles.read_latest"))
    ),
    tracking_service: TrackingApplicationService = Depends(get_tracking_service),
) -> VehiclePositionResponse:
    position = await tracking_service.get_current_vehicle_position(
        GetCurrentVehiclePositionQuery(vehicle_id=vehicle_id)
    )
    if position is None:
        raise NotFoundError(f"No known position for vehicle {vehicle_id}.")
    return _position_dto_to_response(position)


@tracking_router.get(
    "/trips/{trip_id}/positions",
    response_model=list[VehiclePositionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get a trip's position history",
    description=(
        "Org Admin; Parent (own child, granted) (API Contracts §4.4). Trip-scoped history "
        "from the partitioned `vehicle_positions` table. Not yet paginated — see this "
        "module's docstring. Pending the approved RBAC permission matrix — see "
        "`get_latest_vehicle_position`'s note."
    ),
)
async def get_trip_position_history(
    trip_id: str,
    principal: Principal = Depends(
        require_permission(Permission("tracking.trips.read_positions"))
    ),
    tracking_service: TrackingApplicationService = Depends(get_tracking_service),
    uow: TrackingUnitOfWork = Depends(get_tracking_uow),
) -> list[VehiclePositionResponse]:
    positions = await tracking_service.get_vehicle_position_history(
        GetVehiclePositionHistoryQuery(trip_id=trip_id), uow=uow
    )
    return [_position_dto_to_response(position) for position in positions]
