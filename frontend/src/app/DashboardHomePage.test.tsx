import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../shared/stores/authStore";
import { DashboardHomePage } from "./DashboardHomePage";
import type { PlatformStats } from "../features/platform-analytics/api";

vi.mock("../features/transport-ops/drivers/api", () => ({ listDrivers: vi.fn() }));
vi.mock("../features/transport-ops/students/api", () => ({ countStudents: vi.fn() }));
vi.mock("../features/transport-ops/parents/api", () => ({ countParents: vi.fn() }));
vi.mock("../features/platform-analytics/api", () => ({ getPlatformStats: vi.fn() }));

import { listDrivers } from "../features/transport-ops/drivers/api";
import { countStudents } from "../features/transport-ops/students/api";
import { countParents } from "../features/transport-ops/parents/api";
import { getPlatformStats } from "../features/platform-analytics/api";

function pageOf(total: number) {
  return { data: [], page: { total, page: 1, pageSize: 1 } };
}

const SAMPLE_PLATFORM_STATS: PlatformStats = {
  organizations: { total: 3, byStatus: { active: 2, suspended: 1 }, createdToday: 1 },
  vehicles: { total: 8 },
  devices: { total: 5, online: 4, offline: 1 },
  users: { total: 20, byStatus: { active: 18, invited: 2 }, monthlyActive: 12, createdToday: 2 },
  billing: { subscriptionByStatus: { active: 3 }, expiringSoon: 1, revenue: 4500 },
  systemHealth: { database: "ok", broker: "down" },
};

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardHomePage />
    </QueryClientProvider>,
  );
}

describe("DashboardHomePage", () => {
  beforeEach(() => {
    vi.mocked(listDrivers).mockReset().mockResolvedValue(pageOf(0));
    vi.mocked(countStudents).mockReset().mockResolvedValue(0);
    vi.mocked(countParents).mockReset().mockResolvedValue(0);
    vi.mocked(getPlatformStats).mockReset().mockResolvedValue(SAMPLE_PLATFORM_STATS);
  });

  it("shows the ADR-0020 platform analytics grid with real data for a platform role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    expect(await screen.findByText("Organizations")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("Devices")).toBeInTheDocument();
    expect(screen.getByText("2 active · 1 new today")).toBeInTheDocument();
    expect(getPlatformStats).toHaveBeenCalled();
  });

  it("still shows the drivers/students/parents strip alongside the new grid", async () => {
    vi.mocked(listDrivers).mockResolvedValue(pageOf(7));
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    expect(await screen.findByText("Total drivers")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("7")).toBeInTheDocument());
  });

  it("shows a dash instead of crashing when the drivers stat query fails", async () => {
    vi.mocked(listDrivers).mockReset().mockRejectedValue(new Error("network down"));
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    await screen.findByText("Total drivers");
    await waitFor(() => expect(screen.getAllByText("—").length).toBeGreaterThan(0));
  });

  it("shows a visible error (not a silent blank) when the analytics grid fails to load", async () => {
    vi.mocked(getPlatformStats).mockReset().mockRejectedValue(new Error("network down"));
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    // The unrelated drivers/students/parents strip still renders normally.
    expect(await screen.findByText("Total drivers")).toBeInTheDocument();
    expect(await screen.findByText("Could not load platform analytics")).toBeInTheDocument();
    expect(screen.queryByText("Organizations")).not.toBeInTheDocument();
  });

  it("hides both platform KPI sections entirely for an Org Admin", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
      status: "authenticated",
    });

    renderDashboard();

    expect(await screen.findByText(/Welcome/)).toBeInTheDocument();
    expect(screen.queryByText("Organizations")).not.toBeInTheDocument();
    expect(screen.queryByText("Total drivers")).not.toBeInTheDocument();
    expect(getPlatformStats).not.toHaveBeenCalled();
    expect(listDrivers).not.toHaveBeenCalled();
  });
});
