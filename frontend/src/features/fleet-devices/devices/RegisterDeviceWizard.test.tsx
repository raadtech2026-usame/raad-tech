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

  // Regression test for a focus-stealing bug: FormDrawer's focus-management effect used to
  // depend on `onClose`, which this wizard's own `handleClose` (non-memoized) plus its unscoped
  // `watch()` recreate on every keystroke, re-firing the effect and yanking focus to the drawer's
  // close button after every single character. Fixed in FormDrawer.tsx/DetailDrawer.tsx (see
  // their own test files for the isolated, component-level reproduction) — this test proves the
  // fix holds for the real, full wizard, across every hardware-step field.
  it("keeps focus in each hardware field while typing continuously, character by character", async () => {
    const user = userEvent.setup();
    renderWizard();

    const fields: Array<[placeholder: string, value: string]> = [
      ["e.g. 013800000001", "013800000099"],
      ["e.g. JT808-X200", "JT808-X200"],
      ["e.g. Concox", "Concox"],
      ["e.g. +252612345678", "+252612345678"],
      ["e.g. 352389088459231", "352389088459231"],
      ["e.g. 8944500XXXXXXXXXXXX", "8944500123456789012"],
      ["e.g. SN-0042", "SN-0042"],
    ];

    for (const [placeholder, value] of fields) {
      const input = screen.getByPlaceholderText(placeholder);
      await user.click(input);
      await user.type(input, value);
      expect(input).toHaveFocus();
      expect(input).toHaveValue(value);
    }
  });

  it("supports Backspace, Delete, arrow-key repositioning, paste, and Tab like a normal input", async () => {
    const user = userEvent.setup();
    renderWizard();

    const terminalId = screen.getByPlaceholderText("e.g. 013800000001");
    await user.click(terminalId);
    await user.type(terminalId, "0138000999");
    expect(terminalId).toHaveValue("0138000999");

    await user.type(terminalId, "{Backspace}{Backspace}");
    expect(terminalId).toHaveValue("01380009");
    expect(terminalId).toHaveFocus();

    await user.type(terminalId, "{ArrowLeft}{Delete}");
    expect(terminalId).toHaveValue("0138000");
    expect(terminalId).toHaveFocus();

    // Mouse-driven select-all, then paste over the selection (a real browser's "select then
    // type/paste to replace" flow).
    await user.tripleClick(terminalId);
    await user.paste("013800000001");
    expect(terminalId).toHaveValue("013800000001");
    expect(terminalId).toHaveFocus();

    // Tab moves focus to the next field in document order, not somewhere the drawer decided on
    // its own.
    await user.tab();
    expect(screen.getByPlaceholderText("e.g. JT808-X200")).toHaveFocus();
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
