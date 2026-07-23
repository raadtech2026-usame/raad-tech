import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  enrollStudent: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateStudentForm } from "./CreateStudentForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const STUDENT: api.Student = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: ORG_OPTION.id,
  fullName: "Amina Hassan",
  externalRef: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateStudentForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateStudentForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.enrollStudent).mockReset();
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
    vi.mocked(api.enrollStudent).mockResolvedValue(STUDENT);

    renderForm();

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.click(screen.getByRole("button", { name: "Enroll student" }));

    await waitFor(() =>
      expect(api.enrollStudent).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        fullName: "Amina Hassan",
        externalRef: null,
      }),
    );
  });

  it("shows field-level validation errors and does not submit when required fields are missing", async () => {
    renderForm();
    await screen.findByLabelText("Organization");

    await userEvent.click(screen.getByRole("button", { name: "Enroll student" }));

    expect(await screen.findByText("Organization is required")).toBeInTheDocument();
    expect(screen.getByText("Full name is required")).toBeInTheDocument();
    expect(api.enrollStudent).not.toHaveBeenCalled();
  });

  it("submits the exact EnrollStudentRequest-shaped payload and reports success", async () => {
    vi.mocked(api.enrollStudent).mockResolvedValue({ ...STUDENT, externalRef: "STU-00231" });

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.type(screen.getByPlaceholderText("e.g. STU-00231"), "STU-00231");

    await userEvent.click(screen.getByRole("button", { name: "Enroll student" }));

    await waitFor(() =>
      expect(api.enrollStudent).toHaveBeenCalledWith({
        organizationId: ORG_OPTION.id,
        fullName: "Amina Hassan",
        externalRef: "STU-00231",
      }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(useToastStore.getState().toasts[0]).toMatchObject({
      variant: "success",
      title: "Student enrolled",
    });
  });

  it("surfaces a backend validation error via a toast and keeps the drawer open", async () => {
    vi.mocked(api.enrollStudent).mockRejectedValue(
      new ApiError(422, {
        code: "VALIDATION_ERROR",
        message: "Student full_name must not be empty",
        correlationId: null,
      }),
    );

    const { onClose } = renderForm();
    await screen.findByText(ORG_OPTION.name);

    await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Amina Hassan");
    await userEvent.click(screen.getByRole("button", { name: "Enroll student" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Enrollment failed",
        description: "Student full_name must not be empty",
      }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
