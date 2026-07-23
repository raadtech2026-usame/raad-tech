import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  activateDevice,
  assignDeviceToVehicle,
  getDevice,
  listDevices,
  listOrganizationsForPicker,
  listVehiclesForPicker,
  reassignDevice,
  registerDevice,
  unassignDevice,
  updateDeviceLifecycle,
} from "./api";

const DEVICE_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  terminal_id: "013800000001",
  model: "JT808-X200",
  vendor: "Concox",
  sim_msisdn: "+252612345678",
  lifecycle_state: "activated",
  last_seen_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  cameras: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", channel_no: 1, position: "road_facing", label: "Front" }],
};

const ASSIGNMENT_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  device_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ",
  assigned_by: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  assigned_at: "2026-01-03T00:00:00Z",
  unassigned_at: null,
  is_active: true,
};

const ORG_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }],
  page: { total: 1, page: 1, page_size: 100 },
};

const VEHICLE_WIRE = {
  data: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ", plate_no: "ABC-1234", label: "Bus 12" }],
  page: { total: 1, page: 1, page_size: 100 },
};

describe("devices api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listDevices builds the offset query string and maps the page envelope to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [DEVICE_WIRE],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listDevices({
      page: 1,
      pageSize: 25,
      sort: { field: "terminal_id", direction: "asc" },
      filters: { lifecycle_state: "activated" },
      search: "0138",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      "/devices?page=1&page_size=25&sort=terminal_id&filter%5Blifecycle_state%5D=activated&q=0138",
    );
    expect(result).toEqual({
      data: [
        {
          id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
          terminalId: "013800000001",
          model: "JT808-X200",
          vendor: "Concox",
          simMsisdn: "+252612345678",
          lifecycleState: "activated",
          lastSeenAt: null,
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-02T00:00:00Z",
          cameras: [{ id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", channelNo: 1, position: "road_facing", label: "Front" }],
        },
      ],
      page: { total: 1, page: 1, pageSize: 25 },
    });
  });

  it("getDevice maps a single device to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(DEVICE_WIRE);

    const result = await getDevice("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(result.terminalId).toBe("013800000001");
    expect(result.cameras).toHaveLength(1);
  });

  it("registerDevice posts the exact RegisterDeviceRequest shape", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(DEVICE_WIRE);

    await registerDevice({
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      terminalId: "013800000001",
      model: "JT808-X200",
      vendor: "Concox",
      simMsisdn: "+252612345678",
    });

    expect(apiRequest).toHaveBeenCalledWith("/devices", {
      method: "POST",
      body: {
        organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        terminal_id: "013800000001",
        model: "JT808-X200",
        vendor: "Concox",
        sim_msisdn: "+252612345678",
      },
    });
  });

  it("activateDevice posts to the dedicated activate route", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...DEVICE_WIRE, lifecycle_state: "activated" });

    const result = await activateDevice("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV/activate", { method: "POST" });
    expect(result.lifecycleState).toBe("activated");
  });

  it("updateDeviceLifecycle sends only the lifecycle_state field", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...DEVICE_WIRE, lifecycle_state: "suspended" });

    const result = await updateDeviceLifecycle("01ARZ3NDEKTSV4RRFFQ69G5FAV", "suspended");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV", {
      method: "PATCH",
      body: { lifecycle_state: "suspended" },
    });
    expect(result.lifecycleState).toBe("suspended");
  });

  it("assignDeviceToVehicle posts the vehicle_id body and maps the assignment", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ASSIGNMENT_WIRE);

    const result = await assignDeviceToVehicle("01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FEZ");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV/assign", {
      method: "POST",
      body: { vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ" },
    });
    expect(result).toEqual({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      deviceId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FEZ",
      assignedBy: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
      assignedAt: "2026-01-03T00:00:00Z",
      unassignedAt: null,
      isActive: true,
    });
  });

  it("reassignDevice posts to the reassign route with the new vehicle_id", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ASSIGNMENT_WIRE);

    await reassignDevice("01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FEZ");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV/reassign", {
      method: "POST",
      body: { vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ" },
    });
  });

  it("unassignDevice posts to the unassign route with no body", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...ASSIGNMENT_WIRE, unassigned_at: "2026-01-04T00:00:00Z", is_active: false });

    const result = await unassignDevice("01ARZ3NDEKTSV4RRFFQ69G5FAV");

    expect(apiRequest).toHaveBeenCalledWith("/devices/01ARZ3NDEKTSV4RRFFQ69G5FAV/unassign", { method: "POST" });
    expect(result.isActive).toBe(false);
  });

  it("listOrganizationsForPicker maps the page envelope to a minimal option list", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ORG_WIRE);

    const result = await listOrganizationsForPicker("green");

    expect(apiRequest).toHaveBeenCalledWith(
      "/organizations?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active&q=green",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("listVehiclesForPicker filters by organization_id and active status", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(VEHICLE_WIRE);

    const result = await listVehiclesForPicker("01ARZ3NDEKTSV4RRFFQ69G5FBW", "abc");

    expect(apiRequest).toHaveBeenCalledWith(
      "/vehicles?page=1&page_size=100&sort=plate_no&filter%5Borganization_id%5D=01ARZ3NDEKTSV4RRFFQ69G5FBW&filter%5Bstatus%5D=active&q=abc",
    );
    expect(result).toEqual([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ", plateNo: "ABC-1234", label: "Bus 12" }]);
  });
});
