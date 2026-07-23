import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerVehicle: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { CreateVehicleForm } from "./CreateVehicleForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const VEHICLE: api.Vehicle = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: ORG_OPTION.id,
  plateNo: "ABC-1234",
  label: null,
  capacity: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateVehicleForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateVehicleForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.registerVehicle).mockReset();
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
    vi.mocked(api.registerVehicle).mockResolvedValue(VEHICLE);

    renderForm();

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("e.g. ABC-1234"), "ABC-1234");
    await userEvent.click(screen.getByRole("button", { name: "Register vehicle" }));

    await waitFor(() =>
      expect(api.registerVehicle).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        plateNo: "ABC-1234",
        label: null,
        capacity: null,
      }),
    );
  });

  it("shows field-level validation errors and does not submit when required fields are missing", async () => {
    renderForm();
    await screen.findByLabelText("Organization");

    await userEvent.click(screen.getByRole("button", { name: "Register vehicle" }));

    expect(await screen.findByText("Organization is required")).toBeInTheDocument();
    expect(screen.getByText("Plate number is required")).toBeInTheDocument();
    expect(api.registerVehicle).not.toHaveBeenCalled();
  });

  it("rejects a non-numeric capacity", async () => {
    renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. ABC-1234"), "ABC-1234");
    await userEvent.type(screen.getByPlaceholderText("e.g. 32"), "not-a-number");

    await userEvent.click(screen.getByRole("button", { name: "Register vehicle" }));

    expect(await screen.findByText("Capacity must be a positive whole number")).toBeInTheDocument();
    expect(api.registerVehicle).not.toHaveBeenCalled();
  });

  it("submits the exact RegisterVehicleRequest-shaped payload and reports success", async () => {
    vi.mocked(api.registerVehicle).mockResolvedValue(VEHICLE);

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. ABC-1234"), "ABC-1234");
    await userEvent.type(screen.getByPlaceholderText("e.g. Bus 12"), "Bus 12");
    await userEvent.type(screen.getByPlaceholderText("e.g. 32"), "32");

    await userEvent.click(screen.getByRole("button", { name: "Register vehicle" }));

    await waitFor(() =>
      expect(api.registerVehicle).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        plateNo: "ABC-1234",
        label: "Bus 12",
        capacity: 32,
      }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({
      variant: "success",
      title: "Vehicle registered",
    });
  });

  it("surfaces the backend's plate-uniqueness conflict via a toast and keeps the drawer open", async () => {
    const { ApiError } = await import("../../../shared/api/types");
    vi.mocked(api.registerVehicle).mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "A vehicle with plate number 'ABC-1234' already exists in this organization.",
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. ABC-1234"), "ABC-1234");

    await userEvent.click(screen.getByRole("button", { name: "Register vehicle" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Registration failed",
        description: "A vehicle with plate number 'ABC-1234' already exists in this organization.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
