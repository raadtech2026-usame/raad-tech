import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerDevice: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateDeviceForm } from "./CreateDeviceForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const DEVICE: api.Device = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: ORG_OPTION.id,
  terminalId: "013800000001",
  model: null,
  vendor: null,
  simMsisdn: null,
  lifecycleState: "registered",
  lastSeenAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  cameras: [],
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateDeviceForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateDeviceForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.registerDevice).mockReset();
    useToastStore.setState({ toasts: [] });
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
  });

  it("shows an organization picker for a principal with no organization of their own", async () => {
    renderForm();

    expect(await screen.findByLabelText("Organization")).toBeInTheDocument();
  });

  it("hides the organization picker for an org_admin and uses their own organizationId", async () => {
    useAuthStore.setState({
      principal: { userId: "u2", role: "org_admin", organizationId: ORG_OPTION.id, regionIds: [] },
    });
    vi.mocked(api.registerDevice).mockResolvedValue(DEVICE);

    renderForm();

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("e.g. 013800000001"), "013800000001");
    await userEvent.click(screen.getByRole("button", { name: "Register device" }));

    await waitFor(() =>
      expect(api.registerDevice).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        terminalId: "013800000001",
        model: null,
        vendor: null,
        simMsisdn: null,
      }),
    );
  });

  it("shows field-level validation errors and does not submit when required fields are missing", async () => {
    renderForm();
    await screen.findByLabelText("Organization");

    await userEvent.click(screen.getByRole("button", { name: "Register device" }));

    expect(await screen.findByText("Organization is required")).toBeInTheDocument();
    expect(screen.getByText("Terminal ID is required")).toBeInTheDocument();
    expect(api.registerDevice).not.toHaveBeenCalled();
  });

  it("submits the exact RegisterDeviceRequest-shaped payload and reports success", async () => {
    vi.mocked(api.registerDevice).mockResolvedValue({ ...DEVICE, model: "JT808-X200", vendor: "Concox" });

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. 013800000001"), "013800000001");
    await userEvent.type(screen.getByPlaceholderText("e.g. JT808-X200"), "JT808-X200");
    await userEvent.type(screen.getByPlaceholderText("e.g. Concox"), "Concox");
    await userEvent.type(screen.getByPlaceholderText("e.g. +252612345678"), "+252612345678");

    await userEvent.click(screen.getByRole("button", { name: "Register device" }));

    await waitFor(() =>
      expect(api.registerDevice).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        terminalId: "013800000001",
        model: "JT808-X200",
        vendor: "Concox",
        simMsisdn: "+252612345678",
      }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({
      variant: "success",
      title: "Device registered",
    });
  });

  it("surfaces the backend's terminal-id-uniqueness conflict via a toast and keeps the drawer open", async () => {
    vi.mocked(api.registerDevice).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "A device with terminal id 013800000001 already exists.",
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. 013800000001"), "013800000001");

    await userEvent.click(screen.getByRole("button", { name: "Register device" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Registration failed",
        description: "A device with terminal id 013800000001 already exists.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
