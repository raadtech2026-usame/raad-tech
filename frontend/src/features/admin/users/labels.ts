import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { Role } from "../../../shared/api/types";
import type { UserStatus } from "./api";

/** Display copy for `iam` enums — kept in one place so the list table, the detail drawer, and
 * the create form all render the exact same wording, mirroring
 * `features/organizations/labels.ts`'s own convention.
 *
 * Role *label* text is deliberately not re-defined here: `shared/auth/roleDisplay.ts`'s
 * `getRoleDisplay(role).label` (already used by `TopBar`/`DashboardHomePage` for the exact same
 * seven `Role` values) is the one existing source for that copy — duplicating it here would
 * risk the two drifting apart. Only the `Badge`-tone mapping below is new, since `RoleDisplay`
 * carries a raw hex `color` (for `Avatar`), not a semantic `BadgeVariant`.
 */

/** RAAD-staff roles (founder/regional_manager/support_staff/finance_staff) get one family of
 * tones, org-scoped roles (org_admin/driver/parent) another — a purely visual grouping, no
 * business meaning beyond making the two categories `User._validate_identity_and_scope`
 * actually enforces (`iam.domain.entities.py`) easy to tell apart at a glance. */
export function roleTone(role: Role): BadgeVariant {
  switch (role) {
    case "founder":
      return "purple";
    case "regional_manager":
    case "support_staff":
      return "info";
    case "finance_staff":
      return "info";
    case "org_admin":
      return "success";
    case "driver":
      return "warning";
    case "parent":
      return "neutral";
    default:
      return "neutral";
  }
}

/** No `trial`/`suspended`/etc. — only the three real `UserStatus` values
 * (`iam.domain.value_objects.UserStatus`) are ever rendered here. */
export function statusLabel(status: UserStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "disabled":
      return "Disabled";
    case "invited":
      return "Invited";
    default:
      return status;
  }
}

export function statusTone(status: UserStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "disabled":
      return "danger";
    case "invited":
      return "warning";
    default:
      return "neutral";
  }
}

/** Up to two initials for the list/detail `Avatar`, e.g. "Alice Brown" -> "AB", a single-word
 * name -> its first letter. `full_name` is a required, non-empty field on every `User`
 * (`iam.domain.entities.User.__init__`'s `full_name: str`), so this always has something to
 * work with. */
export function avatarInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}
