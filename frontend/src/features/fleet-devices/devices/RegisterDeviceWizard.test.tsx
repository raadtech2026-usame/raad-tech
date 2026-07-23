import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listOrganizationsForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  registerDevice: vi.fn(),
  activateDevice: vi.fn(),
  assignDeviceToVehicle: vi.fn(),
  getDevice: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { RegisterDeviceWizard } from "./RegisterDeviceWizard";

const ORG_OPTION: api.OrganizationOption = { id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" };
const VEHICLE_OPTION: api.VehicleOption = { id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ", plateNo: "ABC-1234", label: "Bus 12" };

const DEVICE: api.Device = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: ORG_OPTION.id,
  terminalId: "013800000001",
  model: null,
  vendor: null,
  simMsisdn: null,
  imei: null,
  iccid: null,
  serialNumber: null,
  lifecycleState: "registered",
  lastSeenAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  cameras: [],
};

function renderWizard(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RegisterDeviceWizard open onClose={onClose} />
    </QueryClientProvider>,
  );
}

async function advanceToRegisterStep() {
  await userEvent.type(screen.getByPlaceholderText("e.g. 013800000001"), "TERM-001");
  await userEvent.click(screen.getByRole("button", { name: /Next: Organization/i }));

  await waitFor(() => expect(screen.getByRole("combobox", { name: "Organization" })).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organization" }), ORG_OPTION.id);
  await userEvent.click(screen.getByRole("button", { name: /Next: Vehicle/i }));

  await waitFor(() => expect(screen.getByRole("combobox", { name: "Vehicle" })).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Vehicle" }), VEHICLE_OPTION.id);
  await userEvent.click(screen.getByRole("button", { name: /Next: Review/i }));
}

describe("RegisterDeviceWizard", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([VEHICLE_OPTION]);
    vi.mocked(api.registerDevice).mockReset();
    vi.mocked(api.activateDevice).mockReset();
    vi.mocked(api.assignDeviceToVehicle).mockReset();
    vi.mocked(api.getDevice).mockReset();
  });

  it("blocks advancing past the hardware step without a terminal ID", async () => {
    renderWizard();
    await userEvent.click(screen.getByRole("button", { name: /Next: Organization/i }));
    expect(await screen.findByText("Terminal ID is required")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Organization" })).not.toBeInTheDocument();
  });

  it("runs register, activate, and assign in order and reaches the honest verify step", async () => {
    vi.mocked(api.registerDevice).mockResolvedValue(DEVICE);
    vi.mocked(api.activateDevice).mockResolvedValue({ ...DEVICE, lifecycleState: "activated" });
    vi.mocked(api.assignDeviceToVehicle).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
      organizationId: ORG_OPTION.id,
      deviceId: DEVICE.id,
      vehicleId: VEHICLE_OPTION.id,
      assignedBy: null,
      assignedAt: "2026-01-01T00:00:00Z",
      unassignedAt: null,
      isActive: true,
    });
    vi.mocked(api.getDevice).mockResolvedValue({ ...DEVICE, lifecycleState: "assigned", lastSeenAt: null });

    renderWizard();
    await advanceToRegisterStep();

    await userEvent.click(screen.getByRole("button", { name: /Register & activate device/i }));

    await waitFor(() => expect(screen.getByText(/Not yet connected/i)).toBeInTheDocument());

    expect(api.registerDevice).toHaveBeenCalledTimes(1);
    expect(api.activateDevice).toHaveBeenCalledWith(DEVICE.id);
    expect(api.assignDeviceToVehicle).toHaveBeenCalledWith(DEVICE.id, VEHICLE_OPTION.id);

    const registerOrder = vi.mocked(api.registerDevice).mock.invocationCallOrder[0];
    const activateOrder = vi.mocked(api.activateDevice).mock.invocationCallOrder[0];
    const assignOrder = vi.mocked(api.assignDeviceToVehicle).mock.invocationCallOrder[0];
    expect(registerOrder).toBeLessThan(activateOrder);
    expect(activateOrder).toBeLessThan(assignOrder);
  });

  it("resumes after a partial failure without re-registering the device", async () => {
    vi.mocked(api.registerDevice).mockResolvedValue(DEVICE);
    vi.mocked(api.activateDevice).mockRejectedValueOnce(
      new ApiError(409, { code: "CONFLICT", message: "Device already activated.", correlationId: null }),
    );
    vi.mocked(api.activateDevice).mockResolvedValueOnce({ ...DEVICE, lifecycleState: "activated" });
    vi.mocked(api.assignDeviceToVehicle).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
      organizationId: ORG_OPTION.id,
      deviceId: DEVICE.id,
      vehicleId: VEHICLE_OPTION.id,
      assignedBy: null,
      assignedAt: "2026-01-01T00:00:00Z",
      unassignedAt: null,
      isActive: true,
    });
    vi.mocked(api.getDevice).mockResolvedValue({ ...DEVICE, lifecycleState: "assigned" });

    renderWizard();
    await advanceToRegisterStep();

    await userEvent.click(screen.getByRole("button", { name: /Register & activate device/i }));
    await waitFor(() => expect(screen.getByText("Device already activated.")).toBeInTheDocument());
    expect(api.registerDevice).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText(/Not yet connected/i)).toBeInTheDocument());

    // Retry must not re-register the same terminal_id (would 409) — only activate+assign re-run.
    expect(api.registerDevice).toHaveBeenCalledTimes(1);
    expect(api.activateDevice).toHaveBeenCalledTimes(2);
    expect(api.assignDeviceToVehicle).toHaveBeenCalledTimes(1);
  });
});
