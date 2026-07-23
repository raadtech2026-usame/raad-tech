import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  changeTripDriver,
  endTrip,
  getTrip,
  listDriversForPicker,
  listRoutesForPicker,
  listTrips,
  listVehiclesForPicker,
  scheduleTrip,
  startTrip,
} from "./api";

const TRIP_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  driver_id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  route_id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  trip_type: "morning",
  status: "scheduled",
  scheduled_date: "2026-07-24",
  started_at: null,
  ended_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const TRIP_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
  vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  driver_id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  route_id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  trip_type: "morning",
  status: "scheduled",
  scheduled_date: "2026-07-24",
};

describe("trips api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listTrips builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [TRIP_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listTrips({
      page: 1,
      pageSize: 25,
      sort: { field: "scheduled_date", direction: "desc" },
      filters: { status: "scheduled" },
      search: "",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/trips?page=1&page_size=25&sort=-scheduled_date&filter%5Bstatus%5D=scheduled",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
          vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
          driverId: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
          routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
          tripType: "morning",
          status: "scheduled",
          scheduledDate: "2026-07-24",
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getTrip maps the full response to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(TRIP_WIRE);

    const result = await getTrip("01ARZ3NDEKTSV4RRFFQ69G5FTP");

    expect(apiRequest).toHaveBeenCalledWith("/trips/01ARZ3NDEKTSV4RRFFQ69G5FTP");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
      driverId: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
      routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
      tripType: "morning",
      status: "scheduled",
      scheduledDate: "2026-07-24",
      startedAt: null,
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("scheduleTrip posts the exact ScheduleTripRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(TRIP_WIRE);

    await scheduleTrip({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
      driverId: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
      routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
      tripType: "morning",
      scheduledDate: "2026-07-24",
    });

    expect(apiRequest).toHaveBeenCalledWith("/trips", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
        driver_id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
        route_id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
        trip_type: "morning",
        scheduled_date: "2026-07-24",
      },
    });
  });

  it("startTrip posts with no request body", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...TRIP_WIRE, status: "in_progress" });

    const result = await startTrip("01ARZ3NDEKTSV4RRFFQ69G5FTP");

    expect(apiRequest).toHaveBeenCalledWith("/trips/01ARZ3NDEKTSV4RRFFQ69G5FTP/start", { method: "POST" });
    expect(result.status).toBe("in_progress");
  });

  it("endTrip posts with no request body", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...TRIP_WIRE, status: "completed" });

    const result = await endTrip("01ARZ3NDEKTSV4RRFFQ69G5FTP");

    expect(apiRequest).toHaveBeenCalledWith("/trips/01ARZ3NDEKTSV4RRFFQ69G5FTP/end", { method: "POST" });
    expect(result.status).toBe("completed");
  });

  it("changeTripDriver PATCHes the exact ChangeTripDriverRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...TRIP_WIRE, driver_id: "01ARZ3NDEKTSV4RRFFQ69G5FD2" });

    const result = await changeTripDriver("01ARZ3NDEKTSV4RRFFQ69G5FTP", "01ARZ3NDEKTSV4RRFFQ69G5FD2");

    expect(apiRequest).toHaveBeenCalledWith("/trips/01ARZ3NDEKTSV4RRFFQ69G5FTP/driver", {
      method: "PATCH",
      body: { driver_id: "01ARZ3NDEKTSV4RRFFQ69G5FD2" },
    });
    expect(result.driverId).toBe("01ARZ3NDEKTSV4RRFFQ69G5FD2");
  });

  it("listVehiclesForPicker filters by organization when one is given", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 100 } });

    await listVehiclesForPicker("01ARZ3NDEKTSV4RRFFQ69G5FBW", "");

    expect(apiRequest).toHaveBeenCalledWith(
      "/vehicles?page=1&page_size=100&sort=plate_no&filter%5Borganization_id%5D=01ARZ3NDEKTSV4RRFFQ69G5FBW&filter%5Bstatus%5D=active",
    );
  });

  it("listDriversForPicker never sends an organization_id filter (not whitelisted server-side)", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 100 } });

    await listDriversForPicker("");

    expect(apiRequest).toHaveBeenCalledWith("/drivers?page=1&page_size=100&sort=license_no&filter%5Bstatus%5D=active");
  });

  it("listRoutesForPicker never sends an organization_id filter (not whitelisted server-side)", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 100 } });

    await listRoutesForPicker("");

    expect(apiRequest).toHaveBeenCalledWith("/routes?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active");
  });
});
