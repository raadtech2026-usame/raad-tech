import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.StudentStatus` (Database Design §6.2's
 * `status ENUM(active,disabled,graduated,transferred)`). No documented state-transition diagram
 * exists for this enum (`domain/entities.py`'s module docstring: "flat enum plus its CR-1
 * consequence... not an invented restriction graph") — every status is directly settable with an
 * idempotent same-state no-op, the same `organization.domain.entities.Organization.suspend/
 * reactivate/deactivate` precedent `fleet_device.Vehicle` already follows too. All four values
 * are reachable via `POST /students/{id}/status` (`UpdateStudentStatusRequest`'s own docstring:
 * `"active"` is also accepted there, reaching `activate_student`). */
export type StudentStatus = "active" | "disabled" | "graduated" | "transferred";

/** Full `StudentResponse` shape (`transport_ops.api.schemas`) — returned by `GET /students/{id}`
 * only. See `StudentSummary` below for why `GET /students` (the list route) cannot return this
 * shape. */
export interface Student {
  id: string;
  organizationId: string;
  fullName: string;
  externalRef: string | null;
  status: StudentStatus;
  createdAt: string;
  updatedAt: string;
}

/** `StudentSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /students`
 * returns (`routers.py`'s `list_students`,
 * `response_model=OffsetPageResponse[StudentSummaryResponse]`). Deliberately thin: no
 * `organization_id`, no `external_ref`, no `created_at`/`updated_at` — a real, confirmed
 * difference from every list route F1-F3 built (`Organization`/`Vehicle`/`Device`/`User` all
 * return their *full* response shape from their own list route; `transport_ops` does not).
 * `StudentsPage`'s table therefore shows only name + status, and opening the detail drawer issues
 * a second `GET /students/{id}` (`getStudent` below) for the richer fields — never fabricating
 * columns the list response doesn't actually carry. */
export interface StudentSummary {
  id: string;
  fullName: string;
  status: StudentStatus;
}

/** Wire shape of `StudentResponse` — snake_case, exactly as the backend serializes it. */
interface StudentWire {
  id: string;
  organization_id: string;
  full_name: string;
  external_ref: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Wire shape of `StudentSummaryResponse`. */
interface StudentSummaryWire {
  id: string;
  full_name: string;
  status: string;
}

function toStudent(wire: StudentWire): Student {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    fullName: wire.full_name,
    externalRef: wire.external_ref,
    status: wire.status as StudentStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

function toStudentSummary(wire: StudentSummaryWire): StudentSummary {
  return { id: wire.id, fullName: wire.full_name, status: wire.status as StudentStatus };
}

/** `GET /students` (API Contracts §4.3's `/students` row; `transport_ops.api.routers.
 * list_students`) — paginated/filterable/sortable via `usePaginatedQuery`. Whitelist confirmed
 * against `modules/transport_ops/infra/repositories.py`'s `SqlAlchemyStudentRepository`:
 * filterable `status` only (no `organization_id` filter exists for this resource, unlike
 * `fleet_device`'s `Vehicle`/`Device`), sortable `full_name`/`status`, searchable `full_name`.
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap — every
 * `list_page` still applies an unrestricted `TenantRegionScope`), matching every other list
 * endpoint in this codebase. */
export async function listStudents(params: OffsetListParams): Promise<OffsetPage<StudentSummary>> {
  const wire = await apiRequest<OffsetPageWire<StudentSummaryWire>>(`/students?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toStudentSummary);
}

/** `GET /students/count` (RAAD business model realignment) — `transport_ops.students.count`,
 * held by founder/regional_manager/support_staff, distinct from `.list` (which those roles no
 * longer hold, migration `c4d9a2e6f813`). Backs the RAAD Platform's "Total students (count
 * only)" KPI tile without exposing individual student rows — `org_admin`'s own `StudentsPage`
 * still uses `listStudents` above; this is platform-only. */
export async function countStudents(): Promise<number> {
  const wire = await apiRequest<{ total: number }>("/students/count");
  return wire.total;
}

/** `GET /students/{id}` — the only route returning the full `Student` shape (`organizationId`,
 * `externalRef`, `createdAt`/`updatedAt`). `StudentsPage`'s detail drawer calls this on row
 * selection rather than reusing the list row alone — see `Student`'s own docstring. */
export async function getStudent(id: string): Promise<Student> {
  const wire = await apiRequest<StudentWire>(`/students/${id}`);
  return toStudent(wire);
}

export interface EnrollStudentInput {
  organizationId: string;
  fullName: string;
  externalRef?: string | null;
}

/** `POST /students` (`EnrollStudentRequest`, `transport_ops.api.schemas`) exactly:
 * `organization_id`, `full_name`, `external_ref`. Per the seeded RBAC matrix (`migrations/
 * versions/20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder`/
 * `org_admin` hold `transport_ops.students.create` — `StudentsPage`'s own `canManage` flag
 * mirrors this as a presentation hint only (`.claude/rules/frontend.md` #2). */
export async function enrollStudent(input: EnrollStudentInput): Promise<Student> {
  const wire = await apiRequest<StudentWire>("/students", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      full_name: input.fullName,
      external_ref: input.externalRef ?? null,
    },
  });
  return toStudent(wire);
}

/** `POST /students/{id}/status` (`UpdateStudentStatusRequest`, body `{status}`) — the single
 * behavioral route dispatching to `activate_student`/`disable_student`/`graduate_student`/
 * `transfer_student` (`routers.py`'s `update_student_status`). All four `StudentStatus` values
 * are valid targets (see this module's own `StudentStatus` docstring) — unlike `iam`'s
 * `UserStatus`, there is no restricted subset.
 *
 * `PATCH /students/{id}` (editing `full_name`/`external_ref` post-enrollment) also exists on the
 * backend but is deliberately not wired to any UI this phase — matching Organizations'/Users'
 * identical restraint of never building an "edit name" form even where a PATCH route accepts
 * one (`OrganizationsPage`/`UsersPage` only ever call their own status/mfa mutations, never a
 * details-edit mutation). Flagged here, not silently built. */
export async function updateStudentStatus(id: string, status: StudentStatus): Promise<Student> {
  const wire = await apiRequest<StudentWire>(`/students/${id}/status`, {
    method: "POST",
    body: { status },
  });
  return toStudent(wire);
}

/** `ParentForStudentResponse` (`transport_ops/api/schemas.py`) — one row of `GET /students/
 * {student_id}/parents` (Phase 10.7 — no documented API Contracts route, see backend
 * `routers.py`'s own module docstring). */
export interface GuardianLink {
  parentId: string;
  fullName: string;
  phone: string | null;
  status: string;
  relationship: string | null;
  isPrimary: boolean;
}

interface GuardianLinkWire {
  parent_id: string;
  full_name: string;
  phone: string | null;
  status: string;
  relationship: string | null;
  is_primary: boolean;
}

function toGuardianLink(wire: GuardianLinkWire): GuardianLink {
  return {
    parentId: wire.parent_id,
    fullName: wire.full_name,
    phone: wire.phone,
    status: wire.status,
    relationship: wire.relationship,
    isPrimary: wire.is_primary,
  };
}

/** `GET /students/{student_id}/parents` — a student's linked guardians, a raw JSON array
 * (`response_model=list[ParentForStudentResponse]`, never wrapped in an `OffsetPage` envelope —
 * this sub-resource is not paginated). Backs the "Guardians" section of the student detail
 * drawer. */
export async function listGuardiansForStudent(studentId: string): Promise<GuardianLink[]> {
  const wire = await apiRequest<GuardianLinkWire[]>(`/students/${studentId}/parents`);
  return wire.map(toGuardianLink);
}

export interface LinkGuardianInput {
  parentId: string;
  relationship?: string | null;
  isPrimary?: boolean;
}

/** `POST /students/{student_id}/parents` (`LinkParentToStudentRequest`) exactly: `parent_id`,
 * `relationship`, `is_primary`.
 *
 * **Two distinct failure shapes to surface, both real:** a duplicate link raises `ConflictError`
 * (409, `code: "CONFLICT"`, `application/validators.py`'s `ensure_link_not_duplicate`: "Parent
 * {parent_id} is already linked to student {student_id}"). A cross-organization link raises a
 * *raw* `DomainError` (`StudentParent.link`, `domain/entities.py`) — **not** wrapped in
 * `ConflictError`/`RuleViolationError`, so `core/errors/handlers.py`'s `_STATUS_TABLE` (which
 * only special-cases those two `DomainError` subclasses) falls through to the generic
 * `status_code >= 500` branch for it. This is a real backend quirk, not a frontend bug: the
 * envelope still carries the real `code: "DOMAIN_ERROR"` and the domain layer's own descriptive
 * message, just under HTTP 500 instead of a 4xx. `LinkGuardianForm.tsx` surfaces either verbatim
 * via a toast using `error.message` regardless of status code — the same handling every other
 * `ApiError` consumer in this codebase already applies, so no special-casing was needed. */
export async function linkGuardianToStudent(studentId: string, input: LinkGuardianInput): Promise<void> {
  await apiRequest(`/students/${studentId}/parents`, {
    method: "POST",
    body: {
      parent_id: input.parentId,
      relationship: input.relationship ?? null,
      is_primary: input.isPrimary ?? false,
    },
  });
}

/** `DELETE /students/{student_id}/parents/{parent_id}` — a 204 No Content (`apiRequest` returns
 * `undefined` for status 204, `shared/api/client.ts`). The first real `DELETE` in this bounded
 * context (`routers.py`'s module docstring: unlike `Student`/`Parent`'s deferred soft-delete,
 * removing a link is a genuine row deletion). */
export async function unlinkGuardianFromStudent(studentId: string, parentId: string): Promise<void> {
  await apiRequest<void>(`/students/${studentId}/parents/${parentId}`, { method: "DELETE" });
}

export interface ParentOption {
  id: string;
  fullName: string;
  status: string;
}

interface ParentOptionWire {
  id: string;
  full_name: string;
  status: string;
}

/** Minimal, read-only `GET /parents` lookup backing `LinkGuardianForm`'s parent picker.
 *
 * **Cannot pre-filter to the student's own organization — a real, flagged gap, not a silently
 * faked filter.** Unlike `fleet_device`'s `AssignDeviceForm`/`listVehiclesForPicker` (which
 * filters by `organization_id`, a real whitelisted `Vehicle` filter), `GET /parents`'s own
 * whitelist (`modules/transport_ops/infra/repositories.py`'s `SqlAlchemyParentRepository.
 * filterable_fields`) exposes only `status`, and `ParentSummaryResponse` carries no
 * `organization_id` field to filter by client-side either. This picker therefore lists every
 * active parent (up to 100, matching every other picker in this codebase's own 100-cap
 * convention — `listOrganizationsForPicker` below), relying entirely on the backend's own
 * `StudentParent.link` cross-organization rejection (surfaced via toast, see
 * `linkGuardianToStudent`'s docstring) to catch a wrong-org selection at submit time. */
export async function listParentsForPicker(search: string): Promise<ParentOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "full_name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<ParentOptionWire>>(`/parents?${query}`);
  return wire.data.map((parent) => ({ id: parent.id, fullName: parent.full_name, status: parent.status }));
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
 * shared/cross-imported helper (`.claude/rules/frontend.md` #1; no cross-feature-folder `api.ts`
 * import exists anywhere in this codebase). */
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
