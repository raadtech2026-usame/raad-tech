import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { createRegion, getRegion, listRegions, updateRegionStatus } from "./api";

const REGION_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "East Africa",
  geographic_scope: "Kenya, Somalia, Ethiopia",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("regions api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listRegions builds the offset query string and maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [REGION_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listRegions({
      page: 1,
      pageSize: 25,
      sort: { field: "name", direction: "asc" },
      filters: { status: "active" },
      search: "east",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/regions?page=1&page_size=25&sort=name&filter%5Bstatus%5D=active&q=east",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
          name: "East Africa",
          geographicScope: "Kenya, Somalia, Ethiopia",
          status: "active",
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-01T00:00:00Z",
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getRegion maps a single region to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(REGION_WIRE);

    const result = await getRegion("01ARZ3NDEKTSV4RRFFQ69G5FBW");

    expect(apiRequest).toHaveBeenCalledWith("/regions/01ARZ3NDEKTSV4RRFFQ69G5FBW");
    expect(result.name).toBe("East Africa");
  });

  it("createRegion posts the exact CreateRegionRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(REGION_WIRE);

    await createRegion({ name: "East Africa", geographicScope: "Kenya, Somalia, Ethiopia" });

    expect(apiRequest).toHaveBeenCalledWith("/regions", {
      method: "POST",
      body: { name: "East Africa", geographic_scope: "Kenya, Somalia, Ethiopia" },
    });
  });

  it("updateRegionStatus sends only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...REGION_WIRE, status: "inactive" });

    const result = await updateRegionStatus("01ARZ3NDEKTSV4RRFFQ69G5FBW", "inactive");

    expect(apiRequest).toHaveBeenCalledWith("/regions/01ARZ3NDEKTSV4RRFFQ69G5FBW", {
      method: "PATCH",
      body: { status: "inactive" },
    });
    expect(result.status).toBe("inactive");
  });
});
