import type { Role } from "../api/types";

/**
 * RAAD ships two distinct dashboards, not one app with a role switcher:
 *
 * - `platform` — Founder, Regional Manager, Support Staff, Finance Staff. Manages the whole
 *   RAAD platform across every organization (tenant provisioning included). Scoped server-side
 *   by RBAC + `ScopeResolver` (Founder = all, Regional Manager = assigned regions, Support =
 *   assigned orgs, Finance = billing scope only — `.claude/rules/security.md` #3).
 * - `organization` — Org Admin only. Organizations are *created from* the platform dashboard
 *   (provision org, create the Org Admin, assign credentials); the Org Admin then signs into
 *   this dashboard, which shows only their own organization's data (`organization_id` scoping,
 *   enforced server-side — this constant only decides which shell/nav renders, never access).
 * - `unsupported` — Driver and Parent have no web dashboard at all. Both are mobile-only roles
 *   (`.claude/rules/flutter.md` #1, Project Brief §4.7/§4.8) — if one of these roles reaches the
 *   web login, the correct behavior is a clear "use the RAAD mobile app" message, not a broken
 *   or empty dashboard shell.
 */
export type DashboardType = "platform" | "organization" | "unsupported";

const DASHBOARD_BY_ROLE: Record<Role, DashboardType> = {
  founder: "platform",
  regional_manager: "platform",
  support_staff: "platform",
  finance_staff: "platform",
  org_admin: "organization",
  driver: "unsupported",
  parent: "unsupported",
};

export function getDashboardType(role: Role): DashboardType {
  return DASHBOARD_BY_ROLE[role];
}

/** Where a freshly authenticated user should land — the "redirect to the correct dashboard"
 * behavior. Both dashboard roots redirect further to their own default page. */
export function getDashboardHomePath(role: Role): string {
  switch (getDashboardType(role)) {
    case "platform":
      return "/platform";
    case "organization":
      return "/org";
    case "unsupported":
      return "/mobile-only";
  }
}
