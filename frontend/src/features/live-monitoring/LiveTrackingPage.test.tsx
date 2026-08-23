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
  listOnlineVehicles: vi.fn(),
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
import { ALL_VEHICLES_ID } from "./VehicleOperationsHeader";

const VEHICLE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", plateNo: "ABC-1234", label: "Bus 12" };

const DEVICE = {
  id: "01DEVICE0000000000000000A",
  terminalId: "TERM12345678",
  isOnline: true,
  cameras: [
    { id: "01CAMERA000000000000000A", channelNo: 1, position: "road_facing" as const, label: "Front" },
  ],
};

const DEVICE_4_CAMERAS = {
  id: "01DEVICE0000000000000000B",
  terminalId: "TERM99999999",
  isOnline: true,
  cameras: [
    { id: "cam-1", channelNo: 1, position: "road_facing" as const, label: "Front" },
    { id: "cam-2", channelNo: 2, position: "in_cabin" as const, label: "Cabin" },
    { id: "cam-3", channelNo: 3, position: "other" as const, label: "Rear" },
    { id: "cam-4", channelNo: 4, position: "other" as const, label: "Side" },
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

function sessionFor(deviceId: string, cameraId: string) {
  return { ...SESSION, id: `session-${cameraId}`, deviceId, cameraId, streamUrl: `ws://jt1078-relay:7911/viewer?token=${cameraId}` };
}

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

const REGIONAL_MANAGER_PRINCIPAL = {
  userId: "u3",
  role: "regional_manager" as const,
  organizationId: null,
  regionIds: ["region-1"],
};

const SUPPORT_STAFF_PRINCIPAL = {
  userId: "u4",
  role: "support_staff" as const,
  organizationId: null,
  regionIds: [],
};

const FINANCE_STAFF_PRINCIPAL = {
  userId: "u5",
  role: "finance_staff" as const,
  organizationId: null,
  regionIds: [],
};

/** ADR-0029: the roles the video panel is now gated to on this dashboard. */
const VIDEO_ELIGIBLE_PRINCIPALS = [
  ["founder", FOUNDER_PRINCIPAL],
  ["regional_manager", REGIONAL_MANAGER_PRINCIPAL],
  ["support_staff", SUPPORT_STAFF_PRINCIPAL],
] as const;

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
    vi.mocked(api.listOnlineVehicles).mockReset().mockResolvedValue({ vehicles: [], totalOnline: 0 });
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
    // Surfaced in both the header's GPS chip and the map's own header status.
    expect(await screen.findByTestId("chip-gps")).toHaveTextContent("Not authorized");
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

  describe("Vehicle -> Device resolution (ADR-0027/0028 §C), now surfaced in the header", () => {
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
      const deviceChip = await screen.findByTestId("chip-device");
      expect(deviceChip).toHaveTextContent("TERM12345678");
      expect(deviceChip).toHaveTextContent("Online");
      // No live/snapshot position was ever mocked with a device_id — proves the device shown
      // above came from the assignment/device calls above, not from any GPS payload.
    });

    it("shows an honest 'No device' chip for a vehicle with no active assignment — GPS keeps working independently", async () => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue(null);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByTestId("chip-device")).toHaveTextContent("No device");
      // The map's own empty state is independent of device resolution.
      expect(await screen.findByText("No live position data")).toBeInTheDocument();
    });
  });

  describe("Removal of the old left Vehicle panel", () => {
    it("has no standalone left vehicle sidebar — the vehicle selector lives in the header, beside the map/video workspace", async () => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE);
      const { container } = renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      await screen.findByTestId("chip-device");

      // The old design's separate always-visible "Device" card no longer exists as its own
      // titled card — device info is now a compact header chip only.
      expect(screen.queryByRole("heading", { name: "Device" })).not.toBeInTheDocument();
      // Exactly one page-level column layout (header + workspace), not a 3-column
      // sidebar/map/panel split — a coarse structural smoke check.
      expect(container.querySelectorAll("select")).toHaveLength(1);
    });
  });

  describe("Video role gating (ADR-0028 §G, widened by ADR-0029)", () => {
    beforeEach(() => {
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE);
    });

    it("renders no Live Video panel or Cameras chip for finance_staff, and makes no video API calls", async () => {
      useAuthStore.setState({ status: "authenticated", principal: FINANCE_STAFF_PRINCIPAL });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      await screen.findByTestId("chip-device");
      expect(screen.queryByText("Live Video")).not.toBeInTheDocument();
      expect(screen.queryByTestId("chip-cameras")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Start Live" })).not.toBeInTheDocument();
      expect(videoApi.requestLiveVideo).not.toHaveBeenCalled();
    });

    it.each(VIDEO_ELIGIBLE_PRINCIPALS)(
      "shows the Live Video panel, ready to start every camera, for %s (ADR-0029)",
      async (_role, principal) => {
        useAuthStore.setState({ status: "authenticated", principal });
        renderPage();
        const select = await screen.findByLabelText("Vehicle");
        await userEvent.selectOptions(select, VEHICLE.id);

        expect(await screen.findByText("Live Video")).toBeInTheDocument();
        expect(await screen.findByText("1 camera ready")).toBeInTheDocument();
      },
    );

    it.each(VIDEO_ELIGIBLE_PRINCIPALS)(
      "Start Live requests a session for the resolved device/camera for %s (ADR-0029)",
      async (_role, principal) => {
        useAuthStore.setState({ status: "authenticated", principal });
        vi.mocked(videoApi.requestLiveVideo).mockResolvedValue(SESSION);
        renderPage();
        const select = await screen.findByLabelText("Vehicle");
        await userEvent.selectOptions(select, VEHICLE.id);
        await userEvent.click(await screen.findByRole("button", { name: "Start Live" }));

        await waitFor(() =>
          expect(videoApi.requestLiveVideo).toHaveBeenCalledWith(DEVICE.id, DEVICE.cameras[0].id),
        );
      },
    );

    it.each(VIDEO_ELIGIBLE_PRINCIPALS)(
      "Stop Live stops the active session for %s (ADR-0029)",
      async (_role, principal) => {
        useAuthStore.setState({ status: "authenticated", principal });
        vi.mocked(videoApi.requestLiveVideo).mockResolvedValue(SESSION);
        playerReturn.state = "connected";
        renderPage();
        const select = await screen.findByLabelText("Vehicle");
        await userEvent.selectOptions(select, VEHICLE.id);
        await userEvent.click(await screen.findByRole("button", { name: "Start Live" }));
        await screen.findByTestId("live-video");

        await userEvent.click(screen.getByRole("button", { name: "Stop Live" }));

        await waitFor(() => expect(videoApi.stopVideoSession).toHaveBeenCalledWith(SESSION.id));
        expect(await screen.findByText("1 camera ready")).toBeInTheDocument();
        expect(screen.queryByTestId("live-video")).not.toBeInTheDocument();
      },
    );

    it("shows the resolved camera count in the header's Cameras chip for org_admin", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByTestId("chip-cameras")).toHaveTextContent("1");
    });

    it("shows a non-blocking offline hint, never disabling Start Live, when the resolved device is offline", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue({ ...DEVICE, isOnline: false });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByText(/last reported offline/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start Live" })).not.toBeDisabled();
    });

    it("shows the 'no device assigned' state in the Live Video panel too, offering no Start Live control", async () => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue(null);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);

      expect(await screen.findByText("Live Video")).toBeInTheDocument();
      expect(await screen.findByText("No device assigned")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Start Live" })).not.toBeInTheDocument();
      expect(videoApi.requestLiveVideo).not.toHaveBeenCalled();
    });
  });

  describe("Multi-camera live video grid (data-driven, not hardcoded)", () => {
    beforeEach(() => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE_4_CAMERAS.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE_4_CAMERAS);
    });

    it("Start Live requests a session for every camera the resolved device reports, and renders one tile per camera", async () => {
      vi.mocked(videoApi.requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
        Promise.resolve(sessionFor(deviceId, cameraId)),
      );
      playerReturn.state = "connected";
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      expect(await screen.findByTestId("chip-cameras")).toHaveTextContent("4");

      await userEvent.click(await screen.findByRole("button", { name: "Start Live" }));

      await waitFor(() => expect(videoApi.requestLiveVideo).toHaveBeenCalledTimes(4));
      for (const camera of DEVICE_4_CAMERAS.cameras) {
        expect(videoApi.requestLiveVideo).toHaveBeenCalledWith(DEVICE_4_CAMERAS.id, camera.id);
      }
      expect(await screen.findAllByTestId("live-video")).toHaveLength(4);
      expect(await screen.findByText("4/4 Live")).toBeInTheDocument();
    });

    it("isolates a single camera's failure — the rest of the grid stays live, not a full-panel failure", async () => {
      vi.mocked(videoApi.requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
        cameraId === "cam-3"
          ? Promise.reject(new Error("relay unreachable for this channel"))
          : Promise.resolve(sessionFor(deviceId, cameraId)),
      );
      playerReturn.state = "connected";
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      await userEvent.click(await screen.findByRole("button", { name: "Start Live" }));

      expect(await screen.findByText("3/4 Live")).toBeInTheDocument();
      expect(await screen.findAllByTestId("live-video")).toHaveLength(3);
      expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    });

    it("Stop Live tears down every open camera session cleanly, leaving nothing orphaned", async () => {
      vi.mocked(videoApi.requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
        Promise.resolve(sessionFor(deviceId, cameraId)),
      );
      playerReturn.state = "connected";
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, VEHICLE.id);
      await userEvent.click(await screen.findByRole("button", { name: "Start Live" }));
      await screen.findAllByTestId("live-video");

      await userEvent.click(screen.getByRole("button", { name: "Stop Live" }));

      await waitFor(() => expect(videoApi.stopVideoSession).toHaveBeenCalledTimes(4));
      for (const camera of DEVICE_4_CAMERAS.cameras) {
        expect(videoApi.stopVideoSession).toHaveBeenCalledWith(`session-${camera.id}`);
      }
      expect(screen.queryByTestId("live-video")).not.toBeInTheDocument();
      expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
    });
  });

  describe("All Vehicles fleet-map mode (ADR-0031)", () => {
    beforeEach(() => {
      useAuthStore.setState({ status: "authenticated", principal: ORG_ADMIN_PRINCIPAL });
    });

    const VEHICLE_ONLINE_A = {
      vehicleId: "veh-a",
      plateNo: "AAA-111",
      label: "Bus A",
      deviceId: "device-a",
      isOnline: true,
      position: {
        latitude: 2.05,
        longitude: 45.32,
        headingDeg: 90,
        speedKph: 25,
        eventTime: "2026-01-01T00:00:00Z",
      },
    };

    const VEHICLE_ONLINE_B = {
      vehicleId: "veh-b",
      plateNo: "BBB-222",
      label: null,
      deviceId: "device-b",
      isOnline: true,
      position: null,
    };

    it("selecting All Vehicles fetches the online-vehicle snapshot and shows the fleet overview", async () => {
      vi.mocked(api.listOnlineVehicles).mockResolvedValue({
        vehicles: [VEHICLE_ONLINE_A],
        totalOnline: 1,
      });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");

      await userEvent.selectOptions(select, ALL_VEHICLES_ID);

      await waitFor(() => expect(api.listOnlineVehicles).toHaveBeenCalledTimes(1));
      expect(await screen.findByText("Fleet Overview")).toBeInTheDocument();
      expect(screen.getByText(/1\/1 vehicles/)).toBeInTheDocument();
    });

    it("renders one marker per online vehicle at its known position", async () => {
      vi.mocked(api.listOnlineVehicles).mockResolvedValue({
        vehicles: [VEHICLE_ONLINE_A, VEHICLE_ONLINE_B],
        totalOnline: 2,
      });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");

      await userEvent.selectOptions(select, ALL_VEHICLES_ID);

      // VEHICLE_ONLINE_A has a known snapshot position and gets a marker immediately;
      // VEHICLE_ONLINE_B has none yet (the disclosed ADR-0031 gap) and gets one only once a
      // live `/ws/tracking` frame arrives — covered by the realtime-update test below.
      await waitFor(() =>
        expect(mockProvider.addMarker).toHaveBeenCalledWith({
          id: "veh-a",
          position: { lat: 2.05, lng: 45.32 },
          headingDeg: 90,
          element: expect.any(Object),
        }),
      );
      expect(mockProvider.addMarker).not.toHaveBeenCalledWith(
        expect.objectContaining({ id: "veh-b" }),
      );
    });

    it("moves a vehicle's marker in realtime from a /ws/tracking frame, the same channel individual mode uses", async () => {
      vi.mocked(api.listOnlineVehicles).mockResolvedValue({
        vehicles: [VEHICLE_ONLINE_B],
        totalOnline: 1,
      });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, ALL_VEHICLES_ID);
      wsReturn.status = "open";

      act(() => {
        latestOnMessage?.({
          type: "position",
          vehicle_id: "veh-b",
          trip_id: null,
          lat: 3.1,
          lng: 46.2,
          speed_kph: 40,
          heading_deg: 270,
          event_time: "2026-01-01T00:05:00Z",
        });
      });

      await waitFor(() =>
        expect(mockProvider.addMarker).toHaveBeenCalledWith(
          expect.objectContaining({ id: "veh-b", position: { lat: 3.1, lng: 46.2 } }),
        ),
      );
    });

    it("switching from All Vehicles back to an individual vehicle restores single-vehicle Map + Live Video exactly", async () => {
      vi.mocked(api.listOnlineVehicles).mockResolvedValue({ vehicles: [], totalOnline: 0 });
      vi.mocked(api.getDeviceAssignmentForVehicle).mockResolvedValue({ deviceId: DEVICE.id });
      vi.mocked(api.getActiveDeviceDetails).mockResolvedValue(DEVICE);
      renderPage();
      const select = await screen.findByLabelText("Vehicle");
      await userEvent.selectOptions(select, ALL_VEHICLES_ID);
      expect(await screen.findByText("Fleet Overview")).toBeInTheDocument();

      await userEvent.selectOptions(select, VEHICLE.id);

      expect(screen.queryByText("Fleet Overview")).not.toBeInTheDocument();
      expect(await screen.findByTestId("chip-device")).toBeInTheDocument();
      expect(await screen.findByText("Live Video")).toBeInTheDocument();
    });

    it("never initializes any camera/video session in All Vehicles mode", async () => {
      vi.mocked(api.listOnlineVehicles).mockResolvedValue({
        vehicles: [VEHICLE_ONLINE_A],
        totalOnline: 1,
      });
      renderPage();
      const select = await screen.findByLabelText("Vehicle");

      await userEvent.selectOptions(select, ALL_VEHICLES_ID);
      await screen.findByText("Fleet Overview");

      expect(screen.queryByText("Live Video")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Start Live" })).not.toBeInTheDocument();
      expect(screen.queryByTestId("live-video")).not.toBeInTheDocument();
      expect(videoApi.requestLiveVideo).not.toHaveBeenCalled();
      expect(api.getDeviceAssignmentForVehicle).not.toHaveBeenCalled();
    });
  });
});
