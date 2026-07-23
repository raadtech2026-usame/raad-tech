import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  assignStudentToRoute: vi.fn(),
  listRoutesForPicker: vi.fn(),
  getRouteWithStops: vi.fn(),
  listVehiclesForPicker: vi.fn(),
}));

import * as api from "./api";
import { AssignStudentForm } from "./AssignStudentForm";

const STUDENT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FBW";
const ROUTE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FRT", name: "Morning Route A" };
const PICKUP = { id: "01ARZ3NDEKTSV4RRFFQ69G5FS1", name: "Main Street & 5th Ave", sequenceNo: 1 };
const DROPOFF = { id: "01ARZ3NDEKTSV4RRFFQ69G5FS2", name: "School Gate", sequenceNo: 5 };

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AssignStudentForm
        open
        onClose={() => {}}
        studentId={STUDENT_ID}
        studentName="Amina Hassan"
        organizationId={ORG_ID}
      />
    </QueryClientProvider>,
  );
}

describe("AssignStudentForm", () => {
  beforeEach(() => {
    vi.mocked(api.assignStudentToRoute).mockReset();
    vi.mocked(api.listRoutesForPicker).mockReset().mockResolvedValue([ROUTE]);
    vi.mocked(api.getRouteWithStops).mockReset().mockResolvedValue({
      id: ROUTE.id,
      name: ROUTE.name,
      stops: [PICKUP, DROPOFF],
    });
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([]);
  });

  it("renders nothing when no student is selected", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <AssignStudentForm open onClose={() => {}} studentId={null} organizationId={ORG_ID} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("Assign to route")).not.toBeInTheDocument();
  });

  it("disables the stop pickers until a route is chosen, then populates them from that route's stops", async () => {
    renderForm();

    expect(screen.getByLabelText("Pickup stop")).toBeDisabled();
    expect(screen.getByLabelText("Dropoff stop")).toBeDisabled();

    const routeSelect = await screen.findByLabelText("Route");
    await waitFor(() => expect(routeSelect).not.toBeDisabled());
    await userEvent.selectOptions(routeSelect, ROUTE.id);

    await waitFor(() => expect(screen.getByLabelText("Pickup stop")).not.toBeDisabled());
    expect(within(screen.getByLabelText("Pickup stop")).getByRole("option", { name: "1. Main Street & 5th Ave" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("Pickup stop")).getByRole("option", { name: "5. School Gate" })).toBeInTheDocument();
  });

  it("submits the exact AssignStudentToRouteInput shape, defaulting vehicleId to null when unset", async () => {
    vi.mocked(api.assignStudentToRoute).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FSA",
      organizationId: ORG_ID,
      studentId: STUDENT_ID,
      routeId: ROUTE.id,
      pickupStopId: PICKUP.id,
      dropoffStopId: DROPOFF.id,
      vehicleId: null,
      status: "active",
      assignedAt: "2026-01-01T00:00:00Z",
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
    });

    renderForm();

    const routeSelect = await screen.findByLabelText("Route");
    await waitFor(() => expect(routeSelect).not.toBeDisabled());
    await userEvent.selectOptions(routeSelect, ROUTE.id);
    await waitFor(() => expect(screen.getByLabelText("Pickup stop")).not.toBeDisabled());
    await userEvent.selectOptions(screen.getByLabelText("Pickup stop"), PICKUP.id);
    await userEvent.selectOptions(screen.getByLabelText("Dropoff stop"), DROPOFF.id);
    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(api.assignStudentToRoute).toHaveBeenCalledWith({
        organizationId: ORG_ID,
        studentId: STUDENT_ID,
        routeId: ROUTE.id,
        pickupStopId: PICKUP.id,
        dropoffStopId: DROPOFF.id,
        vehicleId: null,
      }),
    );
  });

  it("shows a validation error and does not submit when no route is selected", async () => {
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(await screen.findByText("Route is required")).toBeInTheDocument();
    expect(api.assignStudentToRoute).not.toHaveBeenCalled();
  });
});
