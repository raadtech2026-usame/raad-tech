import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../shared/stores/authStore";
import { DashboardHomePage } from "./DashboardHomePage";
import type { PlatformStats, AuditEntry } from "../features/platform-analytics/api";
import type { OffsetPage } from "../shared/api/types";
import type { OffsetListParams } from "../shared/api/listParams";
import type { TripSummary } from "../features/transport-ops/trips/api";

vi.mock("../features/transport-ops/drivers/api", () => ({ listDrivers: vi.fn() }));
vi.mock("../features/transport-ops/students/api", () => ({ countStudents: vi.fn() }));
vi.mock("../features/transport-ops/parents/api", () => ({ countParents: vi.fn() }));
vi.mock("../features/platform-analytics/api", () => ({ getPlatformStats: vi.fn(), listAuditEntries: vi.fn() }));
vi.mock("../features/fleet-devices/vehicles/api", () => ({ listVehicles: vi.fn() }));
vi.mock("../features/transport-ops/trips/api", () => ({ listTrips: vi.fn() }));
vi.mock("../shared/map/MapView", () => ({ MapView: () => null }));
vi.mock("../shared/hooks/useWebSocket", () => ({
  useWebSocketChannel: () => ({ status: "closed", lastCloseCode: null, send: vi.fn() }),
}));

import { listDrivers } from "../features/transport-ops/drivers/api";
import { countStudents } from "../features/transport-ops/students/api";
import { countParents } from "../features/transport-ops/parents/api";
import { getPlatformStats, listAuditEntries } from "../features/platform-analytics/api";
import { listVehicles } from "../features/fleet-devices/vehicles/api";
import { listTrips } from "../features/transport-ops/trips/api";

function pageOf(total: number) {
  return { data: [], page: { total, page: 1, pageSize: 1 } };
}

const SAMPLE_PLATFORM_STATS: PlatformStats = {
  organizations: { total: 3, byStatus: { active: 2, suspended: 1 }, createdToday: 1 },
  vehicles: { total: 8 },
  devices: { total: 5, online: 4, offline: 1 },
  users: { total: 20, byStatus: { active: 18, invited: 2 }, monthlyActive: 12, createdToday: 2 },
  billing: { subscriptionByStatus: { active: 6, trial: 1 }, expiringSoon: 1, revenue: 4500 },
  systemHealth: { database: "ok", broker: "down" },
};

function mockVehicleStatusCounts({
  active = 0,
  maintenance = 0,
  inactive = 0,
}: { active?: number; maintenance?: number; inactive?: number } = {}) {
  vi.mocked(listVehicles).mockImplementation(async (params: OffsetListParams) => {
    const status = params.filters.status;
    const total = status === "active" ? active : status === "maintenance" ? maintenance : status === "inactive" ? inactive : 0;
    return pageOf(total) as unknown as OffsetPage<never>;
  });
}

function mockTripsInProgress({ total = 0, vehicleId }: { total?: number; vehicleId?: string } = {}) {
  const data: TripSummary[] = vehicleId
    ? [{ id: "trip-1", vehicleId, driverId: "d1", routeId: "r1", tripType: "morning", status: "in_progress", scheduledDate: "2026-08-05" }]
    : [];
  vi.mocked(listTrips).mockResolvedValue({ data, page: { total, page: 1, pageSize: 1 } });
}

function mockAuditEntries(entries: AuditEntry[]) {
  vi.mocked(listAuditEntries).mockResolvedValue({ data: entries, page: { total: entries.length, page: 1, pageSize: 8 } });
}

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setFounder() {
  useAuthStore.setState({
    principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  });
}

describe("DashboardHomePage", () => {
  beforeEach(() => {
    vi.mocked(listDrivers).mockReset().mockResolvedValue(pageOf(0));
    vi.mocked(countStudents).mockReset().mockResolvedValue(0);
    vi.mocked(countParents).mockReset().mockResolvedValue(0);
    vi.mocked(getPlatformStats).mockReset().mockResolvedValue(SAMPLE_PLATFORM_STATS);
    vi.mocked(listAuditEntries).mockReset();
    vi.mocked(listVehicles).mockReset();
    vi.mocked(listTrips).mockReset();
    mockAuditEntries([]);
    mockVehicleStatusCounts();
    mockTripsInProgress();
  });

  it("shows the top KPI row with real platform data for a platform role", async () => {
    setFounder();
    renderDashboard();

    expect(await screen.findByText("Organizations")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("Vehicles")).toBeInTheDocument();
    expect(screen.getByText("Devices")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("2 active · 1 new today")).toBeInTheDocument();
    expect(getPlatformStats).toHaveBeenCalled();
  });

  it("shows Live Operations stats and an honest empty map state when no trip is active", async () => {
    setFounder();
    mockTripsInProgress({ total: 0 });
    mockVehicleStatusCounts({ active: 5 });

    renderDashboard();

    expect(await screen.findByText("Live Operations")).toBeInTheDocument();
    expect(screen.getByText("Trips in progress")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Vehicles active")).toBeInTheDocument());
    expect(screen.getByText("Devices online")).toBeInTheDocument();
    expect(await screen.findByText("No vehicles on an active trip")).toBeInTheDocument();
  });

  it("previews the map for the first vehicle on an in-progress trip", async () => {
    setFounder();
    mockTripsInProgress({ total: 1, vehicleId: "veh-1" });

    renderDashboard();

    await waitFor(() => expect(listTrips).toHaveBeenCalled());
    expect(screen.queryByText("No vehicles on an active trip")).not.toBeInTheDocument();
  });

  it("shows Recent Activity entries, humanized", async () => {
    setFounder();
    mockAuditEntries([
      {
        id: "a1",
        organizationId: null,
        actorUserId: "u1",
        action: "VehicleActivated",
        entityType: "Vehicle",
        entityId: "v1",
        createdAt: new Date().toISOString(),
      },
    ]);

    renderDashboard();

    expect(await screen.findByText("Vehicle Activated")).toBeInTheDocument();
    expect(screen.getByText("Vehicle")).toBeInTheDocument();
  });

  it("shows an empty state when there is no recent activity", async () => {
    setFounder();
    mockAuditEntries([]);

    renderDashboard();

    expect(await screen.findByText("No activity yet")).toBeInTheDocument();
  });

  it("shows Fleet Health and Device Health breakdowns", async () => {
    setFounder();
    mockVehicleStatusCounts({ active: 7, maintenance: 1, inactive: 2 });

    renderDashboard();

    expect(await screen.findByText("Fleet Health")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("7").length).toBeGreaterThan(0));
    expect(screen.getByText("Device Health")).toBeInTheDocument();
    expect(screen.getByText("Database")).toBeInTheDocument();
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("Broker")).toBeInTheDocument();
    expect(screen.getByText("Down")).toBeInTheDocument();
  });

  it("shows the subscription and revenue billing summaries", async () => {
    setFounder();
    renderDashboard();

    expect(await screen.findByText("Subscriptions")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(await screen.findByText("1 subscription expiring soon")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("$4,500")).toBeInTheDocument());
  });

  it("still shows the drivers/students/parents People strip", async () => {
    setFounder();
    vi.mocked(listDrivers).mockResolvedValue(pageOf(7));

    renderDashboard();

    expect(await screen.findByText("Total drivers")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("7")).toBeInTheDocument());
  });

  it("shows a visible error (not a silent blank) when the KPI row fails to load", async () => {
    setFounder();
    vi.mocked(getPlatformStats).mockReset().mockRejectedValue(new Error("network down"));

    renderDashboard();

    expect(await screen.findByText("Could not load platform analytics")).toBeInTheDocument();
    expect(screen.queryByText("Organizations")).not.toBeInTheDocument();
  });

  it("hides every platform section entirely for an Org Admin", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
      status: "authenticated",
    });

    renderDashboard();

    expect(await screen.findByText(/Welcome/)).toBeInTheDocument();
    expect(screen.queryByText("Organizations")).not.toBeInTheDocument();
    expect(screen.queryByText("Total drivers")).not.toBeInTheDocument();
    expect(getPlatformStats).not.toHaveBeenCalled();
  });

  it("shows a narrower dashboard for Finance Staff, matching their actual RBAC grants", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "finance_staff", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });

    renderDashboard();

    // Visible: KPI row, Device Health, Billing — all keyed off `admin.platform_stats.read`,
    // which Finance Staff does hold (ADR-0020).
    expect(await screen.findByText("Organizations")).toBeInTheDocument();
    expect(screen.getByText("Device Health")).toBeInTheDocument();
    expect(screen.getByText("Subscriptions")).toBeInTheDocument();

    // Hidden: Finance Staff holds none of `fleet_device.vehicles.read`, `transport_ops.
    // {drivers,trips}.list`, or `admin.audit.read` in the seeded RBAC matrix, so these would
    // 403 rather than render real data — omitted instead of shown broken.
    expect(screen.queryByText("Live Operations")).not.toBeInTheDocument();
    expect(screen.queryByText("Recent Activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Fleet Health")).not.toBeInTheDocument();
    expect(screen.queryByText("Total drivers")).not.toBeInTheDocument();
    expect(listVehicles).not.toHaveBeenCalled();
    expect(listTrips).not.toHaveBeenCalled();
    expect(listAuditEntries).not.toHaveBeenCalled();
    expect(listDrivers).not.toHaveBeenCalled();
  });
});
