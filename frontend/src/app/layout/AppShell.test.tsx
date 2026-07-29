import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../shared/stores/authStore";
import { RouteGuard } from "../RouteGuard";
import { DashboardHomePage } from "../DashboardHomePage";
import { AppShell } from "./AppShell";
import { platformNav } from "./navConfig";

// `DashboardHomePage`'s platform KPI strip fetches from every one of these — irrelevant to
// this file's own regression concern (the PageHeaderContext render loop), so mocked to an
// unresolved promise: never resolves within this test, so no assertion here depends on it.
vi.mock("../../features/organizations/api", () => ({ listOrganizations: vi.fn(() => new Promise(() => {})) }));
vi.mock("../../features/fleet-devices/vehicles/api", () => ({ listVehicles: vi.fn(() => new Promise(() => {})) }));
vi.mock("../../features/fleet-devices/devices/api", () => ({ listDevices: vi.fn(() => new Promise(() => {})) }));
vi.mock("../../features/transport-ops/drivers/api", () => ({ listDrivers: vi.fn(() => new Promise(() => {})) }));
vi.mock("../../features/transport-ops/students/api", () => ({ countStudents: vi.fn(() => new Promise(() => {})) }));
vi.mock("../../features/transport-ops/parents/api", () => ({ countParents: vi.fn(() => new Promise(() => {})) }));

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/platform"]}>
        <Routes>
          <Route path="/login" element={<div>Login page</div>} />
          <Route
            path="/platform"
            element={
              <RouteGuard allowedRoles={["founder"]}>
                <AppShell nav={platformNav} notificationsPath="/platform/notifications" />
              </RouteGuard>
            }
          >
            <Route index element={<DashboardHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
  });

  /** Regression test for the post-login crash: `useCurrentPageHeader` (`PageHeaderContext.tsx`,
   * consumed only here in `AppShell`) previously selected a freshly-allocated `{ title,
   * subtitle }` object literal on every call. Zustand's `useStore` (built on
   * `useSyncExternalStore`) compares each selector's return value via `Object.is`, so a
   * selector that never returns a stable reference is treated as "changed" on every render
   * check — an infinite `AppShell` render loop ("Maximum update depth exceeded" / "The result
   * of getSnapshot should be cached to avoid an infinite loop") the very first time a real
   * login reached `/platform` (`DashboardHomePage`'s own `usePageHeader` call is what first
   * populates the store `AppShell` then reads back). `render()` itself throws if React aborts
   * with that error, so simply completing this render — and seeing the real dashboard content
   * past `RouteGuard` and `AppShell` — is the proof the loop is gone. */
  it("renders the dashboard home page after login without an infinite PageHeaderContext render loop", () => {
    renderDashboard();

    expect(screen.getByText(/Welcome, Founder/)).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});
