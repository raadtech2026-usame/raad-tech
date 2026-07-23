import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.TripType` (Database Design §6.8:
 * `trips.trip_type ENUM(morning,afternoon)` — "Ch. 7.9 independent": morning and afternoon are
 * separate `Trip` instances, not two phases of one trip). */
export type TripType = "morning" | "afternoon";

/** `transport_ops.domain.value_objects.TripStatus` (Database Design §6.8:
 * `trips.status ENUM(scheduled,in_progress,interrupted,completed)`, matching Phase-2 §6.2's
 * documented state diagram exactly: `Scheduled -> InProgress -> Completed`, with
 * `InProgress <-> Interrupted` and `Interrupted -> Completed` as the diagram's other edges.
 * Unlike `RouteStatus`/`StudentAssignmentStatus`, illegal transitions are rejected server-side
 * with `RuleViolationError` (409 `RULE_VIOLATION`), not treated as idempotent no-ops. */
export type TripStatus = "scheduled" | "in_progress" | "interrupted" | "completed";

/** Full `TripResponse` shape (`transport_ops.api.schemas`) — returned by `GET /trips/{id}` only.
 * See `TripSummary` below for why `GET /trips` (the list route) cannot return this shape. */
export interface Trip {
  id: string;
  organizationId: string;
  vehicleId: string;
  driverId: string;
  routeId: string;
  tripType: TripType;
  status: TripStatus;
  scheduledDate: string;
  startedAt: string | null;
  endedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** `TripSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /trips`
 * returns: no `organization_id`, no `started_at`/`ended_at`, no timestamps. `TripsPage` resolves
 * vehicle/driver/route *names* for this row via best-effort id->name lookups (`listVehiclesFor
 * Picker`/`listDriversForPicker`/`listRoutesForPicker` below, called with no organization filter)
 * rather than a second per-row `GET /trips/{id}` — mirrors `RouteSummary`'s identical "list is
 * thin, detail drawer fetches the rest" split, except the *names* come from a shared lookup map
 * built once per page load, not from the detail fetch (which does still run for the drawer's
 * `startedAt`/`endedAt`/timestamps). */
export interface TripSummary {
  id: string;
  vehicleId: string;
  driverId: string;
  routeId: string;
  tripType: TripType;
  status: TripStatus;
  scheduledDate: string;
}

interface TripWire {
  id: string;
  organization_id: string;
  vehicle_id: string;
  driver_id: string;
  route_id: string;
  trip_type: string;
  status: string;
  scheduled_date: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

interface TripSummaryWire {
  id: string;
  vehicle_id: string;
  driver_id: string;
  route_id: string;
  trip_type: string;
  status: string;
  scheduled_date: string;
}

function toTrip(wire: TripWire): Trip {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    vehicleId: wire.vehicle_id,
    driverId: wire.driver_id,
    routeId: wire.route_id,
    tripType: wire.trip_type as TripType,
    status: wire.status as TripStatus,
    scheduledDate: wire.scheduled_date,
    startedAt: wire.started_at,
    endedAt: wire.ended_at,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

function toTripSummary(wire: TripSummaryWire): TripSummary {
  return {
    id: wire.id,
    vehicleId: wire.vehicle_id,
    driverId: wire.driver_id,
    routeId: wire.route_id,
    tripType: wire.trip_type as TripType,
    status: wire.status as TripStatus,
    scheduledDate: wire.scheduled_date,
  };
}

/** `GET /trips` (API Contracts §4.3 line 129 — also §8's own filtering example resource:
 * `filter[trip_type][in]=morning,afternoon`, `filter[scheduled_date][gte]=...`, though this
 * frontend's `OffsetListParams` only ever builds the equality shape, per `listParams.ts`'s own
 * docstring). Whitelist confirmed against `infra/repositories.py`'s `SqlAlchemyTripRepository`:
 * filterable `status`/`trip_type`/`vehicle_id`/`driver_id`/`route_id`/`scheduled_date`, sortable
 * `scheduled_date`/`status`/`trip_type`, **no searchable fields** (`TripsPage` has no search
 * box). Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap). */
export async function listTrips(params: OffsetListParams): Promise<OffsetPage<TripSummary>> {
  const wire = await apiRequest<OffsetPageWire<TripSummaryWire>>(`/trips?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toTripSummary);
}

/** `GET /trips/{id}` — the only route returning `organization_id`/`started_at`/`ended_at`/
 * timestamps. `TripsPage`'s detail drawer calls this on row selection, mirroring `getRoute`'s
 * identical "list is thin, drawer fetches the rest" split. */
export async function getTrip(id: string): Promise<Trip> {
  const wire = await apiRequest<TripWire>(`/trips/${id}`);
  return toTrip(wire);
}

export interface ScheduleTripInput {
  organizationId: string;
  vehicleId: string;
  driverId: string;
  routeId: string;
  tripType: TripType;
  scheduledDate: string;
}

/** `POST /trips` (`ScheduleTripRequest`) exactly: `organization_id`, `vehicle_id`, `driver_id`,
 * `route_id`, `trip_type`, `scheduled_date`. Rejects a cross-organization `driver`/`route`
 * (`DomainError`) — `vehicle_id` is never existence- or organization-checked at all
 * (`Trip`'s own docstring: a cross-module reference, opaque by construction). Per the seeded
 * RBAC matrix, only `founder`/`org_admin` hold `transport_ops.trips.create` —
 * `TripsPage`/`ScheduleTripForm`'s own `canManage` flag mirrors this. */
export async function scheduleTrip(input: ScheduleTripInput): Promise<Trip> {
  const wire = await apiRequest<TripWire>("/trips", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      vehicle_id: input.vehicleId,
      driver_id: input.driverId,
      route_id: input.routeId,
      trip_type: input.tripType,
      scheduled_date: input.scheduledDate,
    },
  });
  return toTrip(wire);
}

/** `POST /trips/{id}/start` — no request body. Legal only from `SCHEDULED`; any other status
 * raises `RuleViolationError` (409 `RULE_VIOLATION`) surfaced verbatim via a toast. Driver-
 * ownership (`_ensure_driver_owns_trip`) only applies to the `Driver` role, which has no web
 * dashboard at all (`.claude/rules/flutter.md` #1) — every caller that can reach this from
 * `TripsPage` is `founder`/`org_admin`, whose grant is an intentional admin-override, not
 * ownership-scoped, so no ownership UI logic is needed here. */
export async function startTrip(id: string): Promise<Trip> {
  const wire = await apiRequest<TripWire>(`/trips/${id}/start`, { method: "POST" });
  return toTrip(wire);
}

/** `POST /trips/{id}/end` — no request body. Legal only from `IN_PROGRESS`/`INTERRUPTED`; any
 * other status raises `RuleViolationError`. See `startTrip`'s note on driver-ownership. */
export async function endTrip(id: string): Promise<Trip> {
  const wire = await apiRequest<TripWire>(`/trips/${id}/end`, { method: "POST" });
  return toTrip(wire);
}

/** `PATCH /trips/{id}/driver` (`ChangeTripDriverRequest`, body `{driver_id}` verbatim — "change
 * driver — no device change", API Contracts line 132). Rejects a cross-organization driver
 * (`DomainError`). **No status restriction** — `Trip.change_driver`'s own docstring: no approved
 * document restricts changing a trip's driver at any particular status. Idempotent: reassigning
 * the same driver is a no-op (no event, but this endpoint still returns 200 with the unchanged
 * trip). */
export async function changeTripDriver(id: string, driverId: string): Promise<Trip> {
  const wire = await apiRequest<TripWire>(`/trips/${id}/driver`, {
    method: "PATCH",
    body: { driver_id: driverId },
  });
  return toTrip(wire);
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
 * identical function for why this is deliberately its own self-contained copy (`.claude/rules/
 * frontend.md` #1). */
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

/** Minimal, read-only `GET /vehicles` lookup — its own self-contained copy of `fleet_device.
 * devices.api.ts`'s identical `listVehiclesForPicker` (`.claude/rules/frontend.md` #1: feature
 * folders don't cross-import each other's `api.ts`). Serves two purposes with the same function:
 * (1) `ScheduleTripForm`'s vehicle picker, called with a real `organizationId` so the choices are
 * scoped to the trip's own organization (a UX convenience only — `Trip.schedule` never checks
 * `vehicle_id`'s organization at all, see `scheduleTrip`'s docstring); (2) `TripsPage`'s own
 * plate-number lookup for its list table, called with `organizationId: ""` (which
 * `buildOffsetListQuery` then omits entirely, per its own "skip empty filter values" behavior) to
 * resolve names for vehicles spanning every organization, since the trips list itself is not yet
 * tenant-scoped. Capped at the first 100 active vehicles (by `plate_no`) in both cases — the same
 * best-effort limitation `RoutesPage`'s/`StudentsPage`'s own `organizationNameById` lookups
 * already accept, not a new one. */
export async function listVehiclesForPicker(organizationId: string, search: string): Promise<VehicleOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters: { organization_id: organizationId, status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehicleOptionWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({ id: vehicle.id, plateNo: vehicle.plate_no, label: vehicle.label }));
}

export interface DriverOption {
  id: string;
  licenseNo: string;
}

interface DriverOptionWire {
  id: string;
  license_no: string;
}

/** Minimal, read-only `GET /drivers` lookup. **Not organization-scoped, unlike
 * `listVehiclesForPicker`** — a real, discovered limitation: `SqlAlchemyDriverRepository`'s own
 * `filterable_fields` whitelists only `status` (`infra/repositories.py`), and
 * `DriverSummaryResponse` doesn't even carry `organization_id` to filter by client-side either.
 * Attempting `filter[organization_id]=...` here would raise the backend's own `ValidationError`
 * ("Field 'organization_id' is not filterable on this resource"), so this lookup is deliberately
 * left global (every active driver, capped at the first 100 by `license_no`) rather than faking a
 * scope the API can't express — `ScheduleTripForm`/`ChangeTripDriverForm` show this full list and
 * rely on the backend's real `Trip.schedule`/`change_driver` cross-organization `DomainError` as
 * the actual safety net, surfaced verbatim via a toast on a wrong pick. `licenseNo` is the only
 * readable identifying field on `Driver` (no `full_name` column exists, `transport-ops/drivers/
 * api.ts`'s own `DriverSummary` docstring). */
export async function listDriversForPicker(search: string): Promise<DriverOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "license_no", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<DriverOptionWire>>(`/drivers?${query}`);
  return wire.data.map((driver) => ({ id: driver.id, licenseNo: driver.license_no }));
}

export interface RouteOption {
  id: string;
  name: string;
}

interface RouteOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /routes` lookup. **Not organization-scoped**, for the identical reason
 * `listDriversForPicker` above isn't: `SqlAlchemyRouteRepository`'s `filterable_fields` whitelists
 * only `status`, and `RouteSummaryResponse` carries no `organization_id` either. See
 * `listDriversForPicker`'s docstring for the full reasoning — the same posture applies here
 * verbatim. */
export async function listRoutesForPicker(search: string): Promise<RouteOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<RouteOptionWire>>(`/routes?${query}`);
  return wire.data.map((route) => ({ id: route.id, name: route.name }));
}
