import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listDevicesForVideoPicker: vi.fn(),
  searchRecordings: vi.fn(),
  getRecordingSearch: vi.fn(),
  requestPlaybackVideo: vi.fn(),
  controlPlayback: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const playerReturn: { state: string; errorMessage: string | null } = {
  state: "idle",
  errorMessage: null,
};
vi.mock("./useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import * as api from "./api";
import { RecordingsPage } from "./RecordingsPage";

const DEVICE = {
  id: "01DEVICE0000000000000000A",
  terminalId: "TERM12345678",
  model: "LSZ-C5804DG-Q-F",
  vendor: "LSZ",
  lifecycleState: "assigned" as const,
  cameras: [
    {
      id: "01CAMERA000000000000000A",
      channelNo: 1,
      position: "road_facing" as const,
      label: "Front",
    },
  ],
};

const SEGMENT = {
  channelNo: 1,
  startTime: "2026-09-21T08:00:00Z",
  endTime: "2026-09-21T08:30:00Z",
  alarmFlag: 0,
  resourceType: 0,
  streamType: 0,
  storageType: 1,
  sizeBytes: 104_857_600,
};

const PLAYBACK_SESSION = {
  id: "01SESSION000000000000000A",
  organizationId: "01ORG00000000000000000000",
  deviceId: DEVICE.id,
  cameraId: DEVICE.cameras[0].id,
  purpose: "playback" as const,
  requestedBy: "01USER00000000000000000A",
  windowStart: SEGMENT.startTime,
  windowEnd: SEGMENT.endTime,
  status: "requested" as const,
  startedAt: null,
  endedAt: null,
  createdAt: "2026-09-21T09:00:00Z",
  streamUrl: "ws://jt1078-relay:7911/viewer?token=abc123",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RecordingsPage />
    </QueryClientProvider>,
  );
}

async function selectDeviceAndCamera() {
  await userEvent.selectOptions(await screen.findByLabelText("Device"), DEVICE.id);
  await userEvent.selectOptions(screen.getByLabelText("Camera"), DEVICE.cameras[0].id);
}

describe("RecordingsPage (ADR-0044)", () => {
  beforeEach(() => {
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
    vi.mocked(api.listDevicesForVideoPicker).mockReset().mockResolvedValue([DEVICE]);
    vi.mocked(api.searchRecordings).mockReset();
    vi.mocked(api.getRecordingSearch).mockReset();
    vi.mocked(api.requestPlaybackVideo).mockReset();
    vi.mocked(api.controlPlayback).mockReset();
    vi.mocked(api.stopVideoSession).mockReset().mockResolvedValue({
      ...PLAYBACK_SESSION,
      status: "ended" as const,
    });
  });

  it("cannot search before a camera is chosen", async () => {
    renderPage();
    await screen.findByLabelText("Device");

    expect(screen.getByRole("button", { name: "Search recordings" })).toBeDisabled();
  });

  it("asks the device for its recordings over the chosen window", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "01SEARCH0000000000000000A",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "01SEARCH0000000000000000A",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    renderPage();
    await selectDeviceAndCamera();

    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));

    await waitFor(() => expect(api.searchRecordings).toHaveBeenCalledTimes(1));
    const [deviceId, cameraId, windowStart, windowEnd] = vi.mocked(api.searchRecordings).mock
      .calls[0];
    expect(deviceId).toBe(DEVICE.id);
    expect(cameraId).toBe(DEVICE.cameras[0].id);
    // The picker collects local wall-clock times; the API takes ISO-8601 instants.
    expect(windowStart).toMatch(/Z$/);
    expect(windowEnd).toMatch(/Z$/);
    expect(new Date(windowStart).getTime()).toBeLessThan(new Date(windowEnd).getTime());
  });

  it("says it is waiting while the device has not answered", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    renderPage();
    await selectDeviceAndCamera();

    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));

    expect(await screen.findByText(/Waiting for the device to answer/)).toBeInTheDocument();
  });

  it("reports an empty answer as the device's own answer, not as still waiting", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "ready",
      segments: [],
    });
    renderPage();
    await selectDeviceAndCamera();

    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));

    expect(
      await screen.findByText(/reports no recordings in this window/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for the device/)).not.toBeInTheDocument();
  });

  it("lists what the device reported and plays the chosen segment back from it", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "ready",
      segments: [SEGMENT],
    });
    vi.mocked(api.requestPlaybackVideo).mockResolvedValue(PLAYBACK_SESSION);
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));

    const segmentButton = await screen.findByRole("button", { name: /Channel 1/ });
    await userEvent.click(segmentButton);

    await waitFor(() =>
      expect(api.requestPlaybackVideo).toHaveBeenCalledWith(
        DEVICE.id,
        DEVICE.cameras[0].id,
        SEGMENT.startTime,
        SEGMENT.endTime,
      ),
    );
  });

  it("sends a transport command without claiming the picture changed", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "ready",
      segments: [SEGMENT],
    });
    vi.mocked(api.requestPlaybackVideo).mockResolvedValue(PLAYBACK_SESSION);
    vi.mocked(api.controlPlayback).mockResolvedValue(PLAYBACK_SESSION);
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));
    await userEvent.click(await screen.findByRole("button", { name: /Channel 1/ }));

    await waitFor(() => expect(api.requestPlaybackVideo).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));

    await waitFor(() =>
      expect(api.controlPlayback).toHaveBeenCalledWith(PLAYBACK_SESSION.id, "pause", undefined),
    );
    // The page must not render a "Paused" state - only the device knows whether it obeyed.
    expect(screen.queryByText(/^Paused$/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/depends on the device's firmware/),
    ).toBeInTheDocument();
  });

  it("forwards the chosen speed with a fast-forward command", async () => {
    vi.mocked(api.searchRecordings).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "pending",
      segments: null,
    });
    vi.mocked(api.getRecordingSearch).mockResolvedValue({
      searchId: "s-1",
      deviceId: DEVICE.id,
      status: "ready",
      segments: [SEGMENT],
    });
    vi.mocked(api.requestPlaybackVideo).mockResolvedValue(PLAYBACK_SESSION);
    vi.mocked(api.controlPlayback).mockResolvedValue(PLAYBACK_SESSION);
    renderPage();
    await selectDeviceAndCamera();
    await userEvent.click(screen.getByRole("button", { name: "Search recordings" }));
    await userEvent.click(await screen.findByRole("button", { name: /Channel 1/ }));
    await waitFor(() => expect(api.requestPlaybackVideo).toHaveBeenCalled());

    await userEvent.selectOptions(screen.getByLabelText("Speed"), "4");
    await userEvent.click(screen.getByRole("button", { name: "Fast forward" }));

    await waitFor(() =>
      expect(api.controlPlayback).toHaveBeenCalledWith(PLAYBACK_SESSION.id, "fast_forward", {
        speed: 4,
      }),
    );
  });

  it("offers no transport controls until a segment is playing", async () => {
    renderPage();
    await selectDeviceAndCamera();

    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.getByText("No recording selected")).toBeInTheDocument();
  });
});
