import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  createOrganization: vi.fn(),
  listRegions: vi.fn(),
}));

import * as api from "./api";
import { useToastStore } from "../../shared/components/Toast/toastStore";
import { CreateOrganizationForm } from "./CreateOrganizationForm";

const REGION: api.Region = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Northern Region",
  geographicScope: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateOrganizationForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

async function fillRequiredFields() {
  await userEvent.type(
    screen.getByPlaceholderText("e.g. Green Valley School"),
    "Green Valley School",
  );
  await userEvent.selectOptions(screen.getByLabelText("Region"), REGION.id);
  await userEvent.type(
    screen.getByPlaceholderText("e.g. Amina Warsame"),
    "Amina Warsame",
  );
  await userEvent.type(
    screen.getByPlaceholderText("admin@school.example.com"),
    "amina@greenvalley.example.com",
  );
}

describe("CreateOrganizationForm", () => {
  beforeEach(() => {
    vi.mocked(api.listRegions).mockReset().mockResolvedValue({
      data: [REGION],
      page: { total: 1, page: 1, pageSize: 100 },
    });
    vi.mocked(api.createOrganization).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("shows field-level validation errors and does not submit when required fields are missing", async () => {
    renderForm();
    await screen.findByText("Northern Region");

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    expect(await screen.findByText("Organization name is required")).toBeInTheDocument();
    expect(screen.getByText("Region is required")).toBeInTheDocument();
    expect(screen.getByText("Org Admin name is required")).toBeInTheDocument();
    expect(api.createOrganization).not.toHaveBeenCalled();
  });

  it("requires at least one of Org Admin email or phone", async () => {
    renderForm();
    await screen.findByText("Northern Region");

    await userEvent.type(
      screen.getByPlaceholderText("e.g. Green Valley School"),
      "Green Valley School",
    );
    await userEvent.selectOptions(screen.getByLabelText("Region"), REGION.id);
    await userEvent.type(
      screen.getByPlaceholderText("e.g. Amina Warsame"),
      "Amina Warsame",
    );

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    expect(
      await screen.findByText("Provide an Org Admin email or phone number"),
    ).toBeInTheDocument();
    expect(api.createOrganization).not.toHaveBeenCalled();
  });

  it("rejects a malformed parent organization id", async () => {
    renderForm();
    await screen.findByText("Northern Region");

    await fillRequiredFields();
    await userEvent.type(screen.getByPlaceholderText("26-character ULID"), "not-a-ulid");

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    expect(
      await screen.findByText("Must be a valid organization ID (26-character ULID)"),
    ).toBeInTheDocument();
    expect(api.createOrganization).not.toHaveBeenCalled();
  });

  it("submits the exact OnboardOrganizationCommand-shaped payload and reveals the temporary password", async () => {
    vi.mocked(api.createOrganization).mockResolvedValue({
      organization: {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        name: "Green Valley School",
        orgType: "school",
        parentOrgId: null,
        regionId: REGION.id,
        status: "active",
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
      },
      adminUserId: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
      temporaryPassword: "Temp-Pw9!xyz",
    });

    const { onClose } = renderForm();
    await screen.findByText("Northern Region");

    await fillRequiredFields();

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    await waitFor(() =>
      expect(api.createOrganization).toHaveBeenCalledWith({
        name: "Green Valley School",
        orgType: "school",
        regionId: REGION.id,
        parentOrgId: null,
        adminFullName: "Amina Warsame",
        adminEmail: "amina@greenvalley.example.com",
        adminPhone: null,
      }),
    );

    // The temporary password is a one-time reveal — onClose must NOT fire until "Done".
    expect(await screen.findByText("Organization created")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Temp-Pw9!xyz")).toBeInTheDocument();
    // ADR-0017: the reveal also carries the Organization's own id, its login URL (this app's
    // own /login route — no separate "Organization Portal" domain), and the Org Admin's login
    // identifier captured from what was just submitted.
    expect(screen.getByDisplayValue("01ARZ3NDEKTSV4RRFFQ69G5FAV")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/\/login$/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("amina@greenvalley.example.com")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(useToastStore.getState().toasts[0]).toMatchObject({
      variant: "success",
      title: "Organization created",
    });

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("surfaces the backend error via a toast and keeps the drawer open on failure", async () => {
    const { ApiError } = await import("../../shared/api/types");
    vi.mocked(api.createOrganization).mockRejectedValue(
      new ApiError(403, { code: "FORBIDDEN", message: "Missing permission.", correlationId: null }),
    );

    const { onClose } = renderForm();
    await screen.findByText("Northern Region");

    await fillRequiredFields();

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Create failed",
        description: "Missing permission.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
