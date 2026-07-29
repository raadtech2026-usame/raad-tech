import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire, type Role } from "../../../shared/api/types";

/** `iam.domain.value_objects.UserStatus` (Database Design §4.3's
 * `status ENUM(active,disabled,invited)`). */
export type UserStatus = "active" | "disabled" | "invited";

/** Every `core.tenancy.principal.Role` value is assignable from `POST /users`
 * (`modules/iam/application/services.py`'s `invite_user` / `User.invite` enforce no
 * role-specific restriction on *who may be assigned which role* — only the org-scope
 * invariant below). Authorization is a single, flat permission check
 * (`require_permission(Permission("iam.users.create"))`, `modules/iam/api/routers.py`), not a
 * per-role rule — confirmed by reading `User._validate_identity_and_scope`
 * (`modules/iam/domain/entities.py`), which never compares the actor's own role to the target
 * role at all. Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder` currently
 * holds `iam.users.create`/`iam.users.update` in this environment — `regional_manager`/
 * `support_staff` hold `iam.users.read` only (list/view, no invite/edit), and
 * `finance_staff`/`org_admin`/`driver`/`parent` hold none of the three. This module doesn't
 * hardcode that distribution (it's operator-editable, seedable data, not a frontend constant)
 * — it only uses `principal.role === "founder"` as a presentation-layer hint for which actions
 * to show, matching `.claude/rules/frontend.md` #2 ("presentation of server-enforced scope,
 * not a second authorization system"); the backend's own `require_permission` remains the real
 * gate regardless of what this hint shows or hides. */
export const ASSIGNABLE_ROLES: Role[] = [
  "founder",
  "regional_manager",
  "support_staff",
  "finance_staff",
  "org_admin",
  "driver",
  "parent",
];

/** `iam.domain.entities._ORG_SCOPED_ROLES` verbatim — `organization_id` is *required* for these
 * three roles and *must be absent* for every other role (`User._validate_identity_and_scope`).
 * The create-user form uses this to decide whether the organization picker applies at all. */
const ORG_SCOPED_ROLES: ReadonlySet<Role> = new Set(["org_admin", "driver", "parent"]);

export function isOrgScopedRole(role: Role): boolean {
  return ORG_SCOPED_ROLES.has(role);
}

export interface User {
  id: string;
  organizationId: string | null;
  role: Role;
  email: string | null;
  phone: string | null;
  fullName: string;
  status: UserStatus;
  createdAt: string;
  updatedAt: string;
  mfaEnabled: boolean;
  lastLoginAt: string | null;
}

/** Wire shape of `iam.api.schemas.UserResponse` — snake_case, exactly as the backend serializes
 * it. `role` travels lower-case snake_case (that schema module's own docstring: "matching
 * `core.tenancy.principal.Role`'s upper-case values case-folded"), which is exactly this app's
 * existing `Role` type (`shared/api/types.ts`) — reused verbatim, never redefined. */
interface UserWire {
  id: string;
  organization_id: string | null;
  role: string;
  email: string | null;
  phone: string | null;
  full_name: string;
  status: string;
  created_at: string;
  updated_at: string;
  mfa_enabled: boolean;
  last_login_at: string | null;
}

function toUser(wire: UserWire): User {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    role: wire.role as Role,
    email: wire.email,
    phone: wire.phone,
    fullName: wire.full_name,
    status: wire.status as UserStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    mfaEnabled: wire.mfa_enabled,
    lastLoginAt: wire.last_login_at,
  };
}

/** `GET /users` (API Contracts §4.1, "in-scope admin... role-restricted creation") — paginated/
 * filterable/sortable via `usePaginatedQuery`. Whitelist confirmed against
 * `modules/iam/infra/repositories.py`'s `SqlAlchemyUserRepository`: filterable
 * `organization_id`/`role`/`status`, sortable `full_name`/`status`/`created_at`/`updated_at`,
 * searchable `full_name`/`email`. Not yet scope-filtered server-side (CLAUDE.md's own flagged,
 * system-wide gap: every `list_page` still applies an unrestricted `TenantRegionScope`) — every
 * viewer who can reach this route currently sees every user, not just their own org/region. */
export async function listUsers(params: OffsetListParams): Promise<OffsetPage<User>> {
  const wire = await apiRequest<OffsetPageWire<UserWire>>(`/users?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toUser);
}

export async function getUser(id: string): Promise<User> {
  const wire = await apiRequest<UserWire>(`/users/${id}`);
  return toUser(wire);
}

export interface InviteUserInput {
  fullName: string;
  role: Role;
  email?: string | null;
  phone?: string | null;
  /** Required for `org_admin`/`driver`/`parent`, must be omitted/`null` for every other role
   * (`User._validate_identity_and_scope` — a `DomainError` surfaces as a 422 otherwise). */
  organizationId?: string | null;
}

/** `POST /users` (`CreateUserRequest`, `modules/iam/api/schemas.py`) exactly: `organization_id`,
 * `role`, `email`, `phone`, `full_name`. The backend enforces "at least one of email/phone"
 * (`User._validate_identity_and_scope`) — this module doesn't duplicate that as a hardcoded
 * client rule beyond form validation (see `InviteUserForm.tsx`'s zod schema), since the
 * server's `DomainError` is the actual source of truth. */
export async function inviteUser(input: InviteUserInput): Promise<User> {
  const wire = await apiRequest<UserWire>("/users", {
    method: "POST",
    body: {
      organization_id: input.organizationId ?? null,
      role: input.role,
      email: input.email ?? null,
      phone: input.phone ?? null,
      full_name: input.fullName,
    },
  });
  return toUser(wire);
}

/** `PATCH /users/{id}` with only `status` set (`UpdateUserRequest`) — mapped server-side to
 * `activate_user`/`disable_user` (`modules/iam/api/routers.py`'s `update_user`). Those are the
 * *only* two status values `UpdateUserRequest` accepts (`"active"`/`"disabled"`) — there is no
 * "revert to invited" transition, matching the backend's own `User` aggregate (`invite()` is a
 * one-way factory, never a status target `activate`/`disable` can restore). */
export async function updateUserStatus(
  id: string,
  status: Extract<UserStatus, "active" | "disabled">,
): Promise<User> {
  const wire = await apiRequest<UserWire>(`/users/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toUser(wire);
}

/** `PATCH /users/{id}` with only `mfa_enabled` set — mapped server-side to `enable_mfa`/
 * `disable_mfa`. Composed independently from `updateUserStatus` above (two separate mutations,
 * two separate commits server-side per `update_user`'s own docstring: "not atomic"), matching
 * Organizations' one-button-per-transition convention applied to this aggregate's second,
 * independent transition axis. */
export async function updateUserMfa(id: string, mfaEnabled: boolean): Promise<User> {
  const wire = await apiRequest<UserWire>(`/users/${id}`, {
    method: "PATCH",
    body: { mfa_enabled: mfaEnabled },
  });
  return toUser(wire);
}

interface PasswordResetWire {
  user: UserWire;
  temporary_password: string;
}

export interface PasswordResetResult {
  user: User;
  /** Surfaced exactly once, in this response — never retrievable again via any other endpoint,
   * the same one-time-hand-off guarantee `OnboardedOrganization.temporaryPassword`
   * (`features/organizations/api.ts`) already establishes for initial onboarding. */
  temporaryPassword: string;
}

/** `POST /users/{id}/reset-password` (ADR-0017 Amendment) — administrator-initiated
 * regeneration for a user who lost their temporary (or only) password. Immediately invalidates
 * whatever password they had and revokes every refresh token already issued to them
 * (`UserApplicationService.reset_password_to_temporary`, backend-enforced, not this call's own
 * responsibility). No request body: the new password is generated server-side. */
export async function resetUserPassword(id: string): Promise<PasswordResetResult> {
  const wire = await apiRequest<PasswordResetWire>(`/users/${id}/reset-password`, {
    method: "POST",
  });
  return { user: toUser(wire.user), temporaryPassword: wire.temporary_password };
}

export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup backing the create-user form's organization
 * picker (shown only for `org_admin`/`driver`/`parent` — see `isOrgScopedRole` above) and the
 * list/detail views' organization-name display. Deliberately self-contained rather than
 * importing `features/organizations/api.ts`'s `listOrganizations`: Phase F1 established no
 * cross-feature-folder import precedent anywhere in this codebase (only `app/router.tsx`
 * imports a feature's *page component*, never one feature importing another's `api.ts`), and
 * `.claude/rules/frontend.md` #1 mirrors backend bounded contexts onto feature folders — `iam`
 * (this module) and `organization` are two different bounded contexts
 * (`.claude/rules/architecture.md` #6), so this follows the same "own minimal read, don't reach
 * into a sibling module" discipline `features/organizations/api.ts`'s own `listRegions` already
 * established for *its* one unavoidable cross-context read. */
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
