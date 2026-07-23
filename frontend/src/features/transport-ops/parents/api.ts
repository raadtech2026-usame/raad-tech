import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.ParentStatus` (Database Design §6.3 gives `parents.status`
 * with no enumerated values at all, unlike §6.2's fully-spelled-out `students.status ENUM(...)` —
 * `value_objects.py`'s own docstring: "flagged, not guessed"). A flat active/inactive toggle,
 * mirroring `organization.domain.value_objects.RegionStatus`'s identical situation. Both values
 * transport via `PATCH /parents/{id}`'s `status` field, folded in alongside `full_name`/`phone`
 * since no dedicated behavioral status sub-route is documented for `/parents` (unlike
 * `/students/{id}/status`). */
export type ParentStatus = "active" | "inactive";

/** Full `ParentResponse` shape (`transport_ops.api.schemas`) — returned by `GET /parents/{id}`
 * only. See `ParentSummary` below for why `GET /parents` (the list route) cannot return this
 * shape. */
export interface Parent {
  id: string;
  organizationId: string;
  userId: string;
  fullName: string;
  phone: string | null;
  status: ParentStatus;
  createdAt: string;
  updatedAt: string;
}

/** `ParentSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /parents`
 * returns (`routers.py`'s `list_parents`,
 * `response_model=OffsetPageResponse[ParentSummaryResponse]`). Deliberately thin: no
 * `organization_id`, no `user_id`, no `phone`, no `created_at`/`updated_at` — see
 * `features/transport-ops/students/api.ts`'s `StudentSummary` docstring for the identical, real
 * `transport_ops`-wide reasoning. */
export interface ParentSummary {
  id: string;
  fullName: string;
  status: ParentStatus;
}

/** Wire shape of `ParentResponse` — snake_case, exactly as the backend serializes it. */
interface ParentWire {
  id: string;
  organization_id: string;
  user_id: string;
  full_name: string;
  phone: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Wire shape of `ParentSummaryResponse`. */
interface ParentSummaryWire {
  id: string;
  full_name: string;
  status: string;
}

function toParent(wire: ParentWire): Parent {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    userId: wire.user_id,
    fullName: wire.full_name,
    phone: wire.phone,
    status: wire.status as ParentStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

function toParentSummary(wire: ParentSummaryWire): ParentSummary {
  return { id: wire.id, fullName: wire.full_name, status: wire.status as ParentStatus };
}

/** `GET /parents` (API Contracts §4.3's `/parents` row; `transport_ops.api.routers.list_parents`)
 * — paginated/filterable/sortable via `usePaginatedQuery`. Whitelist confirmed against
 * `modules/transport_ops/infra/repositories.py`'s `SqlAlchemyParentRepository`: filterable
 * `status` only (no `organization_id`/`user_id` filter exists for this resource), sortable
 * `full_name`/`status`, searchable `full_name`. Not yet scope-filtered server-side (CLAUDE.md's
 * own flagged, system-wide gap), matching every other list endpoint in this codebase. */
export async function listParents(params: OffsetListParams): Promise<OffsetPage<ParentSummary>> {
  const wire = await apiRequest<OffsetPageWire<ParentSummaryWire>>(`/parents?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toParentSummary);
}

/** `GET /parents/{id}` — the only route returning the full `Parent` shape (`organizationId`,
 * `userId`, `phone`, `createdAt`/`updatedAt`). `ParentsPage`'s detail drawer calls this on row
 * selection rather than reusing the list row alone — see `Parent`'s own docstring. */
export async function getParent(id: string): Promise<Parent> {
  const wire = await apiRequest<ParentWire>(`/parents/${id}`);
  return toParent(wire);
}

export interface RegisterParentInput {
  organizationId: string;
  userId: string;
  fullName: string;
  phone?: string | null;
}

/** `POST /parents` (`RegisterParentRequest`, `transport_ops.api.schemas`) exactly:
 * `organization_id`, `user_id`, `full_name`, `phone`. `user_id` links this transport-facing
 * profile to an *existing* `iam.User` login (Database Design §6.3: "Login is via the linked
 * `users` row") — this form does not create a `User`, only references one that must already
 * exist (typically invited with `role: "parent"` via Users & Roles first). Per the seeded RBAC
 * matrix, only `founder`/`org_admin` hold `transport_ops.parents.create` —
 * `ParentsPage`/`CreateParentForm`'s own `canManage` flag mirrors this. See
 * `CreateParentForm.tsx`'s own docstring for a real RBAC gap this input surfaced: `org_admin`
 * holds no `iam.users.*` permission at all, so it cannot browse `GET /users` to find a
 * `user_id` the way `founder` can. */
export async function registerParent(input: RegisterParentInput): Promise<Parent> {
  const wire = await apiRequest<ParentWire>("/parents", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      user_id: input.userId,
      full_name: input.fullName,
      phone: input.phone ?? null,
    },
  });
  return toParent(wire);
}

/** `PATCH /parents/{id}` sending only `status` — dispatches to `activate_parent`/
 * `disable_parent` (`routers.py`'s `update_parent`), leaving `full_name`/`phone` untouched since
 * both are omitted from the request body (the router only processes fields that are actually
 * present). Mirrors `updateOrganizationStatus`'s identical status-only-PATCH shape.
 * `full_name`/`phone` editing is not wired to any UI this phase — the same restraint
 * `features/transport-ops/students/api.ts`'s `updateStudentStatus` docstring documents for
 * `Student`. */
export async function updateParentStatus(id: string, status: ParentStatus): Promise<Parent> {
  const wire = await apiRequest<ParentWire>(`/parents/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toParent(wire);
}

/** `StudentForParentResponse` (`transport_ops/api/schemas.py`) — one row of `GET /parents/
 * {parent_id}/students`. */
export interface LinkedStudent {
  studentId: string;
  fullName: string;
  status: string;
  relationship: string | null;
  isPrimary: boolean;
}

interface LinkedStudentWire {
  student_id: string;
  full_name: string;
  status: string;
  relationship: string | null;
  is_primary: boolean;
}

function toLinkedStudent(wire: LinkedStudentWire): LinkedStudent {
  return {
    studentId: wire.student_id,
    fullName: wire.full_name,
    status: wire.status,
    relationship: wire.relationship,
    isPrimary: wire.is_primary,
  };
}

/** `GET /parents/{parent_id}/students` — a parent's linked students, a raw JSON array
 * (`response_model=list[StudentForParentResponse]`, not paginated). Backs the "Linked students"
 * section of the parent detail drawer — the mirror image of `features/transport-ops/students/
 * api.ts`'s `listGuardiansForStudent`, satisfying the roadmap's "see the link reflected on both
 * the student's and parent's detail views" exit criterion. */
export async function listStudentsForParent(parentId: string): Promise<LinkedStudent[]> {
  const wire = await apiRequest<LinkedStudentWire[]>(`/parents/${parentId}/students`);
  return wire.map(toLinkedStudent);
}

/** `DELETE /students/{student_id}/parents/{parent_id}` — the identical unlink route
 * `features/transport-ops/students/api.ts`'s `unlinkGuardianFromStudent` calls, duplicated here
 * with the parameter order the parent detail drawer naturally has on hand (`parentId` first)
 * rather than importing across entity folders — the same "duplicate a small amount rather than
 * couple two otherwise-independent components" precedent `FormDrawer.tsx`'s own docstring
 * establishes, applied to two sibling entity `api.ts` modules under one bounded context exactly
 * like `fleet-devices/vehicles`+`devices` already do for their own duplicated picker reads. Link
 * *creation* is only ever initiated from the Student side (`LinkGuardianForm.tsx`) — this
 * drawer's own "Linked students" list is read-only plus unlink, not a second, divergent
 * "add student" flow for the identical operation. */
export async function unlinkStudentFromParent(parentId: string, studentId: string): Promise<void> {
  await apiRequest<void>(`/students/${studentId}/parents/${parentId}`, { method: "DELETE" });
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
 * identical function for why this is deliberately its own self-contained copy. */
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

/** Minimal, read-only `GET /users` lookup backing `CreateParentForm`'s "linked user" picker —
 * filtered to the target organization and `role=parent`/`status=active`. A cross-bounded-context
 * read (`iam`, not `transport_ops`) — the same precedent `admin/users/api.ts`'s own
 * `listOrganizationsForPicker` and every `fleet-devices` picker already establish for an
 * unavoidable "pick an existing X" read. Whitelist confirmed against `modules/iam/infra/
 * repositories.py`'s `SqlAlchemyUserRepository`: filterable `organization_id`/`role`/`status`.
 *
 * **Only reachable for a principal holding `iam.users.read`** — per the seeded RBAC matrix, that
 * is `founder` only among the roles that also hold `transport_ops.parents.create` (`org_admin`
 * holds no `iam.users.*` permission at all). `CreateParentForm.tsx` therefore only calls this for
 * `founder`; see that component's own docstring for the real gap this surfaced and how `org_admin`
 * supplies a `user_id` instead. */
export async function listParentUsersForPicker(organizationId: string, search: string): Promise<UserOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "full_name", direction: "asc" },
    filters: { organization_id: organizationId, role: "parent", status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<UserOptionWire>>(`/users?${query}`);
  return wire.data.map((user) => ({ id: user.id, fullName: user.full_name, email: user.email, phone: user.phone }));
}
