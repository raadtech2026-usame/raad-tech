import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  assignDeviceToVehicle: vi.fn(),
  reassignDevice: vi.fn(),
  listVehiclesForPicker: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { AssignDeviceForm } from "./AssignDeviceForm";

const DEVICE: api.Device = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  terminalId: "013800000001",
  model: "JT808-X200",
  vendor: "Concox",
  simMsisdn: null,
  lifecycleState: "activated",
  lastSeenAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  cameras: [],
};

const VEHICLE_OPTION: api.VehicleOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ",
  plateNo: "ABC-1234",
  label: "Bus 12",
};

const ASSIGNMENT: api.DeviceAssignment = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
  organizationId: DEVICE.organizationId,
  deviceId: DEVICE.id,
  vehicleId: VEHICLE_OPTION.id,
  assignedBy: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  assignedAt: "2026-01-03T00:00:00Z",
  unassignedAt: null,
  isActive: true,
};

function renderForm(overrides: Partial<Parameters<typeof AssignDeviceForm>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  const onAssigned = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <AssignDeviceForm open onClose={onClose} device={DEVICE} mode="assign" onAssigned={onAssigned} {...overrides} />
    </QueryClientProvider>,
  );
  return { onClose, onAssigned };
}

describe("AssignDeviceForm", () => {
  beforeEach(() => {
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([VEHICLE_OPTION]);
    vi.mocked(api.assignDeviceToVehicle).mockReset();
    vi.mocked(api.reassignDevice).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("fetches the vehicle picker scoped to the device's own organization", async () => {
    renderForm();

    await waitFor(() => expect(api.listVehiclesForPicker).toHaveBeenCalledWith(DEVICE.organizationId, ""));
    expect(await screen.findByText("ABC-1234 — Bus 12")).toBeInTheDocument();
  });

  it("requires a vehicle to be selected before submitting", async () => {
    renderForm();
    await screen.findByText("ABC-1234 — Bus 12");

    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(await screen.findByText("Vehicle is required")).toBeInTheDocument();
    expect(api.assignDeviceToVehicle).not.toHaveBeenCalled();
  });

  it("calls assignDeviceToVehicle in assign mode and reports the resulting binding", async () => {
    vi.mocked(api.assignDeviceToVehicle).mockResolvedValue(ASSIGNMENT);
    const { onClose, onAssigned } = renderForm({ mode: "assign" });
    await screen.findByText("ABC-1234 — Bus 12");

    await userEvent.selectOptions(screen.getByLabelText("Vehicle"), VEHICLE_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(api.assignDeviceToVehicle).toHaveBeenCalledWith(DEVICE.id, VEHICLE_OPTION.id));
    expect(api.reassignDevice).not.toHaveBeenCalled();
    await waitFor(() => expect(onAssigned).toHaveBeenCalledWith(VEHICLE_OPTION));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Device assigned" });
  });

  it("calls reassignDevice in reassign mode", async () => {
    vi.mocked(api.reassignDevice).mockResolvedValue(ASSIGNMENT);
    const { onClose } = renderForm({ mode: "reassign" });
    await screen.findByText("ABC-1234 — Bus 12");

    await userEvent.selectOptions(screen.getByLabelText("Vehicle"), VEHICLE_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));

    await waitFor(() => expect(api.reassignDevice).toHaveBeenCalledWith(DEVICE.id, VEHICLE_OPTION.id));
    expect(api.assignDeviceToVehicle).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Device reassigned" });
  });

  it("surfaces the backend's one-active-binding conflict via a toast and keeps the drawer open for another attempt", async () => {
    vi.mocked(api.assignDeviceToVehicle).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: `Device ${DEVICE.id} is already assigned to vehicle 01OTHERVEHICLE (one active binding per device, Phase 2 §19).`,
        correlationId: null,
      }),
    );

    const { onClose, onAssigned } = renderForm({ mode: "assign" });
    await screen.findByText("ABC-1234 — Bus 12");

    await userEvent.selectOptions(screen.getByLabelText("Vehicle"), VEHICLE_OPTION.id);
    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Assignment failed",
        description: `Device ${DEVICE.id} is already assigned to vehicle 01OTHERVEHICLE (one active binding per device, Phase 2 §19).`,
      }),
    );
    // Not a silent failure and not closed — the operator can immediately pick a different vehicle.
    expect(onClose).not.toHaveBeenCalled();
    expect(onAssigned).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Assign" })).toBeInTheDocument();
  });

  it("renders nothing when the device is null", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <AssignDeviceForm open onClose={vi.fn()} device={null} mode="assign" onAssigned={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });
});
