import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

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
    playerReturn.stalled = false;
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

  describe("Phase 6 — auto-recovery from an unexpected close", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("automatically requests a fresh session after an unexpected close, bounded to RECONNECT_MAX_ATTEMPTS", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));
      expect(requestLiveVideo).toHaveBeenCalledTimes(1);

      vi.useFakeTimers();
      // Never reconnects while backgrounded (asserted in a dedicated test below) - keep this
      // test's own timer-advance assertions unambiguous by staying "visible" throughout.
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });

      const expectedDelaysMs = [5000, 10000, 20000]; // RECONNECT_BASE_DELAY_MS * 2**attempt
      for (let attempt = 0; attempt < expectedDelaysMs.length; attempt++) {
        // The (mocked) player reports the unexpected close.
        playerReturn.state = "closed";
        act(() => rerender());
        expect(result.current.phase).toBe("unavailable"); // shown immediately, recovery is silent

        await act(async () => {
          await vi.advanceTimersByTimeAsync(expectedDelaysMs[attempt]);
        });
        expect(requestLiveVideo).toHaveBeenCalledTimes(attempt + 2); // +1 for the initial start()

        // The reconnect's own fresh session starts connecting - this is what lets the *next*
        // close (if any) be recognized as a new occurrence, not a still-scheduled old one; the
        // real (unmocked) `useMpegtsPlayer` makes this same "closed" -> "connecting" transition
        // itself the instant `streamUrl` changes to the new session's own URL.
        playerReturn.state = "connecting";
        act(() => rerender());
      }

      // The retry budget (RECONNECT_MAX_ATTEMPTS = 3) is now exhausted - a further close must
      // NOT schedule another attempt.
      playerReturn.state = "closed";
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(expectedDelaysMs.length + 1); // unchanged
    });

    it("never auto-reconnects after a user-initiated stop", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(async () => {
        await result.current.stop();
      });
      expect(result.current.phase).toBe("stopped");

      vi.useFakeTimers();
      playerReturn.state = "closed"; // e.g. the relay's own close racing the stop request
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(requestLiveVideo).toHaveBeenCalledTimes(1); // never a second, auto-triggered call
    });

    it("a momentary connect does NOT refill the retry budget - only a stable one does", async () => {
      // The real defect behind the observed unbounded reconnect loop: the budget used to reset
      // the instant `player.state` touched "connected", so a session that connected and died
      // seconds later refilled the budget it had just spent, forever. RECONNECT_STABILITY_MS
      // (45s) must elapse while continuously connected before the budget is considered earned.
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));
      expect(requestLiveVideo).toHaveBeenCalledTimes(1);

      vi.useFakeTimers();
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });

      const delays = [5000, 10000, 20000];
      for (let attempt = 0; attempt < delays.length; attempt++) {
        playerReturn.state = "closed";
        act(() => rerender());
        await act(async () => {
          await vi.advanceTimersByTimeAsync(delays[attempt]);
        });
        expect(requestLiveVideo).toHaveBeenCalledTimes(attempt + 2);

        playerReturn.state = "connected"; // a brief blip, nowhere near 45s
        act(() => rerender());
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1000);
        });
      }

      // Budget spent. A further close must NOT reconnect, despite each retry having briefly
      // reached "connected" - the old behaviour would have looped here indefinitely.
      playerReturn.state = "closed";
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(120_000);
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(delays.length + 1);
    });

    it("a genuinely stable connection DOES refill the retry budget", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      vi.useFakeTimers();
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });

      playerReturn.state = "closed";
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(2);

      // Stay connected past the stability window - the budget is earned back.
      playerReturn.state = "connected";
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(46_000);
      });

      // ...so the next close gets the *first* (shortest) delay again, not an escalated one.
      playerReturn.state = "closed";
      act(() => rerender());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(3);
    });

    it("does not consume a retry attempt while the tab is backgrounded, and reconnects once it becomes visible", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));
      expect(requestLiveVideo).toHaveBeenCalledTimes(1);

      vi.useFakeTimers();
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
      playerReturn.state = "closed";
      act(() => rerender());

      // Backgrounded - no timer-based reconnect should fire no matter how long we wait.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(1);

      // Tab becomes visible again - reconnects immediately, without needing another close event.
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(requestLiveVideo).toHaveBeenCalledTimes(2);
    });
  });

  describe("frozen-picture phase", () => {
    it("reports 'stalled', not 'connected', when the picture has stopped advancing", async () => {
      // Live-verified 2026-09-02: the relay's viewer socket stays open for a median of 28s after
      // media stops, so `player.state` remains "connected" over a frozen image. Surfacing that
      // as "Live" is the false confidence this phase exists to correct.
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      playerReturn.stalled = true;
      const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), {
        wrapper,
      });

      act(() => result.current.start());

      await waitFor(() => expect(result.current.phase).toBe("stalled"));
    });

    it("still allows stopping a stalled session", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      playerReturn.stalled = true;
      const { result } = renderHook(() => useVideoSessionController("device-1", "camera-1"), {
        wrapper,
      });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("stalled"));

      expect(result.current.canStop).toBe(true);
      expect(result.current.canStart).toBe(false);
    });

    it("returns to 'connected' once frames resume", async () => {
      vi.mocked(requestLiveVideo).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      playerReturn.stalled = true;
      const { result, rerender } = renderHook(
        () => useVideoSessionController("device-1", "camera-1"),
        { wrapper },
      );
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("stalled"));

      playerReturn.stalled = false;
      rerender();

      await waitFor(() => expect(result.current.phase).toBe("connected"));
    });
  });
});
