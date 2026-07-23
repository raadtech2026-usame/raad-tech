import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  getParent,
  listOrganizationsForPicker,
  listParents,
  listParentUsersForPicker,
  listStudentsForParent,
  registerParent,
  unlinkStudentFromParent,
  updateParentStatus,
} from "./api";

const PARENT_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  full_name: "Fatima Ali",
  phone: "+252612345678",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const PARENT_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  full_name: "Fatima Ali",
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
      full_name: "Fatima Ali",
      email: "fatima@example.com",
      phone: null,
    },
  ],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("parents api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listParents builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [PARENT_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listParents({
      page: 1,
      pageSize: 25,
      sort: { field: "full_name", direction: "asc" },
      filters: { status: "active" },
      search: "fatima",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/parents?page=1&page_size=25&sort=full_name&filter%5Bstatus%5D=active&q=fatima",
    );
    expect(result).toEqual({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Fatima Ali", status: "active" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getParent maps the full response to camelCase, including fields the list route omits", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_WIRE);

    const result = await getParent("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      fullName: "Fatima Ali",
      phone: "+252612345678",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("registerParent posts the exact RegisterParentRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_WIRE);

    await registerParent({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      fullName: "Fatima Ali",
      phone: "+252612345678",
    });

    expect(apiRequest).toHaveBeenCalledWith("/parents", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
        full_name: "Fatima Ali",
        phone: "+252612345678",
      },
    });
  });

  it("registerParent defaults phone to null when omitted", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_WIRE);

    await registerParent({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      fullName: "Fatima Ali",
    });

    expect(apiRequest).toHaveBeenCalledWith("/parents", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
        full_name: "Fatima Ali",
        phone: null,
      },
    });
  });

  it("updateParentStatus PATCHes only the status field, leaving full_name/phone untouched", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...PARENT_WIRE, status: "inactive" });

    const result = await updateParentStatus("01ARZ3NDEKTSV4RRFFQ69G5FCX", "inactive");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX", {
      method: "PATCH",
      body: { status: "inactive" },
    });
    expect(result.status).toBe("inactive");
  });

  it("listStudentsForParent maps the raw array response to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([
      {
        student_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        full_name: "Amina Hassan",
        status: "active",
        relationship: "Mother",
        is_primary: true,
      },
    ]);

    const result = await listStudentsForParent("01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith("/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX/students");
    expect(result).toEqual([
      {
        studentId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        fullName: "Amina Hassan",
        status: "active",
        relationship: "Mother",
        isPrimary: true,
      },
    ]);
  });

  it("unlinkStudentFromParent issues a DELETE against the nested link route, student id last", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(undefined);

    await unlinkStudentFromParent("01ARZ3NDEKTSV4RRFFQ69G5FCX", "01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith(
      "/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX",
      { method: "DELETE" },
    );
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("listParentUsersForPicker filters to the given organization, role=parent, and status=active", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(USER_OPTION_WIRE);

    const result = await listParentUsersForPicker("01ARZ3NDEKTSV4RRFFQ69G5FBW", "");

    expect(apiRequest).toHaveBeenCalledWith(
      "/users?page=1&page_size=100&sort=full_name&filter%5Borganization_id%5D=01ARZ3NDEKTSV4RRFFQ69G5FBW&filter%5Brole%5D=parent&filter%5Bstatus%5D=active",
    );
    expect(result).toEqual([
      {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
        fullName: "Fatima Ali",
        email: "fatima@example.com",
        phone: null,
      },
    ]);
  });
});
