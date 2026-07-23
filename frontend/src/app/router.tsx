import type { ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteGuard } from "./RouteGuard";
import { LoginPage } from "./LoginPage";
import { MobileOnlyPage } from "./MobileOnlyPage";
import { PlaceholderPage } from "./PlaceholderPage";
import { DashboardHomePage } from "./DashboardHomePage";
import { AppShell } from "./layout/AppShell";
import { platformNav, organizationNav, type NavItem } from "./layout/navConfig";
import { useAuthStore } from "../shared/stores/authStore";
import { getDashboardHomePath } from "../shared/auth/dashboard";
import type { Role } from "../shared/api/types";
import { OrganizationsPage } from "../features/organizations/OrganizationsPage";
import { UsersPage } from "../features/admin/users/UsersPage";
import { VehiclesPage } from "../features/fleet-devices/vehicles/VehiclesPage";
import { DevicesPage } from "../features/fleet-devices/devices/DevicesPage";
import { StudentsPage } from "../features/transport-ops/students/StudentsPage";
import { ParentsPage } from "../features/transport-ops/parents/ParentsPage";
import { DriversPage } from "../features/transport-ops/drivers/DriversPage";
import { RoutesPage } from "../features/transport-ops/routes/RoutesPage";

const PLATFORM_ROLES: Role[] = ["founder", "regional_manager", "support_staff", "finance_staff"];
const ORGANIZATION_ROLES: Role[] = ["org_admin"];

/** `/` itself is never a page — it sends an authenticated user to their own dashboard's home
 * ("automatically redirect users to the correct dashboard according to their assigned role"),
 * or to `/login` when signed out. */
function RootRedirect() {
  const principal = useAuthStore((s) => s.principal);
  if (!principal) {
    return <Navigate to="/login" replace />;
  }
  return <Navigate to={getDashboardHomePath(principal.role)} replace />;
}

/** Every non-header nav item becomes a real route — the built dashboard page where one exists
 * (looked up by full path in `built`), `PlaceholderPage` everywhere else (see that component's
 * own docstring). */
function buildFeatureRoutes(
  nav: NavItem[],
  dashboardHomePath: string,
  built: Record<string, ReactNode> = {},
) {
  return nav
    .filter((item): item is Extract<NavItem, { type: "link" }> => item.type === "link")
    .filter((item) => item.path !== dashboardHomePath)
    .map((item) => ({
      path: item.path.slice(dashboardHomePath.length + 1),
      element: built[item.path] ?? <PlaceholderPage title={item.label} />,
    }));
}

/** Phase F1 (Organization & Region Management) graduated `/platform/organizations` out of
 * `PlaceholderPage`; Phase F2 (User & Access Management) now does the same for
 * `/platform/users` (`navConfig.ts`'s "Users & Roles" entry). Org Admin never sees either route:
 * `organizationNav` has no Organizations entry at all, and its own separate `/org/users` entry
 * stays a `PlaceholderPage` this phase (`UsersPage.tsx`'s own docstring explains why — only
 * `founder`/`regional_manager`/`support_staff` currently hold any `iam.users.*` permission at
 * all, and `org_admin` holds none of them).
 *
 * Phase F3 (Fleet & Device Management) graduates `/platform/vehicles`/`/platform/devices` here
 * too — but unlike Organizations/Users, Fleet & Device is managed from **both** dashboards
 * (`.claude/rules/api.md` #2's `/vehicles`+`/devices` map to the one `fleet_device` bounded
 * context regardless of which dashboard reaches them), so `ORGANIZATION_BUILT_ROUTES` below
 * mounts the *same* `VehiclesPage`/`DevicesPage` components at their `/org/*` nav entries —
 * exactly one shared page component per entity, not a duplicate built per dashboard, mirroring
 * how `fleet_device.api.routers` itself exposes one `GET/POST /vehicles`+`/devices` surface
 * regardless of caller, gated only by `require_permission`.
 *
 * Phase F4 (Transport Operations, Part A — Students/Parents/Linking) graduates
 * `/platform/students`+`/platform/parents` the same way: one `StudentsPage`/`ParentsPage`
 * component reused at both `/platform/*` and `/org/*` (`ORGANIZATION_BUILT_ROUTES` below), since
 * `GET/POST /students`+`/parents` (API Contracts §4.3) are likewise a single surface gated only
 * by `require_permission`, not a platform-vs-org-specific route.
 *
 * Phase F5 (Transport Operations, Part B — Drivers/Routes & Stops) does the same for
 * `/platform/drivers`+`/platform/routes`: one `DriversPage`/`RoutesPage` component reused at
 * both `/platform/*` and `/org/*`. `transport_ops`'s remaining two aggregates (`Trip`/
 * `StudentAssignment`) stay `PlaceholderPage` until F6 lands (the master roadmap's deliberate
 * per-aggregate split of this bounded context). */
const PLATFORM_BUILT_ROUTES: Record<string, ReactNode> = {
  "/platform/organizations": <OrganizationsPage />,
  "/platform/users": <UsersPage />,
  "/platform/vehicles": <VehiclesPage />,
  "/platform/devices": <DevicesPage />,
  "/platform/students": <StudentsPage />,
  "/platform/parents": <ParentsPage />,
  "/platform/drivers": <DriversPage />,
  "/platform/routes": <RoutesPage />,
};

/** Org Admin's own dashboard equivalent of the Fleet & Device / Transport Ops entries above —
 * see this file's own note on why these are the same page components, not separate ones. Every
 * other `organizationNav` entry (Trips, …) stays a `PlaceholderPage` until its own phase lands. */
const ORGANIZATION_BUILT_ROUTES: Record<string, ReactNode> = {
  "/org/vehicles": <VehiclesPage />,
  "/org/devices": <DevicesPage />,
  "/org/students": <StudentsPage />,
  "/org/parents": <ParentsPage />,
  "/org/drivers": <DriversPage />,
  "/org/routes": <RoutesPage />,
};

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/mobile-only",
    element: (
      <RouteGuard>
        <MobileOnlyPage />
      </RouteGuard>
    ),
  },
  {
    path: "/platform",
    element: (
      <RouteGuard allowedRoles={PLATFORM_ROLES}>
        <AppShell nav={platformNav} notificationsPath="/platform/notifications" />
      </RouteGuard>
    ),
    children: [
      { index: true, element: <DashboardHomePage /> },
      ...buildFeatureRoutes(platformNav, "/platform", PLATFORM_BUILT_ROUTES),
    ],
  },
  {
    path: "/org",
    element: (
      <RouteGuard allowedRoles={ORGANIZATION_ROLES}>
        <AppShell nav={organizationNav} notificationsPath="/org/notifications" />
      </RouteGuard>
    ),
    children: [
      { index: true, element: <DashboardHomePage /> },
      ...buildFeatureRoutes(organizationNav, "/org", ORGANIZATION_BUILT_ROUTES),
    ],
  },
  { path: "/", element: <RootRedirect /> },
  { path: "*", element: <RootRedirect /> },
]);
