import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  inviteUser: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  ASSIGNABLE_ROLES: [
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
  ],
  isOrgScopedRole: (role: string) => ["org_admin", "driver", "parent"].includes(role),
}));

import * as api from "./api";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { InviteUserForm } from "./InviteUserForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <InviteUserForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("InviteUserForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.inviteUser).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  it("shows field-level validation errors and does not submit when required fields are missing", async () => {
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    expect(await screen.findByText("Full name is required")).toBeInTheDocument();
    expect(screen.getByText("Role is required")).toBeInTheDocument();
    expect(api.inviteUser).not.toHaveBeenCalled();
  });

  it("requires an email or a phone number when both are blank", async () => {
    renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "founder");
    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    expect(await screen.findAllByText("Provide an email or a phone number")).toHaveLength(2);
    expect(api.inviteUser).not.toHaveBeenCalled();
  });

  it("rejects a malformed phone number", async () => {
    renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "founder");
    await userEvent.type(screen.getByPlaceholderText("+252612345678"), "not-a-phone");
    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    expect(
      await screen.findByText("Phone must be E.164 format, e.g. +252612345678"),
    ).toBeInTheDocument();
    expect(api.inviteUser).not.toHaveBeenCalled();
  });

  it("reveals the organization picker only for an org-scoped role and requires it", async () => {
    renderForm();

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Role"), "org_admin");

    expect(await screen.findByLabelText("Organization")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.type(screen.getByPlaceholderText("name@example.com"), "amina@greenvalley.example");
    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    expect(await screen.findByText("Organization is required for this role")).toBeInTheDocument();
    expect(api.inviteUser).not.toHaveBeenCalled();
  });

  it("does not show the organization picker for a RAAD-staff role", async () => {
    renderForm();

    await userEvent.selectOptions(screen.getByLabelText("Role"), "regional_manager");

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();
  });

  it("submits the exact CreateUserRequest-shaped payload for an org-scoped role", async () => {
    vi.mocked(api.inviteUser).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      organizationId: ORG_OPTION.id,
      role: "org_admin",
      email: "amina@greenvalley.example",
      phone: null,
      fullName: "Amina Hassan",
      status: "invited",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
      mfaEnabled: false,
      lastLoginAt: null,
    });

    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "org_admin");
    await screen.findByLabelText("Organization");
    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("name@example.com"), "amina@greenvalley.example");

    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    await waitFor(() =>
      expect(api.inviteUser).toHaveBeenCalledWith({
        fullName: "Amina Hassan",
        role: "org_admin",
        email: "amina@greenvalley.example",
        phone: null,
        organizationId: ORG_OPTION.id,
      }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({
      variant: "success",
      title: "User invited",
    });
  });

  it("submits with a null organizationId for a RAAD-staff role", async () => {
    vi.mocked(api.inviteUser).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      organizationId: null,
      role: "regional_manager",
      email: "sara@raad.example",
      phone: null,
      fullName: "Sara Ali",
      status: "invited",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
      mfaEnabled: false,
      lastLoginAt: null,
    });

    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Sara Ali");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "regional_manager");
    await userEvent.type(screen.getByPlaceholderText("name@example.com"), "sara@raad.example");

    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    await waitFor(() =>
      expect(api.inviteUser).toHaveBeenCalledWith({
        fullName: "Sara Ali",
        role: "regional_manager",
        email: "sara@raad.example",
        phone: null,
        organizationId: null,
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("surfaces the backend error via a toast and keeps the drawer open on failure", async () => {
    const { ApiError } = await import("../../../shared/api/types");
    vi.mocked(api.inviteUser).mockRejectedValue(
      new ApiError(403, { code: "FORBIDDEN", message: "Missing permission.", correlationId: null }),
    );

    const { onClose } = renderForm();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "founder");
    await userEvent.type(screen.getByPlaceholderText("name@example.com"), "amina@example.com");

    await userEvent.click(screen.getByRole("button", { name: "Invite user" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Invite failed",
        description: "Missing permission.",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
