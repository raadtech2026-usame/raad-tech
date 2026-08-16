import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listVehiclesForTracking: vi.fn(),
  getLatestVehiclePosition: vi.fn(),
  getActiveTripRouteId: vi.fn(),
  getRouteWithStops: vi.fn(),
  getDeviceAssignmentForVehicle: vi.fn(),
  getActiveDeviceDetails: vi.fn(),
}));

vi.mock("../video/api", () => ({
  requestLiveVideo: vi.fn(),
  stopVideoSession: vi.fn(),
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

const playerReturn: { state: string; errorMessage: string | null } = {
  state: "idle",
  errorMessage: null,
};
vi.mock("../video/useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import * as api from "./api";
import * as videoApi from "../video/api";
import { useAuthStore } from "../../shared/stores/authStore";
import { LiveTrackingPage } from "./LiveTrackingPage";

const VEHICLE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", plateNo: "ABC-1234", label: "Bus 12" };

const DEVICE = {
  id: "01DEVICE0000000000000000A",
  terminalId: "TERM12345678",
  isOnline: true,
  cameras: [
    { id: "01CAMERA000000000000000A", channelNo: 1, position: "road_facing" as const, label: "Front" },
  ],
};

const SESSION = {
  id: "01SESSION000000000000000A",
  organizationId: "01ORG00000000000000000000",
  deviceId: DEVICE.id,
  cameraId: DEVICE.cameras[0].id,
  purpose: "live" as const,
  requestedBy: "01USER00000000000000000A",
  windowStart: null,
  windowEnd: null,
  status: "requested" as const,
  startedAt: null,
  endedAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  streamUrl: "ws://jt1078-relay:7911/viewer?token=abc123",
};

const ORG_ADMIN_PRINCIPAL = {
  userId: "u1",
  role: "org_admin" as const,
  organizationId: "org-1",
  regionIds: [],
};

const FOUNDER_PRINCIPAL = {
  userId: "u2",
  role: "founder" as const,
  organizationId: null,
  regionIds: [],
};

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
    vi.mocked(api.getDeviceAssignmentForVehicle).mockReset().mockResolvedValue(null);
    vi.mocked(api.getActiveDeviceDetails).mockReset();
    vi.mocked(videoApi.requestLiveVideo).mockReset();
    vi.mocked(videoApi.stopVideoSession).mockReset().mockResolvedValue({ ...SESSION, status: "ended" });
    mockSend.mockClear();
    for (const fn of Object.values(mockProvider)) fn.mockClear();
    wsReturn.status = "connecting";
    wsReturn.lastCloseCode = null;
    latestOnMessage = null;
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
    // No role set by default (matches an unauthenticated/unspecified-role render) — every test
    // below that cares about role sets it explicitly, so behavior never depends on suite order.
    useAuthStore.setState({ status: "signed_out", principal: null });
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

  describe("Vehicle -> Device resolution (ADR-0027/0028 §C)", () => {
    it("resolves the vehicle's active device via GET /vehicles/{id}/device-assignment, never a GPS field", async () => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      await waitFor(() => {
        expect(api.getDeviceAssignmentForVehicle).toHaveBeenCalledWith(VEHICLE.id);
      });
      expect(api.getActiveDeviceDetails).toHaveBeenCalledWith(DEVICE.id);
      expect(await screen.findByText("TERM12345678")).toBeInTheDocument();
      expect(await screen.findByText("Online")).toBeInTheDocument();
      // No live/snapshot position was ever mocked with a device_id — proves the device shown
      // above came from the assignment/device calls above, not from any GPS payload.
    });

    it("shows the honest 'no device assigned' state for a vehicle with no active assignment — GPS keeps working independently", async () => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue(null);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByText("No device assigned")).toBeInTheDocument();
      // The map's own empty state is independent of device resolution.
      expect(await screen.findByText("No live position data")).toBeInTheDocument();
    });
  });

  describe("Video role gating (ADR-0028 §G)", () => {
    beforeEach(() => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE);
    });

    it("renders no camera picker or video panel for a non-org_admin role, and makes no video API calls", async () => {
      useAuthStore.setState({ status: "authenticated", principal: FOUNDER_PRINCIPAL });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      await screen.findByText("TERM12345678");
      expect(screen.queryByText("Live Video")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Camera")).not.toBeInTheDocument();
      expect(videoApi.requestLiveVideo).not.toHaveBeenCalled();
    });

    it("populates the camera picker from the resolved device's own cameras for org_admin", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      const cameraSelect = await screen.findByLabelText("Camera");
      expect(cameraSelect).toHaveTextContent("Front");
    });

    it("shows a non-blocking offline hint, never disabling Start, when the resolved device is offline", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue({ ...DEVICE, isOnline: false });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      await screen.findByLabelText("Camera");

      expect(await screen.findByText(/last reported offline/i)).toBeInTheDocument();
      await userEvent.selectOptions(screen.getByLabelText("Camera"), DEVICE.cameras[0].id);
      expect(screen.getByRole("button", { name: "Start Live" })).not.toBeDisabled();
    });

    it("starts a live session with the resolved device id, exactly as ADR-0027 intends — never inferred from a GPS position field", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(videoApi.requestLiveVideo).mockResolvedValue(SESSION);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      await userEvent.selectOptions(await screen.findByLabelText("Camera"), DEVICE.cameras[0].id);
      await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

      expect(videoApi.requestLiveVideo).toHaveBeenCalledWith(DEVICE.id, DEVICE.cameras[0].id);
    });

    it("shows the 'no device assigned' state in the video panel too, without offering a camera picker", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue(null);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByText("Live Video")).toBeInTheDocument();
      expect(screen.queryByLabelText("Camera")).not.toBeInTheDocument();
      expect(videoApi.requestLiveVideo).not.toHaveBeenCalled();
    });
  });
});
