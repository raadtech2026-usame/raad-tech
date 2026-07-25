import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery } from "../../shared/api/listParams";
import type { OffsetPageWire } from "../../shared/api/types";
import { ApiError } from "../../shared/api/types";

/** `VehiclePositionResponse` (`tracking/api/schemas.py`) — the shape `GET /tracking/vehicles/
 * {id}/latest` returns. */
export interface VehiclePosition {
  vehicleId: string;
  tripId: string | null;
  latitude: number;
  longitude: number;
  speedKph: number;
  headingDeg: number;
  eventTime: string;
}

interface VehiclePositionWire {
  vehicle_id: string;
  trip_id: string | null;
  latitude: number;
  longitude: number;
  speed_kph: number;
  heading_deg: number;
  event_time: string;
}

function toVehiclePosition(wire: VehiclePositionWire): VehiclePosition {
  return {
    vehicleId: wire.vehicle_id,
    tripId: wire.trip_id,
    latitude: wire.latitude,
    longitude: wire.longitude,
    speedKph: wire.speed_kph,
    headingDeg: wire.heading_deg,
    eventTime: wire.event_time,
  };
}

/** `GET /tracking/vehicles/{id}/latest` — reads `LatestPositionPort` (Redis), never Postgres
 * (`tracking/application/services.py`'s `get_current_vehicle_position`). A 404 means "no known
 * live position yet" (honest, expected — this session's own device-onboarding-readiness audit
 * confirmed nothing currently writes the `vehicle:{id}:last` key anywhere in this platform, so
 * this will 404 for every vehicle until a device-plane writer exists), mapped to `null` rather
 * than surfaced as an error. Any other status (e.g. a 500 if Redis itself isn't configured at
 * all) propagates as a normal `ApiError` — that is a real misconfiguration, not an honest empty
 * state, and should not be silently swallowed the same way. */
export async function getLatestVehiclePosition(vehicleId: string): Promise<VehiclePosition | null> {
  try {
    const wire = await apiRequest<VehiclePositionWire>(`/tracking/vehicles/${vehicleId}/latest`);
    return toVehiclePosition(wire);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** `/ws/tracking`'s server->client frames (API Contracts §11.2, verified this session directly
 * against `backend/raad/modules/tracking/api/ws.py`'s own `_position_frame`/
 * `_handle_trip_ended_event`). `TrackingWsMessage` is deliberately not exhaustive of every
 * possible `type` — an unrecognized one is just ignored by the caller, mirroring the backend's
 * own "unknown message types are ignored, forward-compatible" posture for the reverse direction. */
export interface PositionFrame {
  type: "position";
  vehicle_id: string;
  trip_id: string | null;
  lat: number;
  lng: number;
  speed_kph: number;
  heading_deg: number;
  event_time: string;
}

export interface SubscriptionClosedFrame {
  type: "subscription_closed";
  vehicle_id: string;
  reason: string;
}

export type TrackingWsMessage = PositionFrame | SubscriptionClosedFrame;

export interface VehicleOption {
  id: string;
  plateNo: string;
  label: string | null;
}

interface VehicleOptionWire {
  id: string;
  plate_no: string;
  label: string | null;
}

/** Minimal, read-only `GET /vehicles` lookup — this feature folder's own self-contained copy
 * (`.claude/rules/frontend.md` #1: no cross-feature-folder `api.ts` import), matching
 * `transport-ops/trips/api.ts`'s/`fleet-devices/devices/api.ts`'s identical
 * `listVehiclesForPicker` precedent exactly. Capped at the first 100 active vehicles. */
export async function listVehiclesForTracking(search: string): Promise<VehicleOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehicleOptionWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({ id: vehicle.id, plateNo: vehicle.plate_no, label: vehicle.label }));
}

interface TripSummaryWire {
  id: string;
  route_id: string;
}

/** Looks up whether the given vehicle currently has an `in_progress` trip, for the route/stop
 * overlay — this feature folder's own minimal copy of `GET /trips`, filtered server-side
 * (`vehicle_id`/`status` are both whitelisted filter fields, confirmed against
 * `transport-ops/trips/api.ts`'s own documented whitelist). Returns the trip's `route_id`, or
 * `null` if no active trip exists (the common case outside a scheduled run — an honest "nothing
 * to overlay" result, not an error). */
export async function getActiveTripRouteId(vehicleId: string): Promise<string | null> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 1,
    sort: null,
    filters: { vehicle_id: vehicleId, status: "in_progress" },
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<TripSummaryWire>>(`/trips?${query}`);
  return wire.data[0]?.route_id ?? null;
}

export interface RouteStop {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sequenceNo: number;
  geofenceRadiusM: number | null;
}

export interface RouteWithStops {
  id: string;
  name: string;
  stops: RouteStop[];
}

interface StopWire {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sequence_no: number;
  geofence_radius_m: number | null;
}

interface RouteWire {
  id: string;
  name: string;
  stops: StopWire[];
}

/** `GET /routes/{id}` — this feature folder's own minimal copy (only `id`/`name`/`stops`, no
 * `status`/timestamps this feature never needs), matching `transport-ops/routes/api.ts`'s own
 * `getRoute` precedent. Stops arrive pre-sorted by `sequence_no` server-side. */
export async function getRouteWithStops(routeId: string): Promise<RouteWithStops> {
  const wire = await apiRequest<RouteWire>(`/routes/${routeId}`);
  return {
    id: wire.id,
    name: wire.name,
    stops: wire.stops.map((stop) => ({
      id: stop.id,
      name: stop.name,
      latitude: stop.latitude,
      longitude: stop.longitude,
      sequenceNo: stop.sequence_no,
      geofenceRadiusM: stop.geofence_radius_m,
    })),
  };
}
