import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./api", () => ({
  getActiveTripRouteId: vi.fn(),
  getRouteWithStops: vi.fn(),
}));

import { getActiveTripRouteId, getRouteWithStops } from "./api";
import { useActiveTripRoute } from "./useActiveTripRoute";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useActiveTripRoute", () => {
  beforeEach(() => {
    vi.mocked(getActiveTripRouteId).mockReset();
    vi.mocked(getRouteWithStops).mockReset();
  });

  it("returns null stops and never fetches a route when there is no active trip", async () => {
    vi.mocked(getActiveTripRouteId).mockResolvedValue(null);

    const { result } = renderHook(() => useActiveTripRoute("vehicle-1"), { wrapper });

    await waitFor(() => expect(getActiveTripRouteId).toHaveBeenCalledWith("vehicle-1"));
    expect(result.current.routeStops).toBeNull();
    expect(getRouteWithStops).not.toHaveBeenCalled();
  });

  it("resolves the active trip's route stops once a route id is found", async () => {
    vi.mocked(getActiveTripRouteId).mockResolvedValue("route-1");
    vi.mocked(getRouteWithStops).mockResolvedValue({
      id: "route-1",
      name: "Morning Loop",
      stops: [
        { id: "s1", name: "Stop A", latitude: 1, longitude: 1, sequenceNo: 1, geofenceRadiusM: null },
      ],
    });

    const { result } = renderHook(() => useActiveTripRoute("vehicle-1"), { wrapper });

    await waitFor(() => expect(result.current.routeStops).not.toBeNull());
    expect(getRouteWithStops).toHaveBeenCalledWith("route-1");
    expect(result.current.routeStops).toEqual([
      { id: "s1", name: "Stop A", latitude: 1, longitude: 1, sequenceNo: 1, geofenceRadiusM: null },
    ]);
  });
});
