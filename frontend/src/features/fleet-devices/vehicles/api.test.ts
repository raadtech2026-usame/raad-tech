import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { getVehicle, listOrganizationsForPicker, listVehicles, registerVehicle, updateVehicleStatus } from "./api";

const VEHICLE_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  plate_no: "ABC-1234",
  label: "Bus 12",
  capacity: 32,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("vehicles api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listVehicles builds the offset query string and maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [VEHICLE_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listVehicles({
      page: 1,
      pageSize: 25,
      sort: { field: "plate_no", direction: "asc" },
      filters: { status: "active" },
      search: "abc",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/vehicles?page=1&page_size=25&sort=plate_no&filter%5Bstatus%5D=active&q=abc",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
          plateNo: "ABC-1234",
          label: "Bus 12",
          capacity: 32,
          status: "active",
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-02T00:00:00Z",
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getVehicle maps a single vehicle to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(VEHICLE_WIRE);

    const result = await getVehicle("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/vehicles/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(result.plateNo).toBe("ABC-1234");
    expect(result.capacity).toBe(32);
  });

  it("registerVehicle posts the exact RegisterVehicleRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(VEHICLE_WIRE);

    await registerVehicle({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      plateNo: "ABC-1234",
      label: "Bus 12",
      capacity: 32,
    });

    expect(apiRequest).toHaveBeenCalledWith("/vehicles", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        plate_no: "ABC-1234",
        label: "Bus 12",
        capacity: 32,
      },
    });
  });

  it("registerVehicle defaults label/capacity to null when omitted", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(VEHICLE_WIRE);

    await registerVehicle({ organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW", plateNo: "ABC-1234" });

    expect(apiRequest).toHaveBeenCalledWith("/vehicles", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        plate_no: "ABC-1234",
        label: null,
        capacity: null,
      },
    });
  });

  it("updateVehicleStatus sends only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...VEHICLE_WIRE, status: "maintenance" });

    const result = await updateVehicleStatus("01ARZ3NDEKTSV4RRFFQ69G5FAV", "maintenance");

    expect(apiRequest).toHaveBeenCalledWith("/vehicles/01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      method: "PATCH",
      body: { status: "maintenance" },
    });
    expect(result.status).toBe("maintenance");
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
