import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  createOrganization: vi.fn(),
  listRegions: vi.fn(),
}));
vi.mock("../billing/api", () => ({ listActivePlansForPicker: vi.fn() }));

import * as api from "./api";
import { listActivePlansForPicker } from "../billing/api";
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
    vi.mocked(listActivePlansForPicker).mockReset().mockResolvedValue([
      {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FCP",
        name: "Standard",
        billingScope: "organization",
        amount: 199,
        currency: "USD",
        billingCycle: "monthly",
        vehicleLimit: 10,
        deviceLimit: 20,
        userLimit: null,
        status: "active",
        createdAt: "2026-08-01T00:00:00Z",
        updatedAt: "2026-08-01T00:00:00Z",
      },
    ]);
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
        // ADR-0040 §5: optional, and null when the operator onboards without picking a tier.
        planId: null,
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

  it("sends the chosen plan so onboarding opens the subscription in the same request", async () => {
    // ADR-0040 §5. Without this the organization is created with no subscription and its Org
    // Admin meets ADR-0039's subscription-inactive gate on first login — the whole reason plan
    // selection belongs in the onboarding request rather than a separate follow-up step.
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
      adminUserId: "01ARZ3NDEKTSV4RRFFQ69G5FAX",
      temporaryPassword: "Temp-Pass-1234",
    });

    renderForm();
    await screen.findByText("Northern Region");
    await fillRequiredFields();
    // `FormField` wraps its control in the `<label>`, so the accessible name carries the hint
    // text too — matched by prefix rather than exact string.
    await userEvent.selectOptions(
      await screen.findByLabelText(/^Subscription plan/),
      "01ARZ3NDEKTSV4RRFFQ69G5FCP",
    );

    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));

    await waitFor(() =>
      expect(api.createOrganization).toHaveBeenCalledWith(
        expect.objectContaining({ planId: "01ARZ3NDEKTSV4RRFFQ69G5FCP" }),
      ),
    );
  });
});
