import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./api", () => ({
  getLatestVehiclePosition: vi.fn(),
}));

type OnMessage = (message: unknown) => void;
let latestOnMessage: OnMessage | null = null;
const mockSend = vi.fn();
const wsReturn: { status: string; lastCloseCode: number | null; send: typeof mockSend } = {
  status: "connecting",
  lastCloseCode: null,
  send: mockSend,
};

vi.mock("../../shared/hooks/useWebSocket", () => ({
  useWebSocketChannel: (_path: string, options: { onMessage: OnMessage }) => {
    latestOnMessage = options.onMessage;
    return wsReturn;
  },
}));

import { getLatestVehiclePosition } from "./api";
import { deriveGpsFixStatus, useVehiclePosition } from "./useVehiclePosition";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useVehiclePosition", () => {
  beforeEach(() => {
    vi.mocked(getLatestVehiclePosition).mockReset().mockResolvedValue(null);
    mockSend.mockClear();
    wsReturn.status = "connecting";
    wsReturn.lastCloseCode = null;
    latestOnMessage = null;
  });

  it("sends the subscribe frame once the socket opens for the given vehicle", () => {
    wsReturn.status = "open";
    renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

    expect(mockSend).toHaveBeenCalledWith({ type: "subscribe", channel: "vehicle", vehicle_id: "vehicle-1" });
  });

  it("turns a matching position frame into livePosition, ignoring frames for a different vehicle", () => {
    wsReturn.status = "open";
    const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

    act(() => {
      latestOnMessage?.({
        type: "position",
        vehicle_id: "vehicle-2",
        lat: 9.9,
        lng: 9.9,
        heading_deg: 0,
        event_time: "2026-01-01T00:00:00Z",
      });
    });
    expect(result.current.livePosition).toBeNull();

    act(() => {
      latestOnMessage?.({
        type: "position",
        vehicle_id: "vehicle-1",
        lat: 2.05,
        lng: 45.32,
        heading_deg: 180,
        event_time: "2026-01-01T00:00:00Z",
      });
    });
    expect(result.current.livePosition).toEqual({
      lat: 2.05,
      lng: 45.32,
      headingDeg: 180,
      eventTime: "2026-01-01T00:00:00Z",
    });
    expect(result.current.hasKnownPosition).toBe(true);
  });

  it("has no device_id anywhere in its return shape — GPS data can never be mistaken for a device identity", () => {
    wsReturn.status = "open";
    const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });
    expect(result.current).not.toHaveProperty("deviceId");

    act(() => {
      latestOnMessage?.({
        type: "position",
        vehicle_id: "vehicle-1",
        lat: 1,
        lng: 1,
        heading_deg: 0,
        event_time: "2026-01-01T00:00:00Z",
      });
    });
    expect(result.current.livePosition).not.toHaveProperty("deviceId");
    expect(Object.keys(result.current.livePosition as object).sort()).toEqual(
      ["eventTime", "headingDeg", "lat", "lng"].sort(),
    );
  });

  it("does not query the snapshot or subscribe when no vehicle is selected", () => {
    renderHook(() => useVehiclePosition(""), { wrapper });
    expect(getLatestVehiclePosition).not.toHaveBeenCalled();
  });

  it("seeds livePosition from the REST snapshot when no live frame has arrived yet", async () => {
    // Root-cause fix (RAAD Live Tracking wrong-location investigation): the snapshot is
    // Redis-backed and, since the backend fix, only ever caches a valid-fix position — so
    // seeding livePosition from it (rather than leaving it null until a WS frame arrives) is
    // exactly what lets "Last GPS update" show a real timestamp on first page load.
    vi.mocked(getLatestVehiclePosition).mockResolvedValue({
      vehicleId: "vehicle-1",
      tripId: null,
      latitude: 1.1,
      longitude: 2.2,
      speedKph: 10,
      headingDeg: 45,
      eventTime: "2026-01-01T00:00:00Z",
      isGpsValid: true,
    });

    const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.hasKnownPosition).toBe(true));
    expect(result.current.livePosition).toEqual({
      lat: 1.1,
      lng: 2.2,
      headingDeg: 45,
      eventTime: "2026-01-01T00:00:00Z",
    });
  });

  it("a live WS frame arriving first is never overwritten by the snapshot resolving later", async () => {
    type SnapshotResult = Awaited<ReturnType<typeof getLatestVehiclePosition>>;
    let resolveSnapshot: (value: SnapshotResult) => void = () => {};
    vi.mocked(getLatestVehiclePosition).mockReturnValue(
      new Promise<SnapshotResult>((resolve) => {
        resolveSnapshot = resolve;
      }),
    );
    wsReturn.status = "open";
    const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

    act(() => {
      latestOnMessage?.({
        type: "position",
        vehicle_id: "vehicle-1",
        lat: 9.9,
        lng: 9.9,
        heading_deg: 0,
        event_time: "2026-01-01T00:10:00Z",
        is_gps_valid: true,
      });
    });
    expect(result.current.livePosition?.lat).toBe(9.9);

    await act(async () => {
      resolveSnapshot({
        vehicleId: "vehicle-1",
        tripId: null,
        latitude: 1.1,
        longitude: 2.2,
        speedKph: 10,
        headingDeg: 45,
        eventTime: "2026-01-01T00:00:00Z",
        isGpsValid: true,
      });
    });

    expect(result.current.livePosition?.lat).toBe(9.9);
  });

  describe("GPS fix validity (root-cause fix, RAAD Live Tracking wrong-location investigation)", () => {
    it("a fix-invalid frame updates lastGpsSignal/gpsFixStatus but never moves livePosition", () => {
      // `gpsFixStatus` compares each event's own timestamp against real wall-clock time
      // (`Date.now()`), so these frames use "just now" timestamps rather than a fixed date —
      // otherwise this assertion would depend on how long ago that fixed date now is.
      const firstEventTime = new Date().toISOString();
      const secondEventTime = new Date(Date.now() + 5000).toISOString();
      wsReturn.status = "open";
      const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

      act(() => {
        latestOnMessage?.({
          type: "position",
          vehicle_id: "vehicle-1",
          lat: 2.05,
          lng: 45.32,
          heading_deg: 0,
          event_time: firstEventTime,
          is_gps_valid: true,
        });
      });
      expect(result.current.livePosition).toEqual({
        lat: 2.05,
        lng: 45.32,
        headingDeg: 0,
        eventTime: firstEventTime,
      });

      act(() => {
        latestOnMessage?.({
          type: "position",
          vehicle_id: "vehicle-1",
          // Real-world regression fixture: this vendor hardware's own cached factory fix.
          lat: 22.676871,
          lng: 114.005251,
          heading_deg: 0,
          event_time: secondEventTime,
          is_gps_valid: false,
        });
      });

      // The marker-driving position never jumps to the fix-invalid coordinate...
      expect(result.current.livePosition).toEqual({
        lat: 2.05,
        lng: 45.32,
        headingDeg: 0,
        eventTime: firstEventTime,
      });
      // ...but the GPS signal/status do reflect the fix-invalid report.
      expect(result.current.lastGpsSignal).toEqual({
        isGpsValid: false,
        eventTime: secondEventTime,
      });
      expect(result.current.gpsFixStatus).toBe("no_fix");
    });

    it("a frame with no is_gps_valid field at all defaults to valid", () => {
      wsReturn.status = "open";
      const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

      act(() => {
        latestOnMessage?.({
          type: "position",
          vehicle_id: "vehicle-1",
          lat: 2.05,
          lng: 45.32,
          heading_deg: 0,
          event_time: new Date().toISOString(),
        });
      });

      expect(result.current.livePosition).not.toBeNull();
      expect(result.current.gpsFixStatus).toBe("live");
    });
  });
});

describe("deriveGpsFixStatus", () => {
  const NOW = new Date("2026-01-01T00:10:00Z").getTime();

  it("is 'no_fix' with no known position and no signal at all", () => {
    expect(deriveGpsFixStatus({ livePosition: null, lastSignal: null, nowMs: NOW })).toBe(
      "no_fix",
    );
  });

  it("is 'live' for a fresh valid position", () => {
    const status = deriveGpsFixStatus({
      livePosition: { lat: 1, lng: 1, headingDeg: 0, eventTime: "2026-01-01T00:09:30Z" },
      lastSignal: null,
      nowMs: NOW,
    });
    expect(status).toBe("live");
  });

  it("is 'stale' once a valid position ages past the live threshold with no fresher signal", () => {
    const status = deriveGpsFixStatus({
      livePosition: { lat: 1, lng: 1, headingDeg: 0, eventTime: "2026-01-01T00:00:00Z" },
      lastSignal: null,
      nowMs: NOW,
    });
    expect(status).toBe("stale");
  });

  it("is 'no_fix' when the most recent signal is invalid and fresh, even with an older valid position", () => {
    const status = deriveGpsFixStatus({
      livePosition: { lat: 1, lng: 1, headingDeg: 0, eventTime: "2026-01-01T00:08:00Z" },
      lastSignal: { isGpsValid: false, eventTime: "2026-01-01T00:09:50Z" },
      nowMs: NOW,
    });
    expect(status).toBe("no_fix");
  });

  it("prefers a fresher valid position over a stale invalid signal from before it", () => {
    // A device cannot "un-report" a fix it already confirmed after a moment's bad reading.
    const status = deriveGpsFixStatus({
      livePosition: { lat: 1, lng: 1, headingDeg: 0, eventTime: "2026-01-01T00:09:50Z" },
      lastSignal: { isGpsValid: false, eventTime: "2026-01-01T00:08:00Z" },
      nowMs: NOW,
    });
    expect(status).toBe("live");
  });

  it("an old invalid signal (older than the live threshold) does not force 'no_fix' forever", () => {
    const status = deriveGpsFixStatus({
      livePosition: { lat: 1, lng: 1, headingDeg: 0, eventTime: "2026-01-01T00:09:30Z" },
      lastSignal: { isGpsValid: false, eventTime: "2026-01-01T00:00:00Z" },
      nowMs: NOW,
    });
    expect(status).toBe("live");
  });
});
