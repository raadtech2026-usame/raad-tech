import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  requestIntercom: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const playerReturn: { state: string; errorMessage: string | null } = {
  state: "idle",
  errorMessage: null,
};
vi.mock("./useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import { requestIntercom, stopVideoSession } from "./api";
import { IntercomControl } from "./IntercomControl";

const SESSION = {
  id: "session-1",
  organizationId: "org-1",
  deviceId: "device-1",
  cameraId: "camera-1",
  purpose: "intercom" as const,
  requestedBy: "user-1",
  windowStart: null,
  windowEnd: null,
  status: "requested" as const,
  startedAt: null,
  endedAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  streamUrl: "ws://relay/viewer?token=viewer-abc",
  uplinkUrl: "ws://relay/viewer?token=uplink-abc",
};

function renderControl() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <IntercomControl deviceId="device-1" cameraId="camera-1" />
    </QueryClientProvider>,
  );
}

describe("IntercomControl", () => {
  beforeEach(() => {
    vi.mocked(requestIntercom).mockReset();
    vi.mocked(stopVideoSession).mockReset().mockResolvedValue({ ...SESSION, status: "ended" });
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
  });

  it("shows a 'Talk to Driver' button, not a video-shaped control, when idle", () => {
    renderControl();
    expect(screen.getByRole("button", { name: "Talk to Driver" })).toBeInTheDocument();
    expect(screen.queryByText(/Talking/)).not.toBeInTheDocument();
  });

  it("clicking Talk to Driver requests an intercom session for the given device/camera", async () => {
    vi.mocked(requestIntercom).mockImplementation(() => new Promise(() => {}));
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: "Talk to Driver" }));

    await waitFor(() => expect(requestIntercom).toHaveBeenCalledWith("device-1", "camera-1"));
    expect(await screen.findByText("Connecting intercom…")).toBeInTheDocument();
  });

  it("once connected, shows the TALK button and End Intercom, never a fake video badge", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: "Talk to Driver" }));

    expect(await screen.findByText("Intercom connected")).toBeInTheDocument();
    // Click-to-talk (2026-09-03): a single activation, no press-and-hold.
    expect(screen.getByRole("button", { name: /Talk to the driver/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End Intercom" })).toBeInTheDocument();
  });

  it("normal operation shows NO microphone device controls", async () => {
    // Product requirement: the successful flow requires zero microphone selection. Device
    // controls are an exception path only.
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    renderControl();
    await userEvent.click(screen.getByRole("button", { name: "Talk to Driver" }));
    await screen.findByText("Intercom connected");

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/Choose another microphone/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Change$/)).not.toBeInTheDocument();
    expect(screen.getByText("Microphone ready")).toBeInTheDocument();
  });

  it("clicking End Intercom stops the session", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    renderControl();
    await userEvent.click(screen.getByRole("button", { name: "Talk to Driver" }));
    await screen.findByRole("button", { name: "End Intercom" });

    await userEvent.click(screen.getByRole("button", { name: "End Intercom" }));

    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledWith("session-1", undefined));
  });

  it("shows a distinct 'already in use' message on a 409, not a generic error", async () => {
    const apiErrorModule = await import("../../shared/api/types");
    vi.mocked(requestIntercom).mockRejectedValue(
      new apiErrorModule.ApiError(409, { code: "CONFLICT", message: "in use", correlationId: null }),
    );
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: "Talk to Driver" }));

    expect(await screen.findByText("Another operator is talking to this bus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("is disabled when no device/camera is resolved yet", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <IntercomControl deviceId={null} cameraId={null} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Talk to Driver" })).toBeDisabled();
  });
});
