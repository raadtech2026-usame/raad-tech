import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import {
  assignStudentToRoute,
  endStudentAssignment,
  findActiveAssignmentForStudent,
  getRouteWithStops,
  getStudentAssignment,
  listRoutesForPicker,
  listStudentAssignments,
  listVehiclesForPicker,
} from "./api";

const ASSIGNMENT_WIRE = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FSA",
  organization_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  student_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  route_id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  pickup_stop_id: "01ARZ3NDEKTSV4RRFFQ69G5FS1",
  dropoff_stop_id: "01ARZ3NDEKTSV4RRFFQ69G5FS2",
  vehicle_id: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  status: "active",
  assigned_at: "2026-01-01T00:00:00Z",
  ended_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("student-assignments api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listStudentAssignments builds the offset query string and maps the summary envelope", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [{ id: ASSIGNMENT_WIRE.id, student_id: ASSIGNMENT_WIRE.student_id, route_id: ASSIGNMENT_WIRE.route_id, status: "active" }],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const result = await listStudentAssignments({
      page: 1,
      pageSize: 25,
      sort: null,
      filters: { student_id: ASSIGNMENT_WIRE.student_id, status: "active" },
      search: "",
    });

    expect(apiRequest).toHaveBeenCalledWith(
      `/student-assignments?page=1&page_size=25&filter%5Bstudent_id%5D=${ASSIGNMENT_WIRE.student_id}&filter%5Bstatus%5D=active`,
    );
    expect(result.data).toEqual([
      { id: ASSIGNMENT_WIRE.id, studentId: ASSIGNMENT_WIRE.student_id, routeId: ASSIGNMENT_WIRE.route_id, status: "active" },
    ]);
  });

  it("getStudentAssignment maps the full response to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ASSIGNMENT_WIRE);

    const result = await getStudentAssignment(ASSIGNMENT_WIRE.id);

    expect(apiRequest).toHaveBeenCalledWith(`/student-assignments/${ASSIGNMENT_WIRE.id}`);
    expect(result).toEqual({
      id: ASSIGNMENT_WIRE.id,
      organizationId: ASSIGNMENT_WIRE.organization_id,
      studentId: ASSIGNMENT_WIRE.student_id,
      routeId: ASSIGNMENT_WIRE.route_id,
      pickupStopId: ASSIGNMENT_WIRE.pickup_stop_id,
      dropoffStopId: ASSIGNMENT_WIRE.dropoff_stop_id,
      vehicleId: ASSIGNMENT_WIRE.vehicle_id,
      status: "active",
      assignedAt: ASSIGNMENT_WIRE.assigned_at,
      endedAt: null,
      createdAt: ASSIGNMENT_WIRE.created_at,
      updatedAt: ASSIGNMENT_WIRE.updated_at,
    });
  });

  it("findActiveAssignmentForStudent returns null when the student has no active assignment", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 1 } });

    const result = await findActiveAssignmentForStudent(ASSIGNMENT_WIRE.student_id);

    expect(apiRequest).toHaveBeenCalledWith(
      `/student-assignments?page=1&page_size=1&filter%5Bstudent_id%5D=${ASSIGNMENT_WIRE.student_id}&filter%5Bstatus%5D=active`,
    );
    expect(result).toBeNull();
  });

  it("findActiveAssignmentForStudent fetches the full detail when an active assignment exists", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        data: [{ id: ASSIGNMENT_WIRE.id, student_id: ASSIGNMENT_WIRE.student_id, route_id: ASSIGNMENT_WIRE.route_id, status: "active" }],
        page: { total: 1, page: 1, page_size: 1 },
      })
      .mockResolvedValueOnce(ASSIGNMENT_WIRE);

    const result = await findActiveAssignmentForStudent(ASSIGNMENT_WIRE.student_id);

    expect(apiRequest).toHaveBeenLastCalledWith(`/student-assignments/${ASSIGNMENT_WIRE.id}`);
    expect(result?.id).toBe(ASSIGNMENT_WIRE.id);
  });

  it("assignStudentToRoute posts the exact AssignStudentToRouteRequest shape, defaulting vehicleId to null", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(ASSIGNMENT_WIRE);

    await assignStudentToRoute({
      organizationId: ASSIGNMENT_WIRE.organization_id,
      studentId: ASSIGNMENT_WIRE.student_id,
      routeId: ASSIGNMENT_WIRE.route_id,
      pickupStopId: ASSIGNMENT_WIRE.pickup_stop_id,
      dropoffStopId: ASSIGNMENT_WIRE.dropoff_stop_id,
    });

    expect(apiRequest).toHaveBeenCalledWith("/student-assignments", {
      method: "POST",
      body: {
        organization_id: ASSIGNMENT_WIRE.organization_id,
        student_id: ASSIGNMENT_WIRE.student_id,
        route_id: ASSIGNMENT_WIRE.route_id,
        pickup_stop_id: ASSIGNMENT_WIRE.pickup_stop_id,
        dropoff_stop_id: ASSIGNMENT_WIRE.dropoff_stop_id,
        vehicle_id: null,
      },
    });
  });

  it("endStudentAssignment posts the exact {status} body", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...ASSIGNMENT_WIRE, status: "removed" });

    const result = await endStudentAssignment(ASSIGNMENT_WIRE.id, "removed");

    expect(apiRequest).toHaveBeenCalledWith(`/student-assignments/${ASSIGNMENT_WIRE.id}/end`, {
      method: "POST",
      body: { status: "removed" },
    });
    expect(result.status).toBe("removed");
  });

  it("getRouteWithStops maps the route name and its ordered stops", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      id: ASSIGNMENT_WIRE.route_id,
      name: "Morning Route A",
      stops: [{ id: ASSIGNMENT_WIRE.pickup_stop_id, name: "Main Street & 5th Ave", sequence_no: 1 }],
    });

    const result = await getRouteWithStops(ASSIGNMENT_WIRE.route_id);

    expect(apiRequest).toHaveBeenCalledWith(`/routes/${ASSIGNMENT_WIRE.route_id}`);
    expect(result).toEqual({
      id: ASSIGNMENT_WIRE.route_id,
      name: "Morning Route A",
      stops: [{ id: ASSIGNMENT_WIRE.pickup_stop_id, name: "Main Street & 5th Ave", sequenceNo: 1 }],
    });
  });

  it("listRoutesForPicker and listVehiclesForPicker never send an unwhitelisted organization_id filter for routes", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 100 } });
    await listRoutesForPicker("");
    expect(apiRequest).toHaveBeenCalledWith("/routes?page=1&page_size=100&sort=name&filter%5Bstatus%5D=active");

    vi.mocked(apiRequest).mockResolvedValueOnce({ data: [], page: { total: 0, page: 1, page_size: 100 } });
    await listVehiclesForPicker(ASSIGNMENT_WIRE.organization_id, "");
    expect(apiRequest).toHaveBeenCalledWith(
      `/vehicles?page=1&page_size=100&sort=plate_no&filter%5Borganization_id%5D=${ASSIGNMENT_WIRE.organization_id}&filter%5Bstatus%5D=active`,
    );
  });
});
