import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

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

import { requestLiveVideo, stopVideoSession } from "./api";
import { useVideoSessionController } from "./useVideoSessionController";

const SESSION = {
  id: "session-1",
  organizationId: "org-1",
  deviceId: "device-1",
  cameraId: "camera-1",
  purpose: "live" as const,
  requestedBy: "user-1",
  windowStart: null,
  windowEnd: null,
  status: "requested" as const,
  startedAt: null,
  endedAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  streamUrl: "ws://relay/viewer?token=abc",
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useVideoSessionController", () => {
  beforeEach(() => {
    vi.mocked(requestLiveVideo).mockReset();
    vi.mocked(stopVideoSession).mockReset().mockResolvedValue({ ...SESSION, status: "ended" });
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
  });

  it("cannot start while either id is null, regardless of player state", () => {
    const { result } = renderHook(() => useVideoSessionController(null, "camera-1"), { wrapper });
    expect(result.current.canStart).toBe(false);
    expect(result.current.phase).toBe("idle");
  });

  it("requests a session with exactly the given device/camera ids and reflects the requesting phase", async () => {
    vi.mocked(requestLiveVideo).mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("requesting"));
    expect(requestLiveVideo).toHaveBeenCalledWith("device-1", "camera-1");
  });

  it("reaches 'connected' once the session exists and the player reports connected", async () => {
    vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("connected"));
    expect(result.current.canStop).toBe(true);
  });

  it("shows 'unavailable' rather than a permanent fake 'connecting' when the session carries no streamUrl", async () => {
    vi.mocked(requestLiveVideo).mockResolvedValue({ ...SESSION, streamUrl: null });
    const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("unavailable"));
  });

  it("maps a 500 to 'unavailable' rather than a generic error", async () => {
    const apiErrorModule = await import("../../shared/api/types");
    vi.mocked(requestLiveVideo).mockRejectedValue(
      new apiErrorModule.ApiError(500, { code: "INTERNAL_ERROR", message: "boom", correlationId: null }),
    );
    const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("unavailable"));
  });

  it("resets the session when deviceId/cameraId change, abandoning the previous stream", async () => {
    vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result, rerender } = renderHook(
      ({ deviceId }: { deviceId: string }) => useVideoSessionController(deviceId, "camera-1"),
      { wrapper, initialProps: { deviceId: "device-1" } },
    );
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    rerender({ deviceId: "device-2" });

    await waitFor(() => expect(stopVideoSession).toHaveBeenCalledWith(SESSION.id));
    expect(result.current.phase).toBe("idle");
  });

  it("stopping is idempotent — a repeated call after an explicit stop does not call the API again", async () => {
    vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result, unmount } = renderHook(() => useVideoSessionController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    await act(async () => {
      await result.current.stop();
    });
    expect(stopVideoSession).toHaveBeenCalledTimes(1);

    unmount();
    expect(stopVideoSession).toHaveBeenCalledTimes(1);
  });
});
