import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  findActiveAssignmentForStudent: vi.fn(),
  getRouteWithStops: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  endStudentAssignment: vi.fn(),
}));

import * as api from "./api";
import { StudentAssignmentSection } from "./StudentAssignmentSection";

const STUDENT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FBW";

const ACTIVE_ASSIGNMENT: api.StudentAssignment = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FSA",
  organizationId: ORG_ID,
  studentId: STUDENT_ID,
  routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  pickupStopId: "01ARZ3NDEKTSV4RRFFQ69G5FS1",
  dropoffStopId: "01ARZ3NDEKTSV4RRFFQ69G5FS2",
  vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  status: "active",
  assignedAt: "2026-01-01T00:00:00Z",
  endedAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderSection(canManage: boolean, onAssign = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <StudentAssignmentSection
        studentId={STUDENT_ID}
        organizationId={ORG_ID}
        canManage={canManage}
        onAssign={onAssign}
      />
    </QueryClientProvider>,
  );
}

describe("StudentAssignmentSection", () => {
  beforeEach(() => {
    vi.mocked(api.findActiveAssignmentForStudent).mockReset();
    vi.mocked(api.getRouteWithStops).mockReset();
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(api.endStudentAssignment).mockReset();
  });

  it("shows an honest 'no active assignment' state and an Assign to route action for a manager", async () => {
    vi.mocked(api.findActiveAssignmentForStudent).mockResolvedValue(null);
    const onAssign = vi.fn();

    renderSection(true, onAssign);

    expect(await screen.findByText("No active route assignment.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Assign to route" }));
    expect(onAssign).toHaveBeenCalled();
  });

  it("hides the Assign to route action for a read-only role", async () => {
    vi.mocked(api.findActiveAssignmentForStudent).mockResolvedValue(null);

    renderSection(false);

    expect(await screen.findByText("No active route assignment.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign to route" })).not.toBeInTheDocument();
  });

  it("shows the current active assignment's route, stops, vehicle, and status", async () => {
    vi.mocked(api.findActiveAssignmentForStudent).mockResolvedValue(ACTIVE_ASSIGNMENT);
    vi.mocked(api.getRouteWithStops).mockResolvedValue({
      id: ACTIVE_ASSIGNMENT.routeId,
      name: "Morning Route A",
      stops: [
        { id: ACTIVE_ASSIGNMENT.pickupStopId, name: "Main Street & 5th Ave", sequenceNo: 1 },
        { id: ACTIVE_ASSIGNMENT.dropoffStopId, name: "School Gate", sequenceNo: 5 },
      ],
    });
    vi.mocked(api.listVehiclesForPicker).mockResolvedValue([
      { id: ACTIVE_ASSIGNMENT.vehicleId!, plateNo: "KAA 123B", label: null },
    ]);

    renderSection(true);

    expect(await screen.findByText("Morning Route A")).toBeInTheDocument();
    expect(screen.getByText(/Pickup: Main Street & 5th Ave/)).toBeInTheDocument();
    expect(screen.getByText(/Dropoff: School Gate/)).toBeInTheDocument();
    expect(screen.getByText(/Vehicle: KAA 123B/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign to route" })).not.toBeInTheDocument();
  });

  it("lets a manager end the active assignment with the selected reason", async () => {
    vi.mocked(api.findActiveAssignmentForStudent).mockResolvedValue(ACTIVE_ASSIGNMENT);
    vi.mocked(api.getRouteWithStops).mockResolvedValue({
      id: ACTIVE_ASSIGNMENT.routeId,
      name: "Morning Route A",
      stops: [],
    });
    vi.mocked(api.endStudentAssignment).mockResolvedValue({ ...ACTIVE_ASSIGNMENT, status: "graduated" });

    renderSection(true);

    await screen.findByText("Morning Route A");
    await userEvent.selectOptions(screen.getByLabelText("End assignment reason"), "graduated");
    await userEvent.click(screen.getByRole("button", { name: "End assignment" }));

    await waitFor(() => expect(api.endStudentAssignment).toHaveBeenCalledWith(ACTIVE_ASSIGNMENT.id, "graduated"));
  });

  it("shows an honest error state when the lookup fails", async () => {
    vi.mocked(api.findActiveAssignmentForStudent).mockRejectedValue(new Error("network down"));

    renderSection(true);

    expect(await screen.findByText("Could not load this student's route assignment.")).toBeInTheDocument();
  });
});
