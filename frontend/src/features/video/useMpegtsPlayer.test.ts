import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMpegtsPlayer } from "./useMpegtsPlayer";

type Handler = (...args: unknown[]) => void;

const { FakePlayer, EVENTS } = vi.hoisted(() => {
  class FakePlayer {
    static instances: FakePlayer[] = [];
    mediaDataSource: unknown;
    config: unknown;
    attached: unknown = null;
    destroyed = false;
    listeners: Record<string, Handler[]> = {};

    constructor(mediaDataSource: unknown, config: unknown) {
      this.mediaDataSource = mediaDataSource;
      this.config = config;
      FakePlayer.instances.push(this);
    }

    on(event: string, handler: Handler): void {
      (this.listeners[event] ??= []).push(handler);
    }
    off(event: string, handler: Handler): void {
      this.listeners[event] = (this.listeners[event] ?? []).filter((h) => h !== handler);
    }
    attachMediaElement(element: unknown): void {
      this.attached = element;
    }
    detachMediaElement(): void {
      this.attached = null;
    }
    load(): void {}
    play(): Promise<void> {
      return Promise.resolve();
    }
    pause(): void {}
    unload(): void {}
    destroy(): void {
      this.destroyed = true;
    }

    emit(event: string, ...args: unknown[]): void {
      this.listeners[event]?.forEach((h) => h(...args));
    }
  }

  const EVENTS = { ERROR: "error", MEDIA_INFO: "media_info", LOADING_COMPLETE: "loading_complete" };

  return { FakePlayer, EVENTS };
});

vi.mock("mpegts.js", () => ({
  default: {
    isSupported: () => true,
    createPlayer: (mediaDataSource: unknown, config: unknown) => new FakePlayer(mediaDataSource, config),
    Events: EVENTS,
  },
}));

const STREAM_URL = "ws://jt1078-relay:7911/viewer?token=abc123";

function makeVideoRef() {
  return { current: document.createElement("video") };
}

/** A media element whose playback position and paused-ness the test drives directly. jsdom does
 * not actually decode anything, so `currentTime` never advances on its own — which is exactly
 * the condition the stall detector looks for, and therefore must be simulated deliberately
 * rather than left to jsdom's defaults. */
function makeControllableVideoRef(): {
  ref: { current: HTMLMediaElement };
  setPosition: (seconds: number) => void;
  setPaused: (paused: boolean) => void;
} {
  const element = document.createElement("video");
  let position = 0;
  let paused = false;
  Object.defineProperty(element, "currentTime", { get: () => position, configurable: true });
  Object.defineProperty(element, "paused", { get: () => paused, configurable: true });
  return {
    ref: { current: element as HTMLMediaElement },
    setPosition: (seconds) => { position = seconds; },
    setPaused: (value) => { paused = value; },
  };
}

describe("useMpegtsPlayer", () => {
  beforeEach(() => {
    FakePlayer.instances = [];
  });

  it("stays idle and creates no player when streamUrl is null", () => {
    const { result } = renderHook(() => useMpegtsPlayer(null, makeVideoRef()));

    expect(result.current).toEqual({ state: "idle", errorMessage: null, stalled: false });
    expect(FakePlayer.instances).toHaveLength(0);
  });

  it("creates a live FLV player against the relay's WS URL and starts connecting", () => {
    const videoRef = makeVideoRef();
    const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, videoRef));

    expect(FakePlayer.instances).toHaveLength(1);
    expect(FakePlayer.instances[0].mediaDataSource).toEqual({
      type: "flv",
      isLive: true,
      url: STREAM_URL,
      hasVideo: true,
    });
    // `hasAudio` is deliberately omitted, not set to `false` - mpegts.js auto-detects it
    // per-stream (see the hook's own comment) so a video-only channel keeps working exactly
    // as before, while a channel that actually streams audio (the G.711A fix) is picked up too.
    expect(FakePlayer.instances[0].mediaDataSource).not.toHaveProperty("hasAudio");
    expect(result.current.state).toBe("connecting");
  });

  it("attaches the player to the given video element and loads/plays it", () => {
    const videoRef = makeVideoRef();
    renderHook(() => useMpegtsPlayer(STREAM_URL, videoRef));

    expect(FakePlayer.instances[0].attached).toBe(videoRef.current);
  });

  it("transitions to connected once MEDIA_INFO arrives", () => {
    const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, makeVideoRef()));
    const player = FakePlayer.instances[0];

    act(() => player.emit(EVENTS.MEDIA_INFO, {}));

    expect(result.current.state).toBe("connected");
  });

  it("transitions to error on Events.ERROR and captures a message", () => {
    const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, makeVideoRef()));
    const player = FakePlayer.instances[0];

    act(() => player.emit(EVENTS.ERROR, "NetworkError", "CONNECTING_TIMEOUT", { code: -1 }));

    expect(result.current.state).toBe("error");
    expect(result.current.errorMessage).toContain("NetworkError");
  });

  it("transitions to closed on LOADING_COMPLETE — the relay's close code isn't recoverable through this library", () => {
    const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, makeVideoRef()));
    const player = FakePlayer.instances[0];

    act(() => player.emit(EVENTS.LOADING_COMPLETE));

    expect(result.current.state).toBe("closed");
  });

  it("does not overwrite an already-reported error with a trailing LOADING_COMPLETE", () => {
    const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, makeVideoRef()));
    const player = FakePlayer.instances[0];

    act(() => player.emit(EVENTS.ERROR, "MediaError", "MEDIA_MSE_ERROR", {}));
    act(() => player.emit(EVENTS.LOADING_COMPLETE));

    expect(result.current.state).toBe("error");
  });

  it("tears down the old player and creates a fresh one when streamUrl changes", () => {
    const videoRef = makeVideoRef();
    const { rerender } = renderHook(({ url }) => useMpegtsPlayer(url, videoRef), {
      initialProps: { url: STREAM_URL as string | null },
    });
    const firstPlayer = FakePlayer.instances[0];

    rerender({ url: "ws://jt1078-relay:7911/viewer?token=different" });

    expect(firstPlayer.destroyed).toBe(true);
    expect(FakePlayer.instances).toHaveLength(2);
  });

  it("tears the player down on unmount", () => {
    const { unmount } = renderHook(() => useMpegtsPlayer(STREAM_URL, makeVideoRef()));
    const player = FakePlayer.instances[0];

    unmount();

    expect(player.destroyed).toBe(true);
    expect(player.attached).toBeNull();
  });

  describe("frozen-picture (stall) detection", () => {
    // Live-verified 2026-09-02: a radio-link outage stops media at the device while the viewer
    // WebSocket stays open (median 28s, max 93s), so `state` stayed "connected" over a frozen
    // image. `currentTime` is the honest signal - it is the decoder's own progress.
    it("is not stalled before the player has connected", () => {
      const { ref } = makeControllableVideoRef();
      const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, ref));
      expect(result.current.stalled).toBe(false);
    });

    it("reports stalled once the playback position stops advancing", () => {
      vi.useFakeTimers();
      try {
        const { ref, setPosition } = makeControllableVideoRef();
        const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, ref));
        act(() => FakePlayer.instances[0].emit(EVENTS.MEDIA_INFO, {}));
        expect(result.current.state).toBe("connected");

        setPosition(1);
        act(() => { vi.advanceTimersByTime(1000); });
        expect(result.current.stalled).toBe(false);

        // Position frozen from here on - the picture is stuck.
        act(() => { vi.advanceTimersByTime(4000); });
        expect(result.current.stalled).toBe(true);
      } finally {
        vi.useRealTimers();
      }
    });

    it("clears stalled as soon as the position advances again", () => {
      vi.useFakeTimers();
      try {
        const { ref, setPosition } = makeControllableVideoRef();
        const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, ref));
        act(() => FakePlayer.instances[0].emit(EVENTS.MEDIA_INFO, {}));
        act(() => { vi.advanceTimersByTime(4000); });
        expect(result.current.stalled).toBe(true);

        setPosition(9);
        act(() => { vi.advanceTimersByTime(1000); });
        expect(result.current.stalled).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("does not report a deliberately paused element as stalled", () => {
      // The operator pausing a tile themselves is not a loss of signal, and reporting it as
      // "No signal" would be a lie.
      vi.useFakeTimers();
      try {
        const { ref, setPaused } = makeControllableVideoRef();
        const { result } = renderHook(() => useMpegtsPlayer(STREAM_URL, ref));
        act(() => FakePlayer.instances[0].emit(EVENTS.MEDIA_INFO, {}));
        setPaused(true);

        act(() => { vi.advanceTimersByTime(10000); });

        expect(result.current.stalled).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
