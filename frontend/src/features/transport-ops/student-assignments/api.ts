import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.StudentAssignmentStatus` (Database Design §6.7:
 * `student_assignments.status ENUM(active,removed,transferred,graduated,disabled)`) —
 * **"the CR-1 access gate"** (`assignment_state` input to `SubscriptionAccessPolicy`, Backend LLD
 * §5.4). No transition graph is documented for this enum (unlike `TripStatus`) — every value is
 * directly settable server-side, mirroring `StudentStatus`'s identical situation. */
export type StudentAssignmentStatus = "active" | "removed" | "transferred" | "graduated" | "disabled";

/** Full `StudentAssignmentResponse` shape (`transport_ops.api.schemas`) — returned by both
 * `GET /student-assignments/{id}` and `POST /student-assignments`/`.../end`. **Does not include
 * `created_at`/`updated_at`'s usual sibling treatment beyond the raw fields below** — this is the
 * one exception `CLAUDE.md` documents for this specific resource; `assignedAt`/`endedAt` are its
 * own domain-meaningful timestamps, distinct from the audit-column pair. */
export interface StudentAssignment {
  id: string;
  organizationId: string;
  studentId: string;
  routeId: string;
  pickupStopId: string;
  dropoffStopId: string;
  vehicleId: string | null;
  status: StudentAssignmentStatus;
  assignedAt: string;
  endedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** `StudentAssignmentSummaryResponse` — the *only* shape `GET /student-assignments` returns:
 * `id`/`student_id`/`route_id`/`status` only, no pickup/dropoff stop, no vehicle, no timestamps.
 * `StudentAssignmentSection` never renders this list view directly — it uses `listStudentAssignments`
 * only to *find* a student's current assignment id (filtered by `student_id`), then fetches the
 * full shape via `getStudentAssignment` for anything worth displaying. */
export interface StudentAssignmentSummary {
  id: string;
  studentId: string;
  routeId: string;
  status: StudentAssignmentStatus;
}

interface StudentAssignmentWire {
  id: string;
  organization_id: string;
  student_id: string;
  route_id: string;
  pickup_stop_id: string;
  dropoff_stop_id: string;
  vehicle_id: string | null;
  status: string;
  assigned_at: string;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

interface StudentAssignmentSummaryWire {
  id: string;
  student_id: string;
  route_id: string;
  status: string;
}

function toStudentAssignment(wire: StudentAssignmentWire): StudentAssignment {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    studentId: wire.student_id,
    routeId: wire.route_id,
    pickupStopId: wire.pickup_stop_id,
    dropoffStopId: wire.dropoff_stop_id,
    vehicleId: wire.vehicle_id,
    status: wire.status as StudentAssignmentStatus,
    assignedAt: wire.assigned_at,
    endedAt: wire.ended_at,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

function toStudentAssignmentSummary(wire: StudentAssignmentSummaryWire): StudentAssignmentSummary {
  return {
    id: wire.id,
    studentId: wire.student_id,
    routeId: wire.route_id,
    status: wire.status as StudentAssignmentStatus,
  };
}

/** `GET /student-assignments` (API Contracts §4.3 line 127). Whitelist confirmed against
 * `infra/repositories.py`'s `SqlAlchemyStudentAssignmentRepository`: filterable `status`/
 * `route_id`/`student_id`, sortable `status` only, **no searchable fields**. `student_id` is the
 * filter `findActiveAssignmentForStudent` below relies on to scope this otherwise-unscoped list
 * down to one student. Not yet tenant-scoped server-side (CLAUDE.md's own flagged, system-wide
 * gap). */
export async function listStudentAssignments(
  params: OffsetListParams,
): Promise<OffsetPage<StudentAssignmentSummary>> {
  const wire = await apiRequest<OffsetPageWire<StudentAssignmentSummaryWire>>(
    `/student-assignments?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toStudentAssignmentSummary);
}

/** `GET /student-assignments/{id}` — the only route returning the full shape (pickup/dropoff
 * stop, vehicle, `assignedAt`/`endedAt`, timestamps). */
export async function getStudentAssignment(id: string): Promise<StudentAssignment> {
  const wire = await apiRequest<StudentAssignmentWire>(`/student-assignments/${id}`);
  return toStudentAssignment(wire);
}

/** Resolves a student's current active assignment, if one exists — "one active assignment per
 * student" (Database Design §6.7) means at most one row can ever come back for
 * `filter[student_id]=X&filter[status]=active`. Two requests (list, then detail) rather than one,
 * because `StudentAssignmentSummaryResponse` alone carries no pickup/dropoff/vehicle/`assignedAt`
 * to show — the same "list is thin, fetch the rest" split every other resource in this codebase
 * already follows. Returns `null` when the student has no active assignment (never a fabricated
 * placeholder) — `StudentAssignmentSection` renders an honest "no active route assignment" state
 * in that case. */
export async function findActiveAssignmentForStudent(studentId: string): Promise<StudentAssignment | null> {
  const page = await listStudentAssignments({
    page: 1,
    pageSize: 1,
    sort: null,
    filters: { student_id: studentId, status: "active" },
    search: "",
  });
  const summary = page.data[0];
  if (!summary) {
    return null;
  }
  return getStudentAssignment(summary.id);
}

export interface AssignStudentToRouteInput {
  organizationId: string;
  studentId: string;
  routeId: string;
  pickupStopId: string;
  dropoffStopId: string;
  vehicleId?: string | null;
}

/** `POST /student-assignments` (`AssignStudentToRouteRequest`) exactly: `organization_id`,
 * `student_id`, `route_id`, `pickup_stop_id`, `dropoff_stop_id`, `vehicle_id`. Rejects a
 * student/route not found, a pickup/dropoff stop not on the given route (`NotFoundError`),
 * cross-organization student/route (`DomainError`), and a student who already has an active
 * assignment (`ConflictError`, one-active-assignment-per-student) — all surfaced verbatim via a
 * toast. Per the seeded RBAC matrix, only `founder`/`org_admin` hold
 * `transport_ops.student_assignments.create`. */
export async function assignStudentToRoute(input: AssignStudentToRouteInput): Promise<StudentAssignment> {
  const wire = await apiRequest<StudentAssignmentWire>("/student-assignments", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      student_id: input.studentId,
      route_id: input.routeId,
      pickup_stop_id: input.pickupStopId,
      dropoff_stop_id: input.dropoffStopId,
      vehicle_id: input.vehicleId ?? null,
    },
  });
  return toStudentAssignment(wire);
}

/** `POST /student-assignments/{id}/end` (body `{status}` -> removed/transferred/graduated/
 * disabled -> CR-1 revocation event, API Contracts line 128 verbatim). `active` is not a legal
 * target here — there is no "re-activate" use-case on this endpoint (a new assignment is created
 * instead, mirroring `Payment.initiate`'s own "a retry is a new row, not a status flip"
 * precedent). */
export async function endStudentAssignment(
  id: string,
  status: Exclude<StudentAssignmentStatus, "active">,
): Promise<StudentAssignment> {
  const wire = await apiRequest<StudentAssignmentWire>(`/student-assignments/${id}/end`, {
    method: "POST",
    body: { status },
  });
  return toStudentAssignment(wire);
}

export interface RouteOption {
  id: string;
  name: string;
}

interface RouteOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /routes` lookup for `AssignStudentForm`'s route picker. **Not
 * organization-scoped** — `SqlAlchemyRouteRepository`'s `filterable_fields` whitelists only
 * `status` (confirmed in `infra/repositories.py`), and `RouteSummaryResponse` carries no
 * `organization_id` to filter by client-side either; the identical gap `transport-ops/trips/
 * api.ts`'s own `listRoutesForPicker` docstring already documents. A cross-organization pick
 * still surfaces the backend's real `DomainError` verbatim via a toast on submit. */
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

export interface StopOption {
  id: string;
  name: string;
  sequenceNo: number;
}

export interface RouteWithStops {
  id: string;
  name: string;
  stops: StopOption[];
}

interface RouteWithStopsWire {
  id: string;
  name: string;
  stops: { id: string; name: string; sequence_no: number }[];
}

/** Minimal, read-only `GET /routes/{id}` read — used for its `name` plus its embedded,
 * pre-ordered `stops` list (`RouteResponse.stops`, always sorted by `sequence_no` server-side,
 * `transport_ops.domain.entities.Route.stops`). Backs `AssignStudentForm`'s pickup/dropoff stop
 * pickers once a route is chosen, and `StudentAssignmentSection`'s own route-name/stop-name
 * display for an existing assignment. Deliberately its own self-contained read rather than an
 * import from `features/transport-ops/routes/api.ts`'s `getRoute` (`.claude/rules/frontend.md`
 * #1: no cross-feature-folder `api.ts` import exists anywhere in this codebase). */
export async function getRouteWithStops(routeId: string): Promise<RouteWithStops> {
  const wire = await apiRequest<RouteWithStopsWire>(`/routes/${routeId}`);
  return {
    id: wire.id,
    name: wire.name,
    stops: wire.stops.map((stop) => ({ id: stop.id, name: stop.name, sequenceNo: stop.sequence_no })),
  };
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

/** Minimal, read-only `GET /vehicles` lookup for `AssignStudentForm`'s optional vehicle picker —
 * `fleet_device`'s `SqlAlchemyVehicleRepository` *does* whitelist `organization_id`
 * (`infra/repositories.py`, a different module from `Route`/`Driver` above), so this one can stay
 * genuinely organization-scoped, mirroring `fleet-devices/devices/api.ts`'s identical
 * `listVehiclesForPicker`. */
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
