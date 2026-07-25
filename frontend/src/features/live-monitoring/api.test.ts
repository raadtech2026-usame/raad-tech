import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { ApiError } from "../../shared/api/types";
import {
  getActiveTripRouteId,
  getLatestVehiclePosition,
  getRouteWithStops,
  listVehiclesForTracking,
} from "./api";

const POSITION_WIRE = {
  vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  trip_id: "01ARZ3NDEKTSV4RRFFQ69G5FBX",
  latitude: 2.0469,
  longitude: 45.3182,
  speed_kph: 42,
  heading_deg: 90,
  event_time: "2026-01-01T00:00:00Z",
};

describe("live-monitoring api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("getLatestVehiclePosition maps a real snapshot to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(POSITION_WIRE);

    const result = await getLatestVehiclePosition("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/tracking/vehicles/01ARZ3NDEKTSV4RRFFQ69G5FAV/latest");
    expect(result).toEqual({
      vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      tripId: "01ARZ3NDEKTSV4RRFFQ69G5FBX",
      latitude: 2.0469,
      longitude: 45.3182,
      speedKph: 42,
      headingDeg: 90,
      eventTime: "2026-01-01T00:00:00Z",
    });
  });

  it("getLatestVehiclePosition maps a 404 (no known position yet) to null, not an error", async () => {
    vi.mocked(apiRequest).mockRejectedValueOnce(
      new ApiError(404, { code: "NOT_FOUND", message: "No position known.", correlationId: null }),
    );

    const result = await getLatestVehiclePosition("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(result).toBeNull();
  });

  it("getLatestVehiclePosition re-throws a non-404 error (a real misconfiguration, not an honest empty state)", async () => {
    vi.mocked(apiRequest).mockRejectedValueOnce(
      new ApiError(500, { code: "UNKNOWN_ERROR", message: "Redis not configured.", correlationId: null }),
    );

    await expect(getLatestVehiclePosition("01ARZ3NDEKTSV4RRFFQ69G5FAV")).rejects.toBeInstanceOf(ApiError);
  });

  it("listVehiclesForTracking builds the picker query and maps to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", plate_no: "ABC-1234", label: "Bus 12" }],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const result = await listVehiclesForTracking("");

    expect(apiRequest).toHaveBeenCalledWith(
      "/vehicles?page=1&page_size=100&sort=plate_no&filter%5Bstatus%5D=active",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", plateNo: "ABC-1234", label: "Bus 12" }]);
  });

  it("getActiveTripRouteId returns the route id of the vehicle's in-progress trip", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBX", route_id: "01ARZ3NDEKTSV4RRFFQ69G5FCY" }],
      page: { total: 1, page: 1, page_size: 1 },
    });

    const result = await getActiveTripRouteId("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith(
      "/trips?page=1&page_size=1&filter%5Bvehicle_id%5D=01ARZ3NDEKTSV4RRFFQ69G5FAV&filter%5Bstatus%5D=in_progress",
    );
    expect(result).toBe("01ARZ3NDEKTSV4RRFFQ69G5FCY");
  });

  it("getActiveTripRouteId returns null when no trip is in progress", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 1 } });

    const result = await getActiveTripRouteId("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(result).toBeNull();
  });

  it("getRouteWithStops maps the route and its stops to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FCY",
      name: "Morning Route A",
      stops: [
        { id: "s1", name: "Stop 1", latitude: 2.05, longitude: 45.32, sequence_no: 1, geofence_radius_m: 50 },
      ],
    });

    const result = await getRouteWithStops("01ARZ3NDEKTSV4RRFFQ69G5FCY");

    expect(apiRequest).toHaveBeenCalledWith("/routes/01ARZ3NDEKTSV4RRFFQ69G5FCY");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FCY",
      name: "Morning Route A",
      stops: [{ id: "s1", name: "Stop 1", latitude: 2.05, longitude: 45.32, sequenceNo: 1, geofenceRadiusM: 50 }],
    });
  });
});
