import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../shared/stores/authStore";
import { DashboardHomePage } from "./DashboardHomePage";

vi.mock("../features/organizations/api", () => ({ listOrganizations: vi.fn() }));
vi.mock("../features/fleet-devices/vehicles/api", () => ({ listVehicles: vi.fn() }));
vi.mock("../features/fleet-devices/devices/api", () => ({ listDevices: vi.fn() }));
vi.mock("../features/transport-ops/drivers/api", () => ({ listDrivers: vi.fn() }));
vi.mock("../features/transport-ops/students/api", () => ({ countStudents: vi.fn() }));
vi.mock("../features/transport-ops/parents/api", () => ({ countParents: vi.fn() }));

import { listOrganizations } from "../features/organizations/api";
import { listVehicles } from "../features/fleet-devices/vehicles/api";
import { listDevices } from "../features/fleet-devices/devices/api";
import { listDrivers } from "../features/transport-ops/drivers/api";
import { countStudents } from "../features/transport-ops/students/api";
import { countParents } from "../features/transport-ops/parents/api";

function pageOf(total: number) {
  return { data: [], page: { total, page: 1, pageSize: 1 } };
}

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
    vi.mocked(listOrganizations).mockReset().mockResolvedValue(pageOf(3));
    vi.mocked(listVehicles).mockReset().mockResolvedValue(pageOf(2));
    vi.mocked(listDevices).mockReset().mockResolvedValue(pageOf(1));
    vi.mocked(listDrivers).mockReset().mockResolvedValue(pageOf(0));
    vi.mocked(countStudents).mockReset().mockResolvedValue(0);
    vi.mocked(countParents).mockReset().mockResolvedValue(0);
  });

  it("shows the platform KPI strip with real counts for a platform role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    expect(await screen.findByText("Total organizations")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(listOrganizations).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 1 }),
    );
  });

  it("shows a dash instead of crashing when a stat query fails", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(listDevices).mockReset().mockRejectedValue(new Error("network down"));

    renderDashboard();

    await screen.findByText("Total devices");
    await waitFor(() => expect(screen.getAllByText("—").length).toBeGreaterThan(0));
  });

  it("hides the platform KPI strip entirely for an Org Admin", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
      status: "authenticated",
    });

    renderDashboard();

    expect(await screen.findByText(/Welcome/)).toBeInTheDocument();
    expect(screen.queryByText("Total organizations")).not.toBeInTheDocument();
    expect(listOrganizations).not.toHaveBeenCalled();
  });
});
