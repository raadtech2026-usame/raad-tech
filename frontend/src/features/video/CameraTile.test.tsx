import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  requestLiveVideo: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const playerReturn: { state: string; errorMessage: string | null; stalled: boolean } = {
  state: "idle",
  errorMessage: null,
  stalled: false,
};
vi.mock("./useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import { requestLiveVideo } from "./api";
import { CameraTile } from "./CameraTile";

const CAMERA = { id: "cam-1", channelNo: 3, position: "road_facing" as const, label: "Front Door" };

function renderTile(onPhaseChange = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CameraTile deviceId="device-1" camera={CAMERA} onPhaseChange={onPhaseChange} />
    </QueryClientProvider>,
  );
}

describe("CameraTile", () => {
  beforeEach(() => {
    vi.mocked(requestLiveVideo).mockReset();
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
    playerReturn.stalled = false;
  });

  it("starts its own session exactly once on mount, for its own camera only", async () => {
    vi.mocked(requestLiveVideo).mockImplementation(() => new Promise(() => {}));
    renderTile();
    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(1));
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "cam-1", "main");
  });

  it("shows the channel number and camera label", async () => {
    vi.mocked(requestLiveVideo).mockImplementation(() => new Promise(() => {}));
    renderTile();
    expect(await screen.findByText("Channel 3")).toBeInTheDocument();
    expect(screen.getByText("Front Door")).toBeInTheDocument();
  });

  it("reports 'connected' upward and shows a Live badge once its own session connects", async () => {
    vi.mocked(requestLiveVideo).mockResolvedValue({
      id: "session-1",
      organizationId: "org-1",
      deviceId: "device-1",
      cameraId: "cam-1",
      purpose: "live",
      requestedBy: "user-1",
      windowStart: null,
      windowEnd: null,
      status: "requested",
      startedAt: null,
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      streamUrl: "ws://relay/viewer?token=abc",
    });
    playerReturn.state = "connected";
    const onPhaseChange = vi.fn();
    renderTile(onPhaseChange);

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(await screen.findByTestId("live-video")).toBeInTheDocument();
    await waitFor(() => expect(onPhaseChange).toHaveBeenCalledWith("cam-1", "connected"));
  });

  it("keeps its video on screen under a 'No signal' badge while the picture is frozen", async () => {
    // 2026-09-23 regression: a freeze used to unmount the <video>, which paused it and left the
    // tile on "No signal" for good even after frames resumed.
    vi.mocked(requestLiveVideo).mockResolvedValue({
      id: "session-1",
      organizationId: "org-1",
      deviceId: "device-1",
      cameraId: "cam-1",
      purpose: "live",
      requestedBy: "user-1",
      windowStart: null,
      windowEnd: null,
      status: "requested",
      startedAt: null,
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      streamUrl: "ws://relay/viewer?token=abc",
    });
    playerReturn.state = "connected";
    playerReturn.stalled = true;
    renderTile();

    expect(await screen.findByText("No signal")).toBeInTheDocument();
    expect(screen.getByTestId("live-video")).toBeInTheDocument();
  });

  it("shows an Error badge, isolated to this tile, when its own request fails", async () => {
    vi.mocked(requestLiveVideo).mockRejectedValue(new Error("boom"));
    renderTile();

    expect(await screen.findByText("Error")).toBeInTheDocument();
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("does not throw when the fullscreen control is activated in an environment without the Fullscreen API", async () => {
    vi.mocked(requestLiveVideo).mockImplementation(() => new Promise(() => {}));
    renderTile();
    const button = screen.getByRole("button", { name: /fullscreen/i });
    await userEvent.click(button);
    expect(button).toBeInTheDocument();
  });
});
