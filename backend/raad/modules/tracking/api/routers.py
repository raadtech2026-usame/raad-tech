"""HTTP surface of the `tracking` module (C5) — Phase 8.4. `tracking_router` mounts at
`/api/v1/tracking` (`interfaces/http/api_v1.py`); the realtime `/ws/tracking` WebSocket
endpoint (API Contracts §11.2) has its own session/subscription lifecycle entirely unlike a
REST route and now lives in `api/ws.py` (the WebSocket phase) — aggregated separately by
`interfaces/http/ws.py`, not this file, since it is a distinct FastAPI `APIRouter` (a
`websocket()` route, not `get`/`post`/etc.) with its own auth/subscribe/broadcast lifecycle.

Thin controllers only (Backend LLD §16.2): parse the request, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access. Mirrors `fleet_device`/`organization`/`iam.api.routers`'s shape exactly.

Two routes, exactly API Contracts §4.4's two REST rows:
- `GET /tracking/vehicles/{vehicle_id}/latest`
- `GET /tracking/trips/{trip_id}/positions`

**Architecture Resolution (Backend Stabilization phase, Critical/High findings #1/#3/#4 of the
pre-production review):** RBAC (`require_permission`) now resolves for real (Database Design
§4.4's `role_permissions` matrix). `GET /tracking/vehicles/{vehicle_id}/latest` fails loudly
with `NotImplementedError` (500) only if no `LatestPositionPort` is bound (no `RAAD_REDIS__URL`
configured) — `TrackingApplicationService` itself is always constructible now (`application.
services.py`'s own docstring); only the one method that actually needs Redis raises. With a
reachable Redis but no cached key for a given vehicle (including "no JT808 deployment writing
`vehicle:{id}:last` at all," true in this sandbox), the route correctly resolves to a
`404 Not Found` instead — `get_latest` returning `None` is an honest "no live position known"
answer, not a bug. Both routes now also call `interfaces.http.policy_guards.
resolve_tracking_decision` —
`TrackingVisibilityPolicy` (`.claude/rules/security.md` #4's mandatory four-dimension
predicate), previously defined but never invoked anywhere in this codebase (the review's own
exhaustive repo-wide search) — composing RBAC (already-passed by the time this runs) + CR-1
(for Parent callers, with the D4 safety-override for genuinely *live* position only, never
history — see `policy_guards.resolve_cr1_decision`'s own docstring for the full D4/CR-1
reconciliation) + `ScopeResolver`.

**`GET /tracking/trips/{trip_id}/positions` is now cursor-paginated** (Pagination/Filtering/
Sorting phase), closing API Contracts §4.4's "(paginated)" marking — previously deferred (see
git history for this module's own now-stale prior note). Cursor mode (`?limit&cursor`, `core.
pagination.CursorPageRequest`/`CursorPage`), not offset — `core/pagination/__init__.py`'s own
`§7` framing reserves cursor pagination for exactly this route and `GET /notifications`,
"stable under inserts, efficient on time-ordered data like positions." Paginates over the
fixed `(event_time, id)` keyset `list_for_trip` already ordered by ascending
(`cursor_column="event_time"`, `descending=False` — preserving the pre-existing chronological
order, not the base method's default `descending=True`); `trip_id` is injected as a mandatory,
always-ANDed filter rather than a route-exposed one (narrowing-only per §8, so it can never
widen past the path parameter's own trip). Client-supplied filters are whitelisted to
`vehicle_id`/`is_backfill` (plus `trip_id` itself) via `SqlAlchemyVehiclePositionRepository.
filterable_fields` — no `sort` parameter, since cursor pagination is always over one fixed,
already-ordered keyset, never a client-chosen one.

**No `GET` for geofence crossings is exposed** — API Contracts documents no REST endpoint for
geofence-crossing history; `GetGeofenceCrossingsQuery`/`get_geofence_crossings`
(Phase 8.2) stay reachable for whichever future contract revision documents one, the same
"routes are contract-driven, not capability-driven" stance `fleet_device`'s undocumented
camera-registration route takes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from raad.core.di.container import Container
from raad.core.errors.exceptions import AuthorizationError, NotFoundError
from raad.core.pagination import CursorPageRequest, FilterCondition
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import (
    get_container,
    get_cursor_page_request,
    get_filter_conditions,
    require_permission,
)
from raad.interfaces.http.pagination import CursorPageResponse, to_cursor_page_response
from raad.interfaces.http.policy_guards import resolve_tracking_decision
from raad.modules.fleet_device.api.deps import get_fleet_device_uow
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.tracking.api.deps import (
    get_fleet_overview_service,
    get_tracking_service,
    get_tracking_uow,
)
from raad.modules.tracking.api.schemas import (
    FleetOnlineVehiclesResponse,
    OnlineVehiclePositionResponse,
    OnlineVehicleResponse,
    VehiclePositionResponse,
)
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.queries import (
    FleetOnlineVehiclesDTO,
    GetCurrentVehiclePositionQuery,
    GetVehiclePositionHistoryQuery,
    OnlineVehicleDTO,
    VehiclePositionDTO,
)
from raad.modules.tracking.application.services import (
    FleetOverviewApplicationService,
    TrackingApplicationService,
)
from raad.modules.transport_ops.api.deps import get_trip_service, get_transport_ops_uow
from raad.modules.transport_ops.application.queries import GetTripByIdQuery
from raad.modules.transport_ops.application.services import TripApplicationService

tracking_router = APIRouter()

#: ADR-0031 — a real gap found while wiring this route, not assumed away: `tracking.vehicles.
#: read_latest` (reused above for the coarse gate, deliberately not a new permission/migration)
#: is *also* held by `parent` (`role_permissions` seed migration `5437a5d1651b`'s own
#: `_PARENT_PERMISSIONS`) for their existing single-vehicle, CR-1-gated use case
#: (`GET /tracking/vehicles/{id}/latest`, `/ws/tracking`). This new *bulk* route has no
#: per-vehicle ownership check at all (see its own description for why — an admin fleet-list
#: view, not a single-vehicle CR-1 read) — reusing the permission alone would let a parent's own
#: mobile JWT list every vehicle in their organization, not just their child's. Mirrors
#: `core.policies.video_access._VIDEO_ELIGIBLE_ROLES`'s identical shape: an explicit,
#: migration-free role-set check layered on top of `require_permission`, for exactly this
#: "the permission is broader than this one route needs" mismatch.
_FLEET_OVERVIEW_ELIGIBLE_ROLES = frozenset(
    {Role.FOUNDER, Role.REGIONAL_MANAGER, Role.SUPPORT_STAFF, Role.ORG_ADMIN}
)


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
        "(Database Design §7.1). `TrackingVisibilityPolicy` (D4/CR-1-aware) enforced — see "
        "this module's docstring."
    ),
)
async def get_latest_vehicle_position(
    request: Request,
    vehicle_id: str,
    principal: Principal = Depends(
        require_permission(Permission("tracking.vehicles.read_latest"))
    ),
    tracking_service: TrackingApplicationService = Depends(get_tracking_service),
    trip_service: TripApplicationService = Depends(get_trip_service),
    transport_ops_uow=Depends(get_transport_ops_uow),
) -> VehiclePositionResponse:
    position = await tracking_service.get_current_vehicle_position(
        GetCurrentVehiclePositionQuery(vehicle_id=vehicle_id)
    )
    if position is None:
        raise NotFoundError(f"No known position for vehicle {vehicle_id}.")

    is_trip_active = False
    if position.trip_id is not None:
        trip = await trip_service.get_trip_by_id(
            GetTripByIdQuery(trip_id=position.trip_id), uow=transport_ops_uow
        )
        is_trip_active = trip.status == "in_progress"

    container: Container = get_container(request)
    decision = await resolve_tracking_decision(
        principal=principal,
        organization_id=position.organization_id,
        vehicle_id=vehicle_id,
        is_trip_active=is_trip_active,
        container=container,
    )
    if not decision.allowed:
        raise AuthorizationError(f"Access denied: {decision.reason}")

    return _position_dto_to_response(position)


@tracking_router.get(
    "/trips/{trip_id}/positions",
    response_model=CursorPageResponse[VehiclePositionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get a trip's position history (cursor-paginated)",
    description=(
        "Org Admin; Parent (own child, granted) (API Contracts §4.4). Trip-scoped history "
        "from the partitioned `vehicle_positions` table, cursor-paginated (`?limit&cursor`) "
        "over the `event_time` ascending keyset — the same order `list_for_trip` always used. "
        "Filterable by `vehicle_id`/`is_backfill` (`?filter[field]=value`); `trip_id` itself "
        "is always the path parameter's trip, never client-widenable. `TrackingVisibilityPolicy` "
        "enforced (history is never a D4-safety-override case — always fully CR-1-gated, see "
        "`policy_guards.resolve_cr1_decision`'s docstring)."
    ),
)
async def get_trip_position_history(
    request: Request,
    trip_id: str,
    principal: Principal = Depends(
        require_permission(Permission("tracking.trips.read_positions"))
    ),
    cursor_request: CursorPageRequest = Depends(get_cursor_page_request),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    tracking_service: TrackingApplicationService = Depends(get_tracking_service),
    uow: TrackingUnitOfWork = Depends(get_tracking_uow),
    trip_service: TripApplicationService = Depends(get_trip_service),
    transport_ops_uow=Depends(get_transport_ops_uow),
) -> CursorPageResponse[VehiclePositionResponse]:
    trip = await trip_service.get_trip_by_id(
        GetTripByIdQuery(trip_id=trip_id), uow=transport_ops_uow
    )

    container: Container = get_container(request)
    decision = await resolve_tracking_decision(
        principal=principal,
        organization_id=trip.organization_id,
        vehicle_id=trip.vehicle_id,
        is_trip_active=False,  # history is never the D4 live-safety-override case
        container=container,
    )
    if not decision.allowed:
        raise AuthorizationError(f"Access denied: {decision.reason}")

    page = await tracking_service.get_vehicle_position_history(
        GetVehiclePositionHistoryQuery(
            trip_id=trip_id, cursor_request=cursor_request, filters=filters
        ),
        uow=uow,
    )
    return to_cursor_page_response(page, _position_dto_to_response)


def _online_vehicle_dto_to_response(vehicle: OnlineVehicleDTO) -> OnlineVehicleResponse:
    return OnlineVehicleResponse(
        vehicle_id=vehicle.vehicle_id,
        plate_no=vehicle.plate_no,
        label=vehicle.label,
        device_id=vehicle.device_id,
        is_online=vehicle.is_online,
        position=(
            OnlineVehiclePositionResponse(
                latitude=vehicle.position.latitude,
                longitude=vehicle.position.longitude,
                heading_deg=vehicle.position.heading_deg,
                speed_kph=vehicle.position.speed_kph,
                event_time=vehicle.position.event_time,
            )
            if vehicle.position is not None
            else None
        ),
    )


@tracking_router.get(
    "/vehicles/online",
    response_model=FleetOnlineVehiclesResponse,
    status_code=status.HTTP_200_OK,
    summary="List online vehicles for the All Vehicles fleet-map mode",
    description=(
        "ADR-0031 (Fleet Overview read model). Founder/Regional Manager/Support Staff/Org "
        "Admin only — gated by the existing `tracking.vehicles.read_latest` permission "
        "(reused, no new grant/migration) *plus* an explicit role-set check "
        "(`_FLEET_OVERVIEW_ELIGIBLE_ROLES`, this file), since that permission is also held by "
        "`parent` for their own single-vehicle, CR-1-gated use case — this bulk route has no "
        "per-vehicle ownership check at all (an admin fleet-list view, matching `GET /vehicles`/"
        "`GET /devices` (list)'s own posture, not `GET /tracking/vehicles/{id}/latest`'s "
        "single-vehicle CR-1 posture), so a parent must never reach it. Scoped by the caller's "
        "own tenant/region (ADR-0021, applied automatically at the repository layer). "
        "`position` is `null` today for every vehicle — a confirmed, disclosed gap (the live "
        "JT808 adapter doesn't yet write `vehicle:{id}:last`), not a bug in this route. Capped "
        "at `FLEET_OVERVIEW_MAX_ONLINE_VEHICLES` online vehicles (`application/services.py`) — "
        "realtime *updates* for the returned set happen over the existing `/ws/tracking`, "
        "never a poll of this route."
    ),
)
async def list_online_vehicles(
    principal: Principal = Depends(
        require_permission(Permission("tracking.vehicles.read_latest"))
    ),
    fleet_overview_service: FleetOverviewApplicationService = Depends(
        get_fleet_overview_service
    ),
    fleet_device_uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> FleetOnlineVehiclesResponse:
    if principal.role not in _FLEET_OVERVIEW_ELIGIBLE_ROLES:
        raise AuthorizationError(
            "Access denied: the fleet overview is not available to this role."
        )

    result = await fleet_overview_service.list_online_vehicles(
        fleet_device_uow=fleet_device_uow
    )
    return FleetOnlineVehiclesResponse(
        vehicles=[_online_vehicle_dto_to_response(v) for v in result.vehicles],
        total_online=result.total_online,
    )
