import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listVehiclesForTracking: vi.fn(),
  getLatestVehiclePosition: vi.fn(),
  getActiveTripRouteId: vi.fn(),
  getRouteWithStops: vi.fn(),
}));

const mockProvider = {
  mount: vi.fn(),
  unmount: vi.fn(),
  setCenter: vi.fn(),
  setZoom: vi.fn(),
  fitBounds: vi.fn(),
  addMarker: vi.fn(),
  updateMarker: vi.fn(),
  removeMarker: vi.fn(),
  addGeoJsonSource: vi.fn(),
  addLineLayer: vi.fn(),
  addCircleLayer: vi.fn(),
  removeLayer: vi.fn(),
  removeSource: vi.fn(),
};

vi.mock("../../shared/map/MapView", () => ({
  MapView: (props: { onReady?: (provider: typeof mockProvider) => void }) => {
    props.onReady?.(mockProvider);
    return <div data-testid="mock-map" />;
  },
}));

type OnMessage = (message: unknown) => void;
let latestOnMessage: OnMessage | null = null;
const mockSend = vi.fn();
const wsReturn: { status: string; lastCloseCode: number | null; send: typeof mockSend } = {
  status: "connecting",
  lastCloseCode: null,
  send: mockSend,
};

vi.mock("../../shared/hooks/useWebSocket", () => ({
  useWebSocketChannel: (_path: string, options: { onMessage: OnMessage }) => {
    latestOnMessage = options.onMessage;
    return wsReturn;
  },
}));

import * as api from "./api";
import { LiveTrackingPage } from "./LiveTrackingPage";

const VEHICLE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", plateNo: "ABC-1234", label: "Bus 12" };

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <LiveTrackingPage />
    </QueryClientProvider>,
  );
  return {
    ...utils,
    rerenderSame: () =>
      utils.rerender(
        <QueryClientProvider client={queryClient}>
          <LiveTrackingPage />
        </QueryClientProvider>,
      ),
  };
}

describe("LiveTrackingPage", () => {
  beforeEach(() => {
    vi.mocked(api.listVehiclesForTracking).mockReset().mockResolvedValue([VEHICLE]);
    vi.mocked(api.getLatestVehiclePosition).mockReset().mockResolvedValue(null);
    vi.mocked(api.getActiveTripRouteId).mockReset().mockResolvedValue(null);
    vi.mocked(api.getRouteWithStops).mockReset();
    mockSend.mockClear();
    for (const fn of Object.values(mockProvider)) fn.mockClear();
    wsReturn.status = "connecting";
    wsReturn.lastCloseCode = null;
    latestOnMessage = null;
  });

  it("shows an honest empty state before any vehicle is selected", async () => {
    renderPage();
    expect(await screen.findByText("Select a vehicle to start tracking")).toBeInTheDocument();
  });

  it("selecting a vehicle with no known position shows the honest 'no live position' state, never a fabricated marker", async () => {
    renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);

    expect(await screen.findByText("No live position data")).toBeInTheDocument();
    expect(mockProvider.addMarker).not.toHaveBeenCalled();
  });

  it("sends the subscribe frame once the socket is open for the selected vehicle", async () => {
    const { rerenderSame } = renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);

    wsReturn.status = "open";
    rerenderSame();

    expect(mockSend).toHaveBeenCalledWith({ type: "subscribe", channel: "vehicle", vehicle_id: VEHICLE.id });
  });

  it("renders a live position frame as a map marker and clears the empty state", async () => {
    const { rerenderSame } = renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);
    wsReturn.status = "open";
    rerenderSame();

    act(() => {
      latestOnMessage?.({
        type: "position",
        vehicle_id: VEHICLE.id,
        trip_id: null,
        lat: 2.05,
        lng: 45.32,
        speed_kph: 30,
        heading_deg: 180,
        event_time: "2026-01-01T00:00:00Z",
      });
    });

    expect(mockProvider.addMarker).toHaveBeenCalledWith({
      id: "live-vehicle",
      position: { lat: 2.05, lng: 45.32 },
      headingDeg: 180,
    });
    expect(screen.queryByText("No live position data")).not.toBeInTheDocument();
  });

  it("updates (not re-adds) the marker on a second position frame for the same vehicle", async () => {
    const { rerenderSame } = renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);
    wsReturn.status = "open";
    rerenderSame();

    const frame = (lat: number) => ({
      type: "position",
      vehicle_id: VEHICLE.id,
      trip_id: null,
      lat,
      lng: 45.32,
      speed_kph: 30,
      heading_deg: 90,
      event_time: "2026-01-01T00:00:00Z",
    });
    act(() => latestOnMessage?.(frame(2.05)));
    act(() => latestOnMessage?.(frame(2.06)));

    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);
    expect(mockProvider.updateMarker).toHaveBeenCalledWith("live-vehicle", { lat: 2.06, lng: 45.32 }, 90);
  });

  it("shows a not-authorized state on a policy close code instead of a silent 'connecting' spinner", async () => {
    const { rerenderSame } = renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);

    wsReturn.status = "closed";
    wsReturn.lastCloseCode = 4403;
    rerenderSame();

    expect(await screen.findByText("Not authorized to track this vehicle")).toBeInTheDocument();
  });

  it("clears the previous vehicle's marker when switching to a different one", async () => {
    vi.mocked(api.listVehiclesForTracking).mockResolvedValue([
      VEHICLE,
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FBX", plateNo: "XYZ-9999", label: null },
    ]);
    const { rerenderSame } = renderPage();
    const select = await screen.findByLabelText("Vehicle");
    await userEvent.selectOptions(select, VEHICLE.id);
    wsReturn.status = "open";
    rerenderSame();
    act(() =>
      latestOnMessage?.({
        type: "position",
        vehicle_id: VEHICLE.id,
        trip_id: null,
        lat: 2.05,
        lng: 45.32,
        speed_kph: 30,
        heading_deg: 90,
        event_time: "2026-01-01T00:00:00Z",
      }),
    );
    expect(mockProvider.addMarker).toHaveBeenCalledTimes(1);

    await userEvent.selectOptions(select, "01ARZ3NDEKTSV4RRFFQ69G5FBX");

    expect(mockProvider.removeMarker).toHaveBeenCalledWith("live-vehicle");
    expect(await screen.findByText("No live position data")).toBeInTheDocument();
  });
});
