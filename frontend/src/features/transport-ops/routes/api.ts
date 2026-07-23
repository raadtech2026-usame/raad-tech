import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.RouteStatus` (Database Design §6.5:
 * `routes.status ENUM(active,inactive)` — documented explicitly, unlike `DriverStatus`/
 * `ParentStatus`. No third "archived" value exists. */
export type RouteStatus = "active" | "inactive";

/** `StopResponse` (`transport_ops/api/schemas.py`) — one ordered stop on a `Route`. Always
 * returned sorted by `sequence_no` (`domain/entities.py`'s `Route.stops` property). */
export interface Stop {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sequenceNo: number;
  geofenceRadiusM: number | null;
}

interface StopWire {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sequence_no: number;
  geofence_radius_m: number | null;
}

function toStop(wire: StopWire): Stop {
  return {
    id: wire.id,
    name: wire.name,
    latitude: wire.latitude,
    longitude: wire.longitude,
    sequenceNo: wire.sequence_no,
    geofenceRadiusM: wire.geofence_radius_m,
  };
}

/** Full `RouteResponse` shape (`transport_ops.api.schemas`) — returned by `GET /routes/{id}`
 * only, with its stops embedded and pre-sorted by `sequence_no` server-side. See `RouteSummary`
 * below for why `GET /routes` (the list route) cannot return this shape. */
export interface Route {
  id: string;
  organizationId: string;
  name: string;
  status: RouteStatus;
  createdAt: string;
  updatedAt: string;
  stops: Stop[];
}

/** `RouteSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /routes`
 * returns (no stops, no organization_id, no timestamps) — the identical `transport_ops`-wide
 * thin-list-response pattern `StudentSummary`/`ParentSummary`/`DriverSummary` already document. */
export interface RouteSummary {
  id: string;
  name: string;
  status: RouteStatus;
}

interface RouteWire {
  id: string;
  organization_id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
  stops: StopWire[];
}

interface RouteSummaryWire {
  id: string;
  name: string;
  status: string;
}

function toRoute(wire: RouteWire): Route {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    name: wire.name,
    status: wire.status as RouteStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    stops: wire.stops.map(toStop),
  };
}

function toRouteSummary(wire: RouteSummaryWire): RouteSummary {
  return { id: wire.id, name: wire.name, status: wire.status as RouteStatus };
}

/** `GET /routes` (API Contracts §4.3 line 125) — paginated/filterable/sortable via
 * `usePaginatedQuery`. Whitelist confirmed against `modules/transport_ops/infra/repositories.py`'s
 * `SqlAlchemyRouteRepository`: filterable `status` only, sortable `name`/`status`, searchable
 * `name`. Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap). */
export async function listRoutes(params: OffsetListParams): Promise<OffsetPage<RouteSummary>> {
  const wire = await apiRequest<OffsetPageWire<RouteSummaryWire>>(`/routes?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toRouteSummary);
}

/** `GET /routes/{id}` — the only route returning the full `Route` shape, stops embedded and
 * pre-ordered. `RoutesPage`'s detail drawer calls this on row selection rather than reusing the
 * list row alone — see `Route`'s own docstring. */
export async function getRoute(id: string): Promise<Route> {
  const wire = await apiRequest<RouteWire>(`/routes/${id}`);
  return toRoute(wire);
}

export interface CreateRouteInput {
  organizationId: string;
  name: string;
}

/** `POST /routes` (`CreateRouteRequest`) exactly: `organization_id`, `name`. Per the seeded RBAC
 * matrix (`migrations/versions/20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`),
 * only `founder`/`org_admin` hold `transport_ops.routes.create` — `RoutesPage`'s own `canManage`
 * flag mirrors this. */
export async function createRoute(input: CreateRouteInput): Promise<Route> {
  const wire = await apiRequest<RouteWire>("/routes", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      name: input.name,
    },
  });
  return toRoute(wire);
}

/** `PATCH /routes/{id}` sending only `status` — dispatches to `activate_route`/`disable_route`,
 * leaving `name` untouched since it's omitted from the request body. Mirrors
 * `updateDriverStatus`/`updateParentStatus`'s identical status-only-PATCH shape. `name` editing
 * is not wired to any UI this phase — the same restraint every other entity in this bounded
 * context already documents. */
export async function updateRouteStatus(id: string, status: RouteStatus): Promise<Route> {
  const wire = await apiRequest<RouteWire>(`/routes/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toRoute(wire);
}

export interface AddStopInput {
  name: string;
  latitude: number;
  longitude: number;
  sequenceNo: number;
  geofenceRadiusM?: number | null;
}

/** `POST /routes/{route_id}/stops` (`AddStopToRouteRequest`) exactly: `name`, `latitude`,
 * `longitude`, `sequence_no`, `geofence_radius_m`. Returns the created `StopResponse` (the
 * "POST-to-a-nested-collection returns the created child" shape, matching
 * `linkGuardianToStudent`'s sibling precedent).
 *
 * **Rejects a duplicate `sequence_no` within the route** (`ConflictError`, 409) and
 * out-of-range coordinates/sequence (`DomainError`), both from `Route.add_stop`
 * (`domain/entities.py`) — surfaced verbatim via a toast using `error.message`, the same
 * handling every other `ApiError` consumer in this codebase already applies.
 *
 * **No `PATCH`/`DELETE` route exists for an individual stop** — `Route.move_stop`/`remove_stop`
 * are implemented and unit-tested at the domain/application layers, but API Contracts §4.3 line
 * 126 documents only `GET`/`POST /routes/{id}/stops`, so no HTTP endpoint is exposed for them
 * this phase (`routers.py`'s own module docstring). `RoutesPage`'s stop list is therefore
 * add-and-view only — no reorder, no remove — with an honest, visible affordance explaining why,
 * rather than omitting the capability invisibly. */
export async function addStopToRoute(routeId: string, input: AddStopInput): Promise<Stop> {
  const wire = await apiRequest<StopWire>(`/routes/${routeId}/stops`, {
    method: "POST",
    body: {
      name: input.name,
      latitude: input.latitude,
      longitude: input.longitude,
      sequence_no: input.sequenceNo,
      geofence_radius_m: input.geofenceRadiusM ?? null,
    },
  });
  return toStop(wire);
}

export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup — see `features/fleet-devices/vehicles/api.ts`'s
 * identical function for why this is deliberately its own self-contained copy rather than a
 * shared/cross-imported helper (`.claude/rules/frontend.md` #1). */
export async function listOrganizationsForPicker(search: string): Promise<OrganizationOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<OrganizationOptionWire>>(`/organizations?${query}`);
  return wire.data.map((org) => ({ id: org.id, name: org.name }));
}
