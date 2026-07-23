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

/** Phase F1 (Organization & Region Management) — the first nav destination to graduate out of
 * `PlaceholderPage`. Org Admin never sees this: `organizationNav` has no Organizations entry at
 * all (organizations are managed from the platform dashboard, not the org one), so only the
 * platform tree needs an override. */
const PLATFORM_BUILT_ROUTES: Record<string, ReactNode> = {
  "/platform/organizations": <OrganizationsPage />,
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
      ...buildFeatureRoutes(organizationNav, "/org"),
    ],
  },
  { path: "/", element: <RootRedirect /> },
  { path: "*", element: <RootRedirect /> },
]);
