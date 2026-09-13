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
  fullName: string;
  email?: string | null;
  phone?: string | null;
  licenseNo: string;
}

export interface RegisterDriverResult {
  driver: Driver;
  /** The generated one-time login password for the linked `iam.User` (role=driver) — surfaced
   * exactly once, here, for hand-off. Never re-derivable via `GET /drivers/{id}`. */
  temporaryPassword: string;
}

/** `POST /drivers` (`RegisterDriverRequest`, `transport_ops.api.schemas`) — ADR-0003: the caller
 * no longer supplies a `user_id`. The backend provisions the linked `iam.User` (role=driver)
 * itself from `full_name`/`email`/`phone` (at least one of `email`/`phone` is required —
 * `iam.User`'s own invariant) and returns `{driver, temporary_password}`
 * (`DriverCreatedResponse`), not a bare `Driver` — mirroring `registerParent`'s identical shape.
 * Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder`/`org_admin`
 * hold `transport_ops.drivers.create` — `DriversPage`/`CreateDriverForm`'s own `canManage` flag
 * mirrors this. */
export async function registerDriver(input: RegisterDriverInput): Promise<RegisterDriverResult> {
  const wire = await apiRequest<{ driver: DriverWire; temporary_password: string }>("/drivers", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      full_name: input.fullName,
      email: input.email ?? null,
      phone: input.phone ?? null,
      license_no: input.licenseNo,
    },
  });
  return { driver: toDriver(wire.driver), temporaryPassword: wire.temporary_password };
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

