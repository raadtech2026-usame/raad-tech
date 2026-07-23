import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  enrollStudent,
  getStudent,
  linkGuardianToStudent,
  listGuardiansForStudent,
  listOrganizationsForPicker,
  listParentsForPicker,
  listStudents,
  unlinkGuardianFromStudent,
  updateStudentStatus,
} from "./api";

const STUDENT_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  full_name: "Amina Hassan",
  external_ref: "STU-00231",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const STUDENT_SUMMARY_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  full_name: "Amina Hassan",
  status: "active",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

const PARENT_OPTION_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", full_name: "Fatima Ali", status: "active" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("students api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listStudents builds the offset query string and maps the summary envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [STUDENT_SUMMARY_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listStudents({
      page: 1,
      pageSize: 25,
      sort: { field: "full_name", direction: "asc" },
      filters: { status: "active" },
      search: "amina",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/students?page=1&page_size=25&sort=full_name&filter%5Bstatus%5D=active&q=amina",
    );
    expect(result).toEqual({
      data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FAV", fullName: "Amina Hassan", status: "active" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getStudent maps the full response to camelCase, including fields the list route omits", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STUDENT_WIRE);

    const result = await getStudent("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      fullName: "Amina Hassan",
      externalRef: "STU-00231",
      status: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("enrollStudent posts the exact EnrollStudentRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STUDENT_WIRE);

    await enrollStudent({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      fullName: "Amina Hassan",
      externalRef: "STU-00231",
    });

    expect(apiRequest).toHaveBeenCalledWith("/students", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        full_name: "Amina Hassan",
        external_ref: "STU-00231",
      },
    });
  });

  it("enrollStudent defaults external_ref to null when omitted", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STUDENT_WIRE);

    await enrollStudent({ organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW", fullName: "Amina Hassan" });

    expect(apiRequest).toHaveBeenCalledWith("/students", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        full_name: "Amina Hassan",
        external_ref: null,
      },
    });
  });

  it("updateStudentStatus posts to the dedicated /status sub-route with only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...STUDENT_WIRE, status: "graduated" });

    const result = await updateStudentStatus("01ARZ3NDEKTSV4RRFFQ69G5FAV", "graduated");

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/status", {
      method: "POST",
      body: { status: "graduated" },
    });
    expect(result.status).toBe("graduated");
  });

  it("listGuardiansForStudent maps the raw array response to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([
      {
        parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
        full_name: "Fatima Ali",
        phone: "+252612345678",
        status: "active",
        relationship: "Mother",
        is_primary: true,
      },
    ]);

    const result = await listGuardiansForStudent("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents");
    expect(result).toEqual([
      {
        parentId: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
        fullName: "Fatima Ali",
        phone: "+252612345678",
        status: "active",
        relationship: "Mother",
        isPrimary: true,
      },
    ]);
  });

  it("linkGuardianToStudent posts the exact LinkParentToStudentRequest shape with defaults applied", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      student_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      relationship: null,
      is_primary: false,
    });

    await linkGuardianToStudent("01ARZ3NDEKTSV4RRFFQ69G5FAV", { parentId: "01ARZ3NDEKTSV4RRFFQ69G5FCX" });

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents", {
      method: "POST",
      body: { parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", relationship: null, is_primary: false },
    });
  });

  it("linkGuardianToStudent forwards relationship/isPrimary when given", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({});

    await linkGuardianToStudent("01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      parentId: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
      relationship: "Mother",
      isPrimary: true,
    });

    expect(apiRequest).toHaveBeenCalledWith("/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents", {
      method: "POST",
      body: { parent_id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", relationship: "Mother", is_primary: true },
    });
  });

  it("unlinkGuardianFromStudent issues a DELETE against the nested link route", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(undefined);

    await unlinkGuardianFromStudent("01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FCX");

    expect(apiRequest).toHaveBeenCalledWith(
      "/students/01ARZ3NDEKTSV4RRFFQ69G5FAV/parents/01ARZ3NDEKTSV4RRFFQ69G5FCX",
      { method: "DELETE" },
    );
  });

  it("listParentsForPicker filters to active parents only, sorted by name", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(PARENT_OPTION_WIRE);

    const result = await listParentsForPicker("");

    expect(apiRequest).toHaveBeenCalledWith(
      "/parents?page=1&page_size=100&sort=full_name&filter%5Bstatus%5D=active",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Fatima Ali", status: "active" }]);
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
