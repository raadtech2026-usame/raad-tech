import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  requestLiveVideo: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const playerReturn: { state: string; errorMessage: string | null } = {
  state: "idle",
  errorMessage: null,
};
vi.mock("./useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import { requestLiveVideo, stopVideoSession, type LiveStreamType, type VideoSession } from "./api";
import { MultiCameraVideoPanel } from "./MultiCameraVideoPanel";

const CAMERAS_4 = [
  { id: "cam-1", channelNo: 1, position: "road_facing" as const, label: "Front" },
  { id: "cam-2", channelNo: 2, position: "in_cabin" as const, label: "Cabin" },
  { id: "cam-3", channelNo: 3, position: "other" as const, label: "Rear" },
  { id: "cam-4", channelNo: 4, position: "other" as const, label: "Side" },
];

function sessionFor(deviceId: string, cameraId: string): VideoSession {
  return {
    id: `session-${cameraId}`,
    organizationId: "org-1",
    deviceId,
    cameraId,
    purpose: "live",
    requestedBy: "user-1",
    windowStart: null,
    windowEnd: null,
    status: "requested",
    startedAt: null,
    endedAt: null,
    createdAt: "2026-01-01T00:00:00Z",
    streamUrl: `ws://relay/viewer?token=${cameraId}`,
  };
}

function renderPanel(cameras = CAMERAS_4, deviceOnline = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MultiCameraVideoPanel deviceId="device-1" cameras={cameras} deviceOnline={deviceOnline} />
    </QueryClientProvider>,
  );
}

describe("MultiCameraVideoPanel", () => {
  beforeEach(() => {
    vi.mocked(requestLiveVideo).mockReset();
    vi.mocked(stopVideoSession).mockReset().mockResolvedValue({ ...sessionFor("device-1", "cam-1"), status: "ended" });
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
  });

  it("shows an honest empty state and disables Start Live when the device reports no cameras", async () => {
    renderPanel([]);
    expect(await screen.findByText("No camera channels configured")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Live" })).toBeDisabled();
  });

  it("shows a 'ready' idle state and mounts no camera tiles before Start Live is pressed", async () => {
    renderPanel();
    expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
    expect(screen.queryByText("Channel 1")).not.toBeInTheDocument();
    expect(requestLiveVideo).not.toHaveBeenCalled();
  });

  it("requests a live session for every camera the device reports on Start Live — data-driven, not hardcoded", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(4));
    for (const camera of CAMERAS_4) {
      // A multi-camera wall asks every tile for the low-bitrate sub stream (ADR-0043).
      expect(requestLiveVideo).toHaveBeenCalledWith("device-1", camera.id, "sub");
    }
    expect(screen.getAllByText(/^Channel \d$/)).toHaveLength(4);
  });

  it("renders a two-camera device as a 2-up wall, both on the sub stream (CH1/CH3 install)", async () => {
    // This bus has two physical cameras (channels 1 and 3); the MDVR still reports four
    // channels, so the panel must lay out whatever it is given, not assume four.
    const twoCameras = [CAMERAS_4[0], CAMERAS_4[2]];
    vi.mocked(requestLiveVideo).mockImplementation(
      (deviceId: string, cameraId: string, streamType?: LiveStreamType) =>
        Promise.resolve({ ...sessionFor(deviceId, cameraId), id: `session-${cameraId}-${streamType}` }),
    );
    const { container } = renderPanel(twoCameras);

    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(2));
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "cam-1", "sub");
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "cam-3", "sub");
    expect(screen.getAllByText(/^Channel \d$/)).toHaveLength(2);
    const wall = container.querySelector("[data-mode]");
    expect(wall).toHaveAttribute("data-mode", "grid");
    expect(wall).toHaveAttribute("data-count", "2");

    // Focusing one camera restarts only that one, on the main stream; the other keeps its session.
    await userEvent.click(screen.getByRole("button", { name: "View Rear in focus mode" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(3));
    expect(requestLiveVideo).toHaveBeenLastCalledWith("device-1", "cam-3", "main");
    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledWith("session-cam-3-sub"));
    expect(stopVideoSession).toHaveBeenCalledTimes(1);
    expect(container.querySelector("[data-mode]")).toHaveAttribute("data-mode", "focus");
  });

  it("restarts only the focused camera on the main stream, and back to sub when leaving focus (ADR-0043)", async () => {
    vi.mocked(requestLiveVideo).mockImplementation(
      (deviceId: string, cameraId: string, streamType?: LiveStreamType) =>
        Promise.resolve({ ...sessionFor(deviceId, cameraId), id: `session-${cameraId}-${streamType}` }),
    );
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(4));

    await userEvent.click(screen.getByRole("button", { name: "View Rear in focus mode" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(5));
    expect(requestLiveVideo).toHaveBeenLastCalledWith("device-1", "cam-3", "main");
    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledWith("session-cam-3-sub"));
    // Only the focused tile was restarted; the other three kept their sub-stream sessions.
    expect(stopVideoSession).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /Back to grid/ }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(6));
    expect(requestLiveVideo).toHaveBeenLastCalledWith("device-1", "cam-3", "sub");
    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledWith("session-cam-3-main"));
  });

  it("renders a single full-width tile for a device with exactly one camera — never assumes four", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    renderPanel([CAMERAS_4[0]]);

    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(1));
    // A device's only camera gets the main stream (ADR-0043).
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "cam-1", "main");
    expect(screen.getAllByText(/^Channel \d$/)).toHaveLength(1);
  });

  it("isolates a single camera's failure — shows an aggregate N/M Live count, not a full-panel failure", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      cameraId === "cam-3"
        ? Promise.reject(new Error("relay unreachable"))
        : Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    playerReturn.state = "connected";
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    expect(await screen.findByText("3/4 Live")).toBeInTheDocument();
    expect(await screen.findAllByTestId("live-video")).toHaveLength(3);
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("Stop Live tears down every open session and returns to the idle state", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    playerReturn.state = "connected";
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await screen.findAllByTestId("live-video");

    await userEvent.click(screen.getByRole("button", { name: "Stop Live" }));

    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledTimes(4));
    for (const camera of CAMERAS_4) {
      expect(stopVideoSession).toHaveBeenCalledWith(`session-${camera.id}`);
    }
    expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
    expect(screen.queryByTestId("live-video")).not.toBeInTheDocument();
  });

  it("shows a non-blocking offline hint without disabling Start Live", async () => {
    renderPanel(CAMERAS_4, false);
    expect(await screen.findByText(/last reported offline/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Live" })).not.toBeDisabled();
  });

  it("resets to idle when the device id changes, never carrying a stale session into a new vehicle's device", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    playerReturn.state = "connected";
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MultiCameraVideoPanel deviceId="device-1" cameras={CAMERAS_4} deviceOnline />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    await screen.findAllByTestId("live-video");

    rerender(
      <QueryClientProvider client={queryClient}>
        <MultiCameraVideoPanel deviceId="device-2" cameras={CAMERAS_4} deviceOnline />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
    expect(screen.queryByTestId("live-video")).not.toBeInTheDocument();
  });

  describe("installed cameras only (ADR-0046)", () => {
    const withSignal = (present: number[]) =>
      CAMERAS_4.map((camera) => ({
        ...camera,
        videoSignal: present.includes(camera.channelNo) ? ("present" as const) : ("absent" as const),
      }));

    async function startLive(): Promise<void> {
      vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
        Promise.resolve(sessionFor(deviceId, cameraId)),
      );
      await userEvent.click(screen.getByRole("button", { name: "Start Live" }));
    }

    it("CH1 + CH3 installed: two tiles, two requests, CH2/CH4 named as not connected", async () => {
      renderPanel(withSignal([1, 3]));
      expect(await screen.findByText("2 cameras ready")).toBeInTheDocument();
      expect(screen.getByTestId("cameras-not-connected")).toHaveTextContent("CH2, CH4 · Camera not connected");
      await startLive();
      await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(2));
      const requested = vi.mocked(requestLiveVideo).mock.calls.map((call) => call[1]).sort();
      expect(requested).toEqual(["cam-1", "cam-3"]);
      expect(screen.queryByText("Channel 2")).not.toBeInTheDocument();
      expect(screen.queryByText("Channel 4")).not.toBeInTheDocument();
    });

    it("a camera later connected to CH2 is presented without any code change", async () => {
      const { rerender } = renderPanel(withSignal([1, 3]));
      expect(await screen.findByText("2 cameras ready")).toBeInTheDocument();
      const queryClient = new QueryClient();
      rerender(
        <QueryClientProvider client={queryClient}>
          <MultiCameraVideoPanel deviceId="device-1" cameras={withSignal([1, 2, 3])} deviceOnline />
        </QueryClientProvider>,
      );
      expect(await screen.findByText("3 cameras ready")).toBeInTheDocument();
      expect(screen.getByTestId("cameras-not-connected")).toHaveTextContent("CH4 · Camera not connected");
    });

    it("all four connected: four tiles and no not-connected note", async () => {
      renderPanel(withSignal([1, 2, 3, 4]));
      expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
      expect(screen.queryByTestId("cameras-not-connected")).not.toBeInTheDocument();
    });

    it("a single connected camera gets the main stream (the only-camera rule applies to installed cameras)", async () => {
      renderPanel(withSignal([3]));
      expect(await screen.findByText("1 camera ready")).toBeInTheDocument();
      await startLive();
      await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(1));
      expect(vi.mocked(requestLiveVideo).mock.calls[0].slice(1)).toEqual(["cam-3", "main" as LiveStreamType]);
    });

    it("no camera connected at all: says so and requests nothing", async () => {
      renderPanel(withSignal([]));
      expect(await screen.findByText("No camera connected")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start Live" })).toBeDisabled();
      expect(requestLiveVideo).not.toHaveBeenCalled();
    });

    it("an unreported (unknown) camera is still offered, exactly as before", async () => {
      renderPanel(CAMERAS_4.map((camera) => ({ ...camera, videoSignal: "unknown" as const })));
      expect(await screen.findByText("4 cameras ready")).toBeInTheDocument();
    });
  });
});
