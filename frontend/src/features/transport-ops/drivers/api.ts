import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.DriverStatus` (Database Design §6.1 gives `drivers.status`
 * with no enumerated values at all — `value_objects.py`'s own docstring: "flagged, not guessed").
 * A flat active/inactive toggle, the same situation `ParentStatus` already documents. `Driver`'s
 * own login/account lifecycle lives entirely on the linked `iam.User` row — this status is
 * `transport_ops`'s own, separate concept (an Org Admin enabling/disabling a driver's
 * transport-facing profile without touching their login credentials). */
export type DriverStatus = "active" | "inactive";

/** Full `DriverResponse` shape (`transport_ops.api.schemas`) — returned by `GET /drivers/{id}`
 * only. See `DriverSummary` below for why `GET /drivers` (the list route) cannot return this
 * shape. */
export interface Driver {
  id: string;
  organizationId: string;
  userId: string;
  licenseNo: string;
  status: DriverStatus;
  createdAt: string;
  updatedAt: string;
}

/** `DriverSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /drivers`
 * returns. **`Driver` has no `full_name` of its own at all** (unlike `Student`/`Parent`) — Database
 * Design §6.1 gives the table no such column, so `licenseNo` stands in as this entity's only
 * readable identifying field, mirroring `infra/repositories.py`'s own
 * `SqlAlchemyDriverRepository` docstring verbatim. `DriversPage`'s table therefore shows
 * "License No" as its primary column, not a person's name. */
export interface DriverSummary {
  id: string;
  licenseNo: string;
  status: DriverStatus;
}

/** Wire shape of `DriverResponse` — snake_case, exactly as the backend serializes it. */
interface DriverWire {
  id: string;
  organization_id: string;
  user_id: string;
  license_no: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Wire shape of `DriverSummaryResponse`. */
interface DriverSummaryWire {
  id: string;
  license_no: string;
  status: string;
}

function toDriver(wire: DriverWire): Driver {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    userId: wire.user_id,
    licenseNo: wire.license_no,
    status: wire.status as DriverStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

function toDriverSummary(wire: DriverSummaryWire): DriverSummary {
  return { id: wire.id, licenseNo: wire.license_no, status: wire.status as DriverStatus };
}

/** `GET /drivers` (no documented API Contracts row — Phase 10.8's own flagged gap: Database
 * Design §6.1/ADR-0001 define the table and its ownership unambiguously, but API Contracts §4.3
 * lists no `/drivers` resource row at all, the same documentation gap `student_parents`/`routes`
 * stop-reorder already carry elsewhere in this codebase). Whitelist confirmed against
 * `modules/transport_ops/infra/repositories.py`'s `SqlAlchemyDriverRepository`: filterable
 * `status` only, sortable `license_no`/`status`, searchable `license_no`. Not yet scope-filtered
 * server-side (CLAUDE.md's own flagged, system-wide gap), matching every other list endpoint. */
export async function listDrivers(params: OffsetListParams): Promise<OffsetPage<DriverSummary>> {
  const wire = await apiRequest<OffsetPageWire<DriverSummaryWire>>(`/drivers?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toDriverSummary);
}

/** `GET /drivers/{id}` — the only route returning the full `Driver` shape (`organizationId`,
 * `userId`, `createdAt`/`updatedAt`). `DriversPage`'s detail drawer calls this on row selection
 * rather than reusing the list row alone — see `Driver`'s own docstring. */
export async function getDriver(id: string): Promise<Driver> {
  const wire = await apiRequest<DriverWire>(`/drivers/${id}`);
  return toDriver(wire);
}

export interface RegisterDriverInput {
  organizationId: string;
  userId: string;
  licenseNo: string;
}

/** `POST /drivers` (`RegisterDriverRequest`) exactly: `organization_id`, `user_id`, `license_no`.
 * `user_id` links this transport-facing profile to an *existing* `iam.User` login (mirroring
 * `Parent.user_id`'s identical precedent) — this form does not create a `User`, only references
 * one that must already exist (typically invited with `role: "driver"` via Users & Roles first).
 * Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder`/`org_admin`
 * hold `transport_ops.drivers.create` — `DriversPage`/`CreateDriverForm`'s own `canManage` flag
 * mirrors this. See `CreateDriverForm.tsx`'s own docstring for the identical `iam.users.read` gap
 * `CreateParentForm.tsx` already surfaced: `org_admin` cannot browse `GET /users`. */
export async function registerDriver(input: RegisterDriverInput): Promise<Driver> {
  const wire = await apiRequest<DriverWire>("/drivers", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      user_id: input.userId,
      license_no: input.licenseNo,
    },
  });
  return toDriver(wire);
}

/** `PATCH /drivers/{id}` sending only `status` — dispatches to `activate_driver`/
 * `disable_driver` (`routers.py`'s `update_driver`), leaving `license_no` untouched since it's
 * omitted from the request body. Mirrors `updateParentStatus`'s identical status-only-PATCH
 * shape. `license_no` editing is not wired to any UI this phase — the same restraint
 * `updateStudentStatus`/`updateParentStatus` already document. */
export async function updateDriverStatus(id: string, status: DriverStatus): Promise<Driver> {
  const wire = await apiRequest<DriverWire>(`/drivers/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toDriver(wire);
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

export interface UserOption {
  id: string;
  fullName: string;
  email: string | null;
  phone: string | null;
}

interface UserOptionWire {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
}

/** Minimal, read-only `GET /users` lookup backing `CreateDriverForm`'s "linked user" picker —
 * filtered to the target organization and `role=driver`/`status=active`. Identical precedent to
 * `admin/users/api.ts`/`transport-ops/parents/api.ts`'s own pickers for an unavoidable
 * cross-bounded-context "pick an existing X" read.
 *
 * **Only reachable for a principal holding `iam.users.read`** — per the seeded RBAC matrix, that
 * is `founder` only among the roles that also hold `transport_ops.drivers.create` (`org_admin`
 * holds no `iam.users.*` permission at all). `CreateDriverForm.tsx` therefore only calls this for
 * `founder`; see that component's own docstring for how `org_admin` supplies a `user_id`
 * instead. */
export async function listDriverUsersForPicker(organizationId: string, search: string): Promise<UserOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "full_name", direction: "asc" },
    filters: { organization_id: organizationId, role: "driver", status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<UserOptionWire>>(`/users?${query}`);
  return wire.data.map((user) => ({ id: user.id, fullName: user.full_name, email: user.email, phone: user.phone }));
}
