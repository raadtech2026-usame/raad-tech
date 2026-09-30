import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  assignToBus,
  changeStaffStatus,
  getStaff,
  grantDriverAccess,
  listCrew,
  listExpiringDocuments,
  listStaffRoles,
  recordStaffDocument,
  updateStaff,
} from "./api";
import { parseLeadDays } from "./StaffSetupPanel";

const STAFF_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  full_name: "Amina Warsame",
  phone: "+252611234567",
  alternate_phone: null,
  role_id: "01ARZ3NDEKTSV4RRFFQ69G5FRL",
  role_name: "Attendant",
  employee_ref: "E-7",
  start_date: "2026-01-05",
  status: "active",
  emergency_contact_name: null,
  emergency_contact_phone: null,
  notes: null,
  left_on: null,
  driver: { driver_id: "d1", user_id: "u1", license_no: "DL-1", status: "active" },
  private_fields_visible: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const DOCUMENT_WIRE = {
  id: "doc1",
  organization_id: "org",
  staff_id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  staff_name: "Amina Warsame",
  type_id: "t1",
  type_name: "Driving licence",
  number: null,
  issued_on: null,
  expires_on: "2026-10-07",
  notes: null,
  status: "expiring",
  days_left: 7,
  replaced_by_id: null,
  private_fields_visible: false,
  created_at: "2026-09-01T00:00:00Z",
};

describe("transport staff api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("getStaff maps the wire shape, including the driver profile and the private-fields flag", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STAFF_WIRE);
    const staff = await getStaff(STAFF_WIRE.id);
    expect(apiRequest).toHaveBeenCalledWith(`/transport-staff/${STAFF_WIRE.id}`);
    expect(staff.fullName).toBe("Amina Warsame");
    expect(staff.roleName).toBe("Attendant");
    expect(staff.driver).toEqual({ driverId: "d1", userId: "u1", licenseNo: "DL-1", status: "active" });
    expect(staff.privateFieldsVisible).toBe(false);
  });

  it("updateStaff sends every profile field so a cleared input clears the stored value", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(STAFF_WIRE);
    await updateStaff("s1", {
      fullName: "Amina",
      phone: null,
      alternatePhone: null,
      roleId: null,
      employeeRef: null,
      startDate: null,
      emergencyContactName: null,
      emergencyContactPhone: null,
      notes: null,
    });
    const [path, options] = vi.mocked(apiRequest).mock.calls[0];
    expect(path).toBe("/transport-staff/s1");
    expect(options).toMatchObject({ method: "PATCH" });
    expect(Object.keys((options as { body: object }).body).sort()).toEqual(
      [
        "alternate_phone",
        "emergency_contact_name",
        "emergency_contact_phone",
        "employee_ref",
        "full_name",
        "notes",
        "phone",
        "role_id",
        "start_date",
      ].sort(),
    );
  });

  it("changeStaffStatus posts to the status sub-resource", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...STAFF_WIRE, status: "left", left_on: "2026-09-30" });
    const staff = await changeStaffStatus("s1", "left");
    expect(apiRequest).toHaveBeenCalledWith("/transport-staff/s1/status", { method: "POST", body: { status: "left" } });
    expect(staff.leftOn).toBe("2026-09-30");
  });

  it("grantDriverAccess returns the one-time password", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ driver: { id: "d9" }, temporary_password: "Temp#1" });
    const result = await grantDriverAccess("s1", { licenseNo: "DL-9", email: null, phone: "+252611234567" });
    expect(apiRequest).toHaveBeenCalledWith("/transport-staff/s1/driver-access", {
      method: "POST",
      body: { license_no: "DL-9", email: null, phone: "+252611234567" },
    });
    expect(result).toEqual({ driverId: "d9", temporaryPassword: "Temp#1" });
  });

  it("listCrew filters by vehicle and current only", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([]);
    await listCrew({ vehicleId: "v1", current: true });
    expect(apiRequest).toHaveBeenCalledWith("/staff-assignments?vehicle_id=v1&current=true");
  });

  it("assignToBus sends the snake_case body", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: "a1",
      organization_id: "org",
      staff_id: "s1",
      staff_name: "Amina",
      vehicle_id: "v1",
      role_id: null,
      role_name: null,
      route_id: null,
      starts_on: "2026-10-01",
      ends_on: "2026-10-05",
      kind: "temporary",
      reason: "Cover",
      is_current: false,
      created_at: "2026-09-30T00:00:00Z",
    });
    const assignment = await assignToBus({
      staffId: "s1",
      vehicleId: "v1",
      kind: "temporary",
      startsOn: "2026-10-01",
      endsOn: "2026-10-05",
      routeId: null,
      roleId: null,
      reason: "Cover",
    });
    expect(vi.mocked(apiRequest).mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: { staff_id: "s1", vehicle_id: "v1", kind: "temporary", starts_on: "2026-10-01", ends_on: "2026-10-05" },
    });
    expect(assignment.kind).toBe("temporary");
    expect(assignment.isCurrent).toBe(false);
  });

  it("recordStaffDocument carries replaces_id for a renewal", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(DOCUMENT_WIRE);
    await recordStaffDocument("s1", {
      typeId: "t1",
      number: "DL-2",
      issuedOn: null,
      expiresOn: "2031-10-07",
      notes: null,
      replacesId: "doc0",
    });
    expect(vi.mocked(apiRequest).mock.calls[0][1]).toMatchObject({ body: { replaces_id: "doc0", type_id: "t1" } });
  });

  it("listExpiringDocuments maps days left and status", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([DOCUMENT_WIRE]);
    const [document] = await listExpiringDocuments();
    expect(apiRequest).toHaveBeenCalledWith("/staff-documents/expiring");
    expect(document.daysLeft).toBe(7);
    expect(document.status).toBe("expiring");
  });

  it("listStaffRoles names the organization only when one is given", async () => {
    vi.mocked(apiRequest).mockResolvedValue([]);
    await listStaffRoles();
    await listStaffRoles("org 1");
    expect(vi.mocked(apiRequest).mock.calls.map((call) => call[0])).toEqual([
      "/transport-staff-roles",
      "/transport-staff-roles?organization_id=org%201",
    ]);
  });
});

describe("parseLeadDays", () => {
  it("accepts 1–5 whole numbers from 1 to 365, deduplicated and sorted descending", () => {
    expect(parseLeadDays("7, 30, 7")).toEqual([30, 7]);
    expect(parseLeadDays("90")).toEqual([90]);
  });

  it("rejects anything else", () => {
    for (const raw of ["", "0", "366", "1.5", "abc", "1,2,3,4,5,6"]) {
      expect(parseLeadDays(raw)).toBeNull();
    }
  });
});
