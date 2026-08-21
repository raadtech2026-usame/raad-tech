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

import { requestLiveVideo, stopVideoSession, type VideoSession } from "./api";
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
      expect(requestLiveVideo).toHaveBeenCalledWith("device-1", camera.id);
    }
    expect(screen.getAllByText(/^Channel \d$/)).toHaveLength(4);
  });

  it("renders a single full-width tile for a device with exactly one camera — never assumes four", async () => {
    vi.mocked(requestLiveVideo).mockImplementation((deviceId: string, cameraId: string) =>
      Promise.resolve(sessionFor(deviceId, cameraId)),
    );
    renderPanel([CAMERAS_4[0]]);

    await userEvent.click(screen.getByRole("button", { name: "Start Live" }));

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(1));
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "cam-1");
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
});
