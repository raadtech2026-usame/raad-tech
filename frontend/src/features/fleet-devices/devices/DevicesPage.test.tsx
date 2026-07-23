import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listDevices: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  activateDevice: vi.fn(),
  updateDeviceLifecycle: vi.fn(),
  unassignDevice: vi.fn(),
  assignDeviceToVehicle: vi.fn(),
  reassignDevice: vi.fn(),
  registerDevice: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { DevicesPage } from "./DevicesPage";

const REGISTERED_DEVICE: api.Device = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  terminalId: "013800000001",
  model: "JT808-X200",
  vendor: "Concox",
  simMsisdn: "+252612345678",
  lifecycleState: "registered",
  lastSeenAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  cameras: [],
};

const ACTIVATED_DEVICE: api.Device = { ...REGISTERED_DEVICE, lifecycleState: "activated" };
const ASSIGNED_DEVICE: api.Device = { ...REGISTERED_DEVICE, lifecycleState: "assigned" };

const VEHICLE_OPTION: api.VehicleOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FEZ",
  plateNo: "ABC-1234",
  label: "Bus 12",
};

const ASSIGNMENT: api.DeviceAssignment = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDY",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  deviceId: REGISTERED_DEVICE.id,
  vehicleId: VEHICLE_OPTION.id,
  assignedBy: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  assignedAt: "2026-01-03T00:00:00Z",
  unassignedAt: null,
  isActive: true,
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DevicesPage />
    </QueryClientProvider>,
  );
}

describe("DevicesPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listDevices).mockReset();
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([VEHICLE_OPTION]);
    vi.mocked(api.activateDevice).mockReset();
    vi.mocked(api.updateDeviceLifecycle).mockReset();
    vi.mocked(api.unassignDevice).mockReset();
    vi.mocked(api.assignDeviceToVehicle).mockReset();
    vi.mocked(api.reassignDevice).mockReset();
  });

  it("renders skeleton state while loading, then the fetched devices", async () => {
    let resolvePage!: (value: OffsetPage<api.Device>) => void;
    vi.mocked(api.listDevices).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("013800000001")).not.toBeInTheDocument();

    resolvePage(pageOf([REGISTERED_DEVICE], 1));

    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    expect(screen.getByText("Green Valley School")).toBeInTheDocument();
    expect(screen.getByText("Concox · JT808-X200")).toBeInTheDocument();
  });

  it("shows an empty state when there are no devices", async () => {
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No devices yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listDevices).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load devices")).toBeInTheDocument());
  });

  it("opens the detail drawer with the device's details on row click", async () => {
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([REGISTERED_DEVICE], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());

    await userEvent.click(screen.getByText("013800000001"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Model")).toBeInTheDocument();
    expect(within(dialog).getByText("JT808-X200")).toBeInTheDocument();
    expect(within(dialog).getByText(REGISTERED_DEVICE.id)).toBeInTheDocument();
  });

  it("lets a founder activate a registered device from the detail drawer", async () => {
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([REGISTERED_DEVICE], 1));
    vi.mocked(api.activateDevice).mockResolvedValue(ACTIVATED_DEVICE);

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    await userEvent.click(screen.getByText("013800000001"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(api.activateDevice).toHaveBeenCalledWith(REGISTERED_DEVICE.id));
  });

  it("hides the New Device action and drawer actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([REGISTERED_DEVICE], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Device/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("013800000001"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
  });

  it("lets support_staff manage lifecycle but hides the assignment actions", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([ACTIVATED_DEVICE], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    await userEvent.click(screen.getByText("013800000001"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Suspend" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Assign to vehicle" })).not.toBeInTheDocument();
  });

  it("assigns an activated device to a vehicle and shows the resulting binding in the drawer", async () => {
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([ACTIVATED_DEVICE], 1));
    vi.mocked(api.assignDeviceToVehicle).mockResolvedValue(ASSIGNMENT);

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    await userEvent.click(screen.getByText("013800000001"));

    const detailDialog = await screen.findByRole("dialog");
    await userEvent.click(within(detailDialog).getByRole("button", { name: "Assign to vehicle" }));

    const assignDialogs = await screen.findAllByRole("dialog");
    const assignDialog = assignDialogs[assignDialogs.length - 1];
    await screen.findByText("ABC-1234 — Bus 12");
    await userEvent.selectOptions(within(assignDialog).getByLabelText("Vehicle"), VEHICLE_OPTION.id);
    await userEvent.click(within(assignDialog).getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(api.assignDeviceToVehicle).toHaveBeenCalledWith(ACTIVATED_DEVICE.id, VEHICLE_OPTION.id),
    );
    await waitFor(() => expect(screen.getByText("Current assignment")).toBeInTheDocument());
    expect(screen.getByText("ABC-1234 — Bus 12")).toBeInTheDocument();
  });

  it("surfaces the backend's one-active-device-per-vehicle conflict via a toast and keeps the assign drawer open", async () => {
    useToastStore.setState({ toasts: [] });
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([ACTIVATED_DEVICE], 1));
    vi.mocked(api.assignDeviceToVehicle).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "Vehicle 01ARZ3NDEKTSV4RRFFQ69G5FEZ already has an active device 01XYZ (one active device per vehicle, Phase 2 §19).",
        correlationId: null,
      }),
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    await userEvent.click(screen.getByText("013800000001"));

    const detailDialog = await screen.findByRole("dialog");
    await userEvent.click(within(detailDialog).getByRole("button", { name: "Assign to vehicle" }));

    const assignDialogs = await screen.findAllByRole("dialog");
    const assignDialog = assignDialogs[assignDialogs.length - 1];
    await screen.findByText("ABC-1234 — Bus 12");
    await userEvent.selectOptions(within(assignDialog).getByLabelText("Vehicle"), VEHICLE_OPTION.id);
    await userEvent.click(within(assignDialog).getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Assignment failed",
        description:
          "Vehicle 01ARZ3NDEKTSV4RRFFQ69G5FEZ already has an active device 01XYZ (one active device per vehicle, Phase 2 §19).",
      }),
    );
    // The assign drawer is still open, ready for another attempt — not a silent failure.
    expect(within(assignDialog).getByRole("button", { name: "Assign" })).toBeInTheDocument();
  });

  it("unassigns a device and returns it to the activated state in the drawer", async () => {
    vi.mocked(api.listDevices).mockResolvedValue(pageOf([ASSIGNED_DEVICE], 1));
    vi.mocked(api.unassignDevice).mockResolvedValue({ ...ASSIGNMENT, unassignedAt: "2026-01-04T00:00:00Z", isActive: false });

    renderPage();
    await waitFor(() => expect(screen.getByText("013800000001")).toBeInTheDocument());
    await userEvent.click(screen.getByText("013800000001"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Unassign" }));

    await waitFor(() => expect(api.unassignDevice).toHaveBeenCalledWith(ASSIGNED_DEVICE.id));
    await waitFor(() => expect(within(dialog).getByText("Activated")).toBeInTheDocument());
  });
});
