import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { addStopToRoute, createRoute, getRoute, listOrganizationsForPicker, listRoutes, updateRouteStatus } from "./api";

const STOP_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  name: "Main Street & 5th Ave",
  latitude: 2.0469,
  longitude: 45.3182,
  sequence_no: 1,
  geofence_radius_m: 100,
};

const ROUTE_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Morning Route A",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  stops: [STOP_WIRE],
};

const ROUTE_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  name: "Morning Route A",
  status: "active",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("routes api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listRoutes builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [ROUTE_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listRoutes({
      page: 1,
      pageSize: 25,
      sort: { field: "name", direction: "asc" },
      filters: { status: "active" },
      search: "morning",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/routes?page=1&page_size=25&sort=name&filter%5Bstatus%5D=active&q=morning",
    );
    expect(result).toEqual({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FRT", name: "Morning Route A", status: "active" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getRoute maps the full response to camelCase, including the embedded, pre-ordered stops", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ROUTE_WIRE);

    const result = await getRoute("01ARZ3NDEKTSV4RRFFQ69G5FRT");

    expect(apiRequest).toHaveBeenCalledWith("/routes/01ARZ3NDEKTSV4RRFFQ69G5FRT");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      name: "Morning Route A",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
      stops: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
          name: "Main Street & 5th Ave",
          latitude: 2.0469,
          longitude: 45.3182,
          sequenceNo: 1,
          geofenceRadiusM: 100,
        },
      ],
    });
  });

  it("createRoute posts the exact CreateRouteRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...ROUTE_WIRE, stops: [] });

    await createRoute({ organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Morning Route A" });

    expect(apiRequest).toHaveBeenCalledWith("/routes", {
      method: "POST",
      body: { organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Morning Route A" },
    });
  });

  it("updateRouteStatus PATCHes only the status field, leaving name untouched", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...ROUTE_WIRE, status: "inactive" });

    const result = await updateRouteStatus("01ARZ3NDEKTSV4RRFFQ69G5FRT", "inactive");

    expect(apiRequest).toHaveBeenCalledWith("/routes/01ARZ3NDEKTSV4RRFFQ69G5FRT", {
      method: "PATCH",
      body: { status: "inactive" },
    });
    expect(result.status).toBe("inactive");
  });

  it("addStopToRoute posts the exact AddStopToRouteRequest shape and maps the created stop", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STOP_WIRE);

    const result = await addStopToRoute("01ARZ3NDEKTSV4RRFFQ69G5FRT", {
      name: "Main Street & 5th Ave",
      latitude: 2.0469,
      longitude: 45.3182,
      sequenceNo: 1,
      geofenceRadiusM: 100,
    });

    expect(apiRequest).toHaveBeenCalledWith("/routes/01ARZ3NDEKTSV4RRFFQ69G5FRT/stops", {
      method: "POST",
      body: {
        name: "Main Street & 5th Ave",
        latitude: 2.0469,
        longitude: 45.3182,
        sequence_no: 1,
        geofence_radius_m: 100,
      },
    });
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
      name: "Main Street & 5th Ave",
      latitude: 2.0469,
      longitude: 45.3182,
      sequenceNo: 1,
      geofenceRadiusM: 100,
    });
  });

  it("addStopToRoute defaults geofenceRadiusM to null when omitted", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...STOP_WIRE, geofence_radius_m: null });

    await addStopToRoute("01ARZ3NDEKTSV4RRFFQ69G5FRT", {
      name: "Main Street & 5th Ave",
      latitude: 2.0469,
      longitude: 45.3182,
      sequenceNo: 1,
    });

    expect(apiRequest).toHaveBeenCalledWith("/routes/01ARZ3NDEKTSV4RRFFQ69G5FRT/stops", {
      method: "POST",
      body: {
        name: "Main Street & 5th Ave",
        latitude: 2.0469,
        longitude: 45.3182,
        sequence_no: 1,
        geofence_radius_m: null,
      },
    });
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });
});
