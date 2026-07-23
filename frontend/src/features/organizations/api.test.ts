import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import {
  createOrganization,
  getOrganization,
  listOrganizations,
  listRegions,
  updateOrganizationStatus,
} from "./api";

const ORG_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  name: "Green Valley School",
  org_type: "school",
  parent_org_id: null,
  region_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  billing_model: "organization_pays",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const REGION_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Northern Region",
  geographic_scope: "North",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("organizations api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listOrganizations builds the offset query string and maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [ORG_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listOrganizations({
      page: 1,
      pageSize: 25,
      sort: { field: "name", direction: "asc" },
      filters: { status: "active" },
      search: "green",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=25&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          name: "Green Valley School",
          orgType: "school",
          parentOrgId: null,
          regionId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
          billingModel: "organization_pays",
          status: "active",
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-02T00:00:00Z",
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getOrganization maps a single organization to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await getOrganization("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/organizations/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(result.name).toBe("Green Valley School");
    expect(result.billingModel).toBe("organization_pays");
  });

  it("createOrganization posts the exact RegisterOrganizationRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    await createOrganization({
      name: "Green Valley School",
      orgType: "school",
      regionId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      billingModel: "organization_pays",
      parentOrgId: null,
    });

    expect(apiRequest).toHaveBeenCalledWith("/organizations", {
      method: "POST",
      body: {
        name: "Green Valley School",
        org_type: "school",
        region_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        billing_model: "organization_pays",
        parent_org_id: null,
      },
    });
  });

  it("updateOrganizationStatus sends only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...ORG_WIRE, status: "suspended" });

    const result = await updateOrganizationStatus("01ARZ3NDEKTSV4RRFFQ69G5FAV", "suspended");

    expect(apiRequest).toHaveBeenCalledWith("/organizations/01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      method: "PATCH",
      body: { status: "suspended" },
    });
    expect(result.status).toBe("suspended");
  });

  it("listRegions maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [REGION_WIRE],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const result = await listRegions({
      page: 1,
      pageSize: 100,
      sort: null,
      filters: {},
      search: "",
    });

    expect(apiRequest).toHaveBeenCalledWith("/regions?page=1&page_size=100");
    expect(result.data[0]).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      name: "Northern Region",
      geographicScope: "North",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
    });
  });
});
