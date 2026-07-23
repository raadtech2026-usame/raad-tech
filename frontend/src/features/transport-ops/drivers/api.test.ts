import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  getDriver,
  listDriverUsersForPicker,
  listDrivers,
  listOrganizationsForPicker,
  registerDriver,
  updateDriverStatus,
} from "./api";

const DRIVER_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  license_no: "DL-00231",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const DRIVER_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  license_no: "DL-00231",
  status: "active",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

const USER_OPTION_WIRE = {
  data: [
    {
      id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      full_name: "Hassan Warsame",
      email: "hassan@example.com",
      phone: null,
    },
  ],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("drivers api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listDrivers builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [DRIVER_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listDrivers({
      page: 1,
      pageSize: 25,
      sort: { field: "license_no", direction: "asc" },
      filters: { status: "active" },
      search: "DL-002",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/drivers?page=1&page_size=25&sort=license_no&filter%5Bstatus%5D=active&q=DL-002",
    );
    expect(result).toEqual({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FDR", licenseNo: "DL-00231", status: "active" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getDriver maps the full response to camelCase, including fields the list route omits", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(DRIVER_WIRE);

    const result = await getDriver("01ARZ3NDEKTSV4RRFFQ69G5FDR");

    expect(apiRequest).toHaveBeenCalledWith("/drivers/01ARZ3NDEKTSV4RRFFQ69G5FDR");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      licenseNo: "DL-00231",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("registerDriver posts the exact RegisterDriverRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(DRIVER_WIRE);

    await registerDriver({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      licenseNo: "DL-00231",
    });

    expect(apiRequest).toHaveBeenCalledWith("/drivers", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
        license_no: "DL-00231",
      },
    });
  });

  it("updateDriverStatus PATCHes only the status field, leaving license_no untouched", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...DRIVER_WIRE, status: "inactive" });

    const result = await updateDriverStatus("01ARZ3NDEKTSV4RRFFQ69G5FDR", "inactive");

    expect(apiRequest).toHaveBeenCalledWith("/drivers/01ARZ3NDEKTSV4RRFFQ69G5FDR", {
      method: "PATCH",
      body: { status: "inactive" },
    });
    expect(result.status).toBe("inactive");
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("listDriverUsersForPicker filters to the given organization, role=driver, and status=active", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(USER_OPTION_WIRE);

    const result = await listDriverUsersForPicker("01ARZ3NDEKTSV4RRFFQ69G5FBW", "");

    expect(apiRequest).toHaveBeenCalledWith(
      "/users?page=1&page_size=100&sort=full_name&filter%5Borganization_id%5D=01ARZ3NDEKTSV4RRFFQ69G5FBW&filter%5Brole%5D=driver&filter%5Bstatus%5D=active",
    );
    expect(result).toEqual([
      {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
        fullName: "Hassan Warsame",
        email: "hassan@example.com",
        phone: null,
      },
    ]);
  });
});
