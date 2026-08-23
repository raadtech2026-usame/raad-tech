import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Regression coverage for a real bug found live (2026-08-22): `POST /video/live` genuinely
 * succeeded server-side on every attempt (confirmed against the real backend/relay/device-gateway
 * stack), but the browser never once attempted `new WebSocket(streamUrl)` — `CameraTile`'s mount
 * effect called `session.start()` synchronously, which under React 18 `<StrictMode>` (active in
 * dev, where this was reproduced) loses the mutation's resolution: `useMutation`'s internal
 * subscription is torn down and recreated by StrictMode's synchronous mount/cleanup/remount
 * dance, so a `mutate()` call issued during the first (soon-to-be-discarded) pass never reaches
 * `onSuccess` on the surviving subscription. `isPending` stays stuck `true` forever, `<video>`
 * never mounts, and `useMpegtsPlayer` never gets a real element to attach `mpegts.js` to.
 *
 * Unlike `CameraTile.test.tsx` (which mocks `useMpegtsPlayer` entirely) and
 * `useMpegtsPlayer.test.ts` (which always hands it an already-populated `videoRef`), this test
 * exercises the real integration: an unmocked `useVideoSessionController`/`useMpegtsPlayer`
 * wrapped in the same `<StrictMode>` the real app renders under (`main.tsx`), with only the
 * `mpegts.js` library itself faked — the same level `useMpegtsPlayer.test.ts` fakes it at.
 */

vi.mock("./api", () => ({
  requestLiveVideo: vi.fn(),
  stopVideoSession: vi.fn(),
}));

type Handler = (...args: unknown[]) => void;

const { FakePlayer, EVENTS } = vi.hoisted(() => {
  class FakePlayer {
    static instances: FakePlayer[] = [];
    mediaDataSource: unknown;
    attached: unknown = null;
    listeners: Record<string, Handler[]> = {};
    constructor(mediaDataSource: unknown) {
      this.mediaDataSource = mediaDataSource;
      FakePlayer.instances.push(this);
    }
    on(event: string, handler: Handler): void {
      (this.listeners[event] ??= []).push(handler);
    }
    off(): void {}
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
    destroy(): void {}
  }
  const EVENTS = { ERROR: "error", MEDIA_INFO: "media_info", LOADING_COMPLETE: "loading_complete" };
  return { FakePlayer, EVENTS };
});

vi.mock("mpegts.js", () => ({
  default: {
    isSupported: () => true,
    createPlayer: (mediaDataSource: unknown) => new FakePlayer(mediaDataSource),
    Events: EVENTS,
  },
}));

import { requestLiveVideo } from "./api";
import { CameraTile } from "./CameraTile";

const CAMERA = { id: "cam-1", channelNo: 1, position: "road_facing" as const, label: "Front" };

describe("CameraTile under React StrictMode (real useVideoSessionController + real useMpegtsPlayer)", () => {
  beforeEach(() => {
    FakePlayer.instances = [];
    vi.mocked(requestLiveVideo).mockReset();
  });

  it("still reaches mpegts.createPlayer (and so, eventually, new WebSocket()) once the session resolves", async () => {
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
      streamUrl: "ws://localhost:7911/viewer?token=abc123",
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <CameraTile deviceId="device-1" camera={CAMERA} />
        </QueryClientProvider>
      </StrictMode>,
    );

    await waitFor(() => expect(requestLiveVideo).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(FakePlayer.instances.length).toBeGreaterThan(0));
    expect(FakePlayer.instances[0].mediaDataSource).toMatchObject({
      url: "ws://localhost:7911/viewer?token=abc123",
    });
  });
});
