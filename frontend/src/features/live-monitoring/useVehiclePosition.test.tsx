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
import { useVehiclePosition } from "./useVehiclePosition";

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

  it("resolves hasKnownPosition from the REST snapshot when no live frame has arrived yet", async () => {
    vi.mocked(getLatestVehiclePosition).mockResolvedValue({
      vehicleId: "vehicle-1",
      tripId: null,
      latitude: 1.1,
      longitude: 2.2,
      speedKph: 10,
      headingDeg: 45,
      eventTime: "2026-01-01T00:00:00Z",
    });

    const { result } = renderHook(() => useVehiclePosition("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.hasKnownPosition).toBe(true));
    expect(result.current.livePosition).toBeNull();
  });
});
