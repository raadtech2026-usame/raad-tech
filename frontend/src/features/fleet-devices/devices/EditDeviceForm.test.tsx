import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  updateDeviceDetails: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { EditDeviceForm } from "./EditDeviceForm";

const DEVICE: api.Device = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  terminalId: "000000000014482607571",
  model: null,
  vendor: null,
  simMsisdn: null,
  imei: null,
  iccid: null,
  serialNumber: null,
  lifecycleState: "assigned",
  lastSeenAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  cameras: [],
};

function renderForm(overrides: Partial<Parameters<typeof EditDeviceForm>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <EditDeviceForm open onClose={onClose} device={DEVICE} {...overrides} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("EditDeviceForm", () => {
  beforeEach(() => {
    vi.mocked(api.updateDeviceDetails).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("pre-fills the form with the device's current values", () => {
    renderForm();
    expect(screen.getByDisplayValue(DEVICE.terminalId)).toBeInTheDocument();
  });

  it("submits directly, with no confirmation, when the terminal ID is unchanged", async () => {
    vi.mocked(api.updateDeviceDetails).mockResolvedValue({ ...DEVICE, vendor: "LSZ" });
    const { onClose } = renderForm();

    await userEvent.type(screen.getByLabelText("Vendor"), "LSZ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.queryByText(/Change this device's terminal ID/)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(api.updateDeviceDetails).toHaveBeenCalledWith(
        DEVICE.id,
        expect.objectContaining({ terminalId: DEVICE.terminalId, vendor: "LSZ" }),
      ),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Device updated" });
  });

  it("requires an explicit confirmation before changing the terminal ID, and does not submit until confirmed", async () => {
    vi.mocked(api.updateDeviceDetails).mockResolvedValue({
      ...DEVICE,
      terminalId: "00000000014482607571",
    });
    renderForm();

    const terminalIdInput = screen.getByDisplayValue(DEVICE.terminalId);
    await userEvent.clear(terminalIdInput);
    await userEvent.type(terminalIdInput, "00000000014482607571");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    // The mutation must not fire before the operator explicitly confirms.
    expect(api.updateDeviceDetails).not.toHaveBeenCalled();
    expect(await screen.findByText("Change this device's terminal ID?")).toBeInTheDocument();
    expect(screen.getByText(DEVICE.terminalId)).toBeInTheDocument();
    expect(screen.getByText("00000000014482607571")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Change terminal ID" }));

    await waitFor(() =>
      expect(api.updateDeviceDetails).toHaveBeenCalledWith(
        DEVICE.id,
        expect.objectContaining({ terminalId: "00000000014482607571" }),
      ),
    );
  });

  it("cancelling the terminal-ID confirmation leaves the device unchanged", async () => {
    renderForm();

    const terminalIdInput = screen.getByDisplayValue(DEVICE.terminalId);
    await userEvent.clear(terminalIdInput);
    await userEvent.type(terminalIdInput, "00000000014482607571");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const confirmDialog = await screen.findByRole("dialog", { name: "Change this device's terminal ID?" });

    // Two "Cancel" buttons coexist here (the drawer's own, and the confirm dialog's) —
    // scoped to the confirm dialog specifically, not the drawer behind it.
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText("Change this device's terminal ID?")).not.toBeInTheDocument();
    expect(api.updateDeviceDetails).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-terminal-id conflict from the backend via a toast", async () => {
    vi.mocked(api.updateDeviceDetails).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "A device with terminal id 00000000014482607571 already exists.",
        correlationId: null,
      }),
    );
    const { onClose } = renderForm();

    const terminalIdInput = screen.getByDisplayValue(DEVICE.terminalId);
    await userEvent.clear(terminalIdInput);
    await userEvent.type(terminalIdInput, "00000000014482607571");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Change this device's terminal ID?");
    await userEvent.click(screen.getByRole("button", { name: "Change terminal ID" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Update failed",
        description: "A device with terminal id 00000000014482607571 already exists.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders nothing when the device is null", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <EditDeviceForm open onClose={vi.fn()} device={null} />
      </QueryClientProvider>,
    );
    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });
});
