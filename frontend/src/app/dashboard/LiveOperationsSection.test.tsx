import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockProvider = {
  mount: vi.fn(),
  unmount: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  addMarker: vi.fn(),
  updateMarker: vi.fn(),
  updateMarkerPopup: vi.fn(),
  removeMarker: vi.fn(),
  onMarkerClick: vi.fn(),
  addGeoJsonSource: vi.fn(),
  addLineLayer: vi.fn(),
  addCircleLayer: vi.fn(),
  addPointLayer: vi.fn(),
  removeLayer: vi.fn(),
  removeSource: vi.fn(),
  onUserPanOrZoom: vi.fn(() => vi.fn()),
};

vi.mock("../../shared/map/MapView", () => ({
  MapView: (props: { onReady?: (provider: typeof mockProvider) => void }) => {
    props.onReady?.(mockProvider);
    return <div data-testid="mock-map" />;
  },
}));

vi.mock("./hooks", () => ({
  useTripsInProgress: vi.fn(),
  useVehicleStatusCounts: vi.fn(),
}));

vi.mock("../../features/live-monitoring/useVehiclePosition", () => ({
  useVehiclePosition: vi.fn(),
}));

vi.mock("../../features/platform-analytics/api", () => ({ getPlatformStats: vi.fn() }));

vi.mock("../../features/fleet-devices/vehicles/api", () => ({ getVehicle: vi.fn() }));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => mockNavigate,
}));

import { useTripsInProgress, useVehicleStatusCounts } from "./hooks";
import { useVehiclePosition, type UseVehiclePositionResult } from "../../features/live-monitoring/useVehiclePosition";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import { getVehicle, type Vehicle } from "../../features/fleet-devices/vehicles/api";
import { LiveOperationsSection } from "./LiveOperationsSection";

const PLATFORM_STATS: PlatformStats = {
  organizations: { total: 0, byStatus: {}, createdToday: 0 },
  vehicles: { total: 0 },
  devices: { total: 0, online: 0, offline: 0 },
  users: { total: 0, byStatus: {}, monthlyActive: 0, createdToday: 0 },
  billing: { subscriptionByStatus: {}, expiringSoon: 0, revenue: 0, activeByBillingCycle: {} },
  paymentDueOrganizations: 0,
  systemHealth: { database: "ok", broker: "ok" },
};

const VEHICLE: Vehicle = {
  id: "veh-1",
  organizationId: "org-1",
  plateNo: "BENCH-001",
  label: "Bus 001",
  capacity: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  trackingStatus: null,
};

function gpsResult(overrides: Partial<UseVehiclePositionResult>): UseVehiclePositionResult {
  return {
    wsStatus: "closed",
    isAuthOrPolicyClose: false,
    livePosition: null,
    snapshotQuery: {} as UseVehiclePositionResult["snapshotQuery"],
    hasKnownPosition: false,
    gpsFixStatus: "no_fix",
    lastGpsSignal: null,
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LiveOperationsSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LiveOperationsSection", () => {
  beforeEach(() => {
    for (const fn of Object.values(mockProvider)) fn.mockClear();
    mockNavigate.mockClear();
    vi.mocked(useVehicleStatusCounts)
      .mockReset()
      .mockReturnValue({ active: 0, maintenance: 0, inactive: 0, isLoading: false, isError: false });
    vi.mocked(getPlatformStats).mockReset().mockResolvedValue(PLATFORM_STATS);
    vi.mocked(getVehicle).mockReset().mockResolvedValue(VEHICLE);
    vi.mocked(useTripsInProgress).mockReset();
    vi.mocked(useVehiclePosition).mockReset();
  });

  it("shows an honest empty state and disables position tracking when no trip is in progress", () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 0,
      previewVehicleId: null,
      isLoading: false,
      isError: false,
    });
    vi.mocked(useVehiclePosition).mockReturnValue(gpsResult({}));

    renderSection();

    // The shared hook's own "" convention for "nothing selected" (matching LiveTrackingPage) —
    // never a raw vehicle-id-or-null passed straight to a bespoke WS subscription.
    expect(useVehiclePosition).toHaveBeenCalledWith("");
    expect(screen.getByText("No vehicles on an active trip")).toBeInTheDocument();
    expect(mockProvider.addMarker).not.toHaveBeenCalled();
    expect(getVehicle).not.toHaveBeenCalled();
  });

  it("root-cause fix: an invalid-fix GPS signal never moves the marker — only useVehiclePosition's own last-known-good livePosition does", () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 1,
      previewVehicleId: "veh-1",
      isLoading: false,
      isError: false,
    });
    // Mirrors what `useVehiclePosition` itself does for a fix-invalid frame (e.g. the device's
    // cached Shenzhen factory position): `lastGpsSignal.isGpsValid` is false and `livePosition`
    // stays null — this component must never invent a marker position from anywhere else.
    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        gpsFixStatus: "no_fix",
        lastGpsSignal: { isGpsValid: false, eventTime: "2026-01-01T00:00:00Z" },
      }),
    );

    renderSection();

    expect(useVehiclePosition).toHaveBeenCalledWith("veh-1");
    expect(mockProvider.addMarker).not.toHaveBeenCalled();
    expect(mockProvider.setCenter).not.toHaveBeenCalled();
  });

  it("renders the professional RAAD bus marker (with a vehicle-info popup) and centers on it, once useVehiclePosition resolves a valid last-known-good position", async () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 1,
      previewVehicleId: "veh-1",
      isLoading: false,
      isError: false,
    });
    // No position yet — lets the plate/label lookup (`getVehicle`) resolve first, the realistic
    // ordering: `useVehiclePosition`'s own REST+WS handshake is at least as slow as this one plain
    // GET. The marker is created once, on the position update below, already carrying the real
    // title (a later-resolving metadata case is covered separately below).
    vi.mocked(useVehiclePosition).mockReturnValue(gpsResult({ wsStatus: "open" }));

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LiveOperationsSection />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // `act`-aware (unlike `vi.waitFor`) — the resolved query must actually flow through a React
    // state update before the rerender below sees `vehicleQuery.data` populated.
    await waitFor(() =>
      expect(queryClient.getQueryData(["vehicles", "dashboard-preview", "veh-1"])).toEqual(VEHICLE),
    );

    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        hasKnownPosition: true,
        gpsFixStatus: "live",
        livePosition: { lat: 2.0469, lng: 45.3182, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
        snapshotQuery: { data: { speedKph: 42 } } as UseVehiclePositionResult["snapshotQuery"],
      }),
    );
    rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LiveOperationsSection />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mockProvider.addMarker).toHaveBeenCalledTimes(1));
    const call = vi.mocked(mockProvider.addMarker).mock.calls[0][0];
    expect(call.id).toBe("dashboard-preview-vehicle");
    expect(call.position).toEqual(expect.objectContaining({ lat: 2.0469, lng: 45.3182 }));
    expect(call.headingDeg).toBe(90);
    // The same `createVehicleMarkerElement` bus-icon element `VehicleMapPanel`/`FleetMapPanel`
    // use — never a bare/generic Mapbox pin.
    expect(call.element).toBeInstanceOf(HTMLElement);
    expect(call.element.dataset.fixStatus).toBe("live");
    expect(call.element.querySelector("svg")).not.toBeNull();
    // The same "vehicle info" popup fields as `FleetMapPanel` (plate/label, fix status, speed,
    // last GPS update, click affordance) — built via the shared `buildVehiclePopupHtml`.
    expect(call.popupHtml).toContain("BENCH-001");
    expect(call.popupHtml).toContain("Bus 001");
    expect(call.popupHtml).toContain("Live");
    expect(call.popupHtml).toContain("42 km/h");
    expect(call.popupHtml).toContain("Click to open Live Tracking");

    expect(mockProvider.setCenter).toHaveBeenCalledWith(expect.objectContaining({ lat: 2.0469, lng: 45.3182 }));
    expect(screen.queryByText("No vehicles on an active trip")).not.toBeInTheDocument();
  });

  it("clicking the marker navigates to Live Tracking — the same page the header link already goes to", () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 1,
      previewVehicleId: "veh-1",
      isLoading: false,
      isError: false,
    });
    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        hasKnownPosition: true,
        gpsFixStatus: "live",
        livePosition: { lat: 2.0469, lng: 45.3182, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
      }),
    );

    renderSection();

    const call = vi.mocked(mockProvider.addMarker).mock.calls[0][0];
    call.element.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(mockNavigate).toHaveBeenCalledWith("/platform/tracking");
  });

  it("updates the marker in place (never removes/re-adds it) on a subsequent position update", () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 1,
      previewVehicleId: "veh-1",
      isLoading: false,
      isError: false,
    });
    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        hasKnownPosition: true,
        gpsFixStatus: "live",
        livePosition: { lat: 2.0469, lng: 45.3182, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
      }),
    );

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LiveOperationsSection />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);

    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        hasKnownPosition: true,
        gpsFixStatus: "stale",
        livePosition: { lat: 3, lng: 46, headingDeg: 10, eventTime: "2026-01-01T00:05:00Z" },
      }),
    );
    rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LiveOperationsSection />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);
    expect(mockProvider.updateMarker).toHaveBeenCalledWith(
      "dashboard-preview-vehicle",
      expect.objectContaining({ lat: 3, lng: 46 }),
      10,
    );
    // Root-cause fix (vehicle-popup staleness investigation): the popup refreshes in place too,
    // reflecting the new fix status/timestamp — never left showing the marker-creation-time text.
    expect(mockProvider.updateMarkerPopup).toHaveBeenCalledWith(
      "dashboard-preview-vehicle",
      expect.stringContaining("Stale"),
    );
    // `removeMarker` fires once on mount (the same unconditional "reset on vehicleId change"
    // effect `VehicleMapPanel` also runs on its own first mount — a harmless no-op against a
    // marker that was never added) but never again just because a same-vehicle position updated.
    expect(mockProvider.removeMarker).toHaveBeenCalledTimes(1);
  });

  it("self-corrects the popup title once vehicle metadata resolves after the marker was already created — never a permanently-stale raw id", async () => {
    vi.mocked(useTripsInProgress).mockReturnValue({
      total: 1,
      previewVehicleId: "veh-1",
      isLoading: false,
      isError: false,
    });
    let resolveVehicle!: (vehicle: Vehicle) => void;
    vi.mocked(getVehicle).mockReset().mockReturnValue(
      new Promise((resolve) => {
        resolveVehicle = resolve;
      }),
    );
    vi.mocked(useVehiclePosition).mockReturnValue(
      gpsResult({
        wsStatus: "open",
        hasKnownPosition: true,
        gpsFixStatus: "live",
        livePosition: { lat: 2.0469, lng: 45.3182, headingDeg: 90, eventTime: "2026-01-01T00:00:00Z" },
      }),
    );

    renderSection();

    // Metadata hasn't resolved yet — the popup falls back to the raw id, but the marker still
    // renders immediately rather than waiting on it.
    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);
    expect(vi.mocked(mockProvider.addMarker).mock.calls[0][0].popupHtml).toContain("veh-1");

    resolveVehicle(VEHICLE);
    await waitFor(() => expect(mockProvider.updateMarkerPopup).toHaveBeenCalled());

    // Refreshed in place — never a second marker.
    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);
    const [, html] = vi.mocked(mockProvider.updateMarkerPopup).mock.calls.at(-1)!;
    expect(html).toContain("BENCH-001");
    expect(html).toContain("Bus 001");
  });
});
