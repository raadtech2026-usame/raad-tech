import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  getUser,
  inviteUser,
  isOrgScopedRole,
  listOrganizationsForPicker,
  listUsers,
  resetUserPassword,
  updateUserMfa,
  updateUserStatus,
} from "./api";

const USER_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  role: "org_admin",
  email: "amina@greenvalley.example",
  phone: null,
  full_name: "Amina Hassan",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  mfa_enabled: false,
  last_login_at: "2026-01-03T08:00:00Z",
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("users api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listUsers builds the offset query string and maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [USER_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listUsers({
      page: 1,
      pageSize: 25,
      sort: { field: "full_name", direction: "asc" },
      filters: { status: "active", role: "org_admin" },
      search: "amina",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/users?page=1&page_size=25&sort=full_name&filter%5Bstatus%5D=active&filter%5Brole%5D=org_admin&q=amina",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
          role: "org_admin",
          email: "amina@greenvalley.example",
          phone: null,
          fullName: "Amina Hassan",
          status: "active",
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-02T00:00:00Z",
          mfaEnabled: false,
          lastLoginAt: "2026-01-03T08:00:00Z",
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getUser maps a single user to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(USER_WIRE);

    const result = await getUser("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/users/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(result.fullName).toBe("Amina Hassan");
    expect(result.role).toBe("org_admin");
  });

  it("inviteUser posts the exact CreateUserRequest shape for an org-scoped role", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(USER_WIRE);

    await inviteUser({
      fullName: "Amina Hassan",
      role: "org_admin",
      email: "amina@greenvalley.example",
      phone: null,
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
    });

    expect(apiRequest).toHaveBeenCalledWith("/users", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        role: "org_admin",
        email: "amina@greenvalley.example",
        phone: null,
        full_name: "Amina Hassan",
      },
    });
  });

  it("inviteUser sends a null organization_id for a RAAD-staff role", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...USER_WIRE, role: "regional_manager", organization_id: null });

    await inviteUser({
      fullName: "Sara Ali",
      role: "regional_manager",
      email: "sara@raad.example",
      phone: null,
      organizationId: null,
    });

    expect(apiRequest).toHaveBeenCalledWith("/users", {
      method: "POST",
      body: {
        organization_id: null,
        role: "regional_manager",
        email: "sara@raad.example",
        phone: null,
        full_name: "Sara Ali",
      },
    });
  });

  it("updateUserStatus sends only the status field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...USER_WIRE, status: "disabled" });

    const result = await updateUserStatus("01ARZ3NDEKTSV4RRFFQ69G5FAV", "disabled");

    expect(apiRequest).toHaveBeenCalledWith("/users/01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      method: "PATCH",
      body: { status: "disabled" },
    });
    expect(result.status).toBe("disabled");
  });

  it("updateUserMfa sends only the mfa_enabled field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...USER_WIRE, mfa_enabled: true });

    const result = await updateUserMfa("01ARZ3NDEKTSV4RRFFQ69G5FAV", true);

    expect(apiRequest).toHaveBeenCalledWith("/users/01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      method: "PATCH",
      body: { mfa_enabled: true },
    });
    expect(result.mfaEnabled).toBe(true);
  });

  it("resetUserPassword posts with no body and maps the one-time reveal envelope", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      user: { ...USER_WIRE, is_password_change_required: true },
      temporary_password: "TempPass!23456",
    });

    const result = await resetUserPassword("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/users/01ARZ3NDEKTSV4RRFFQ69G5FAV/reset-password", {
      method: "POST",
    });
    expect(result.user.fullName).toBe("Amina Hassan");
    expect(result.temporaryPassword).toBe("TempPass!23456");
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("isOrgScopedRole is true only for org_admin/driver/parent", () => {
    expect(isOrgScopedRole("org_admin")).toBe(true);
    expect(isOrgScopedRole("driver")).toBe(true);
    expect(isOrgScopedRole("parent")).toBe(true);
    expect(isOrgScopedRole("founder")).toBe(false);
    expect(isOrgScopedRole("regional_manager")).toBe(false);
    expect(isOrgScopedRole("support_staff")).toBe(false);
    expect(isOrgScopedRole("finance_staff")).toBe(false);
  });
});
