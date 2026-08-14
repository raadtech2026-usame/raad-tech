import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listDevicesForVideoPicker: vi.fn(),
  requestLiveVideo: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const relayReturn: { state: string; closeCode: number | null; bytesReceived: number } = {
  state: "idle",
  closeCode: null,
  bytesReceived: 0,
};
vi.mock("./useRelayStreamSocket", () => ({
  useRelayStreamSocket: () => relayReturn,
}));

import * as api from "./api";
import { ApiError } from "../../shared/api/types";
import { VideoPage } from "./VideoPage";

const DEVICE = {
  id: "01DEVICE0000000000000000A",
  terminalId: "TERM12345678",
  model: "LSZ-C5804DG-Q-F",
  vendor: "LSZ",
  lifecycleState: "assigned" as const,
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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <VideoPage />
    </QueryClientProvider>,
  );
}

async function selectDeviceAndCamera() {
  await userEvent.selectOptions(await screen.findByLabelText("Device"), DEVICE.id);
  await userEvent.selectOptions(screen.getByLabelText("Camera"), DEVICE.cameras[0].id);
}

describe("VideoPage", () => {
  beforeEach(() => {
    vi.mocked(api.listDevicesForVideoPicker).mockReset().mockResolvedValue([DEVICE]);
    vi.mocked(api.requestLiveVideo).mockReset();
    vi.mocked(api.stopVideoSession)
      .mockReset()
      .mockResolvedValue({ ...SESSION, status: "ended" });
    relayReturn.state = "idle";
    relayReturn.closeCode = null;
    relayReturn.bytesReceived = 0;
  });

  it("shows an honest empty state before any device/camera is selected", async () => {
    renderPage();
    expect(await screen.findByText("Select a device and camera")).toBeInTheDocument();
  });

  it("lists devices by terminal id — no vehicle correlation exists to pick by plate number — and their cameras", async () => {
    renderPage();
    const deviceSelect = await screen.findByLabelText("Device");
    expect(deviceSelect).toHaveTextContent("TERM12345678");

    await userEvent.selectOptions(deviceSelect, DEVICE.id);
    const cameraSelect = screen.getByLabelText("Camera");
    expect(cameraSelect).toHaveTextContent("Front");
  });

  it("requests a live session with the selected device/camera and shows the requesting state", async () => {
    vi.mocked(api.requestLiveVideo).mockImplementation(() => new Promise(() => {}));
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    expect(api.requestLiveVideo).toHaveBeenCalledWith(DEVICE.id, DEVICE.cameras[0].id);
    expect(await screen.findByText("Requesting a live session…")).toBeInTheDocument();
  });

  it("shows the relay-connected state honestly, without pretending to render video", async () => {
    vi.mocked(api.requestLiveVideo).mockResolvedValue(SESSION);
    relayReturn.state = "connected";
    relayReturn.bytesReceived = 2048;
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    expect(await screen.findByText("Stream is live on the relay")).toBeInTheDocument();
    expect(screen.getByText(/2\.0 KB received/)).toBeInTheDocument();
    expect(screen.getByText(/browser playback isn't wired yet/)).toBeInTheDocument();
  });

  it("maps a 500 (no VideoProviderPort bound on this deployment) to the unavailable state, not a generic error", async () => {
    vi.mocked(api.requestLiveVideo).mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "boom", correlationId: null }),
    );
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    expect(await screen.findByText("Video is unavailable")).toBeInTheDocument();
  });

  it("shows the real backend error message for a 403 VIDEO_FORBIDDEN, not a fabricated one", async () => {
    vi.mocked(api.requestLiveVideo).mockRejectedValue(
      new ApiError(403, { code: "VIDEO_FORBIDDEN", message: "Video access denied.", correlationId: null }),
    );
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    expect(await screen.findByText("Video access denied.")).toBeInTheDocument();
  });

  it("stops the session on explicit Stop and shows the stopped state", async () => {
    vi.mocked(api.requestLiveVideo).mockResolvedValue(SESSION);
    relayReturn.state = "connected";
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await screen.findByText("Stream is live on the relay");

    await userEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(api.stopVideoSession).toHaveBeenCalledWith(SESSION.id);
    expect(await screen.findByText("Session stopped")).toBeInTheDocument();
  });

  it("stops the previous session exactly once when the device selection changes while live", async () => {
    const OTHER_DEVICE = { ...DEVICE, id: "01DEVICE0000000000000000C", terminalId: "TERM00000000" };
    vi.mocked(api.listDevicesForVideoPicker).mockResolvedValue([DEVICE, OTHER_DEVICE]);
    vi.mocked(api.requestLiveVideo).mockResolvedValue(SESSION);
    relayReturn.state = "connected";
    renderPage();
    const deviceSelect = await screen.findByLabelText("Device");
    await userEvent.selectOptions(deviceSelect, DEVICE.id);
    await userEvent.selectOptions(screen.getByLabelText("Camera"), DEVICE.cameras[0].id);
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await screen.findByText("Stream is live on the relay");

    await userEvent.selectOptions(deviceSelect, OTHER_DEVICE.id);

    expect(api.stopVideoSession).toHaveBeenCalledTimes(1);
    expect(api.stopVideoSession).toHaveBeenCalledWith(SESSION.id);
  });

  it("does not call stop again after an explicit Stop already tore the session down (idempotency guard)", async () => {
    vi.mocked(api.requestLiveVideo).mockResolvedValue(SESSION);
    relayReturn.state = "connected";
    const { unmount } = renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await screen.findByText("Stream is live on the relay");
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    await screen.findByText("Session stopped");

    unmount();

    expect(api.stopVideoSession).toHaveBeenCalledTimes(1);
  });
});
