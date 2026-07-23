import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerParent: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listParentUsersForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateParentForm } from "./CreateParentForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const USER_OPTION: api.UserOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  fullName: "Fatima Ali",
  email: "fatima@example.com",
  phone: null,
};

const PARENT: api.Parent = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  organizationId: ORG_OPTION.id,
  userId: USER_OPTION.id,
  fullName: "Fatima Ali",
  phone: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateParentForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateParentForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.listParentUsersForPicker).mockReset().mockResolvedValue([USER_OPTION]);
    vi.mocked(api.registerParent).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  describe("as founder (holds iam.users.read)", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("shows an organization picker and, once an organization is chosen, a real user picker", async () => {
      renderForm();

      expect(await screen.findByLabelText("Organization")).toBeInTheDocument();
      // The user picker exists but is disabled until an organization is selected.
      expect(screen.getByLabelText("Linked user")).toBeDisabled();

      await screen.findByText(ORG_OPTION.name);
      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);

      await waitFor(() => expect(api.listParentUsersForPicker).toHaveBeenCalledWith(ORG_OPTION.id, ""));
      expect(await screen.findByText("Fatima Ali — fatima@example.com")).toBeInTheDocument();
    });

    it("submits the exact RegisterParentRequest shape using the picked user", async () => {
      vi.mocked(api.registerParent).mockResolvedValue(PARENT);
      const { onClose } = renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await screen.findByText("Fatima Ali — fatima@example.com");
      await userEvent.selectOptions(screen.getByLabelText("Linked user"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");

      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      await waitFor(() =>
        expect(api.registerParent).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          userId: USER_OPTION.id,
          fullName: "Fatima Ali",
          phone: null,
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
      expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Parent registered" });
    });
  });

  describe("as org_admin (holds no iam.users.* permission)", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u2", role: "org_admin", organizationId: ORG_OPTION.id, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("hides both the organization picker and the user picker, showing a manual user-id field instead", async () => {
      renderForm();

      await waitFor(() => expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument());
      expect(screen.queryByLabelText("Linked user")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Linked user ID")).toBeInTheDocument();
      // org_admin holds no iam.users.read, so this form never calls GET /users for them.
      expect(api.listParentUsersForPicker).not.toHaveBeenCalled();
    });

    it("rejects a manually-entered user id that isn't a valid ULID", async () => {
      renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), "not-a-ulid");
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      expect(await screen.findByText("Must be a valid user ID (26-character ULID)")).toBeInTheDocument();
      expect(api.registerParent).not.toHaveBeenCalled();
    });

    it("submits a valid manually-entered user id with the org's own organizationId", async () => {
      vi.mocked(api.registerParent).mockResolvedValue(PARENT);
      const { onClose } = renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      await waitFor(() =>
        expect(api.registerParent).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          userId: USER_OPTION.id,
          fullName: "Fatima Ali",
          phone: null,
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    });

    it("validates phone as E.164 format when provided", async () => {
      renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.type(screen.getByPlaceholderText("e.g. +252612345678"), "0612345678");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      expect(await screen.findByText("Phone must be E.164 format, e.g. +252612345678")).toBeInTheDocument();
      expect(api.registerParent).not.toHaveBeenCalled();
    });

    it("surfaces a backend error via a toast and keeps the drawer open", async () => {
      vi.mocked(api.registerParent).mockRejectedValue(
        new ApiError(404, { code: "NOT_FOUND", message: "User 01XYZ not found.", correlationId: null }),
      );
      const { onClose } = renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      await waitFor(() =>
        expect(useToastStore.getState().toasts[0]).toMatchObject({
          variant: "error",
          title: "Registration failed",
          description: "User 01XYZ not found.",
        }),
      );
      expect(onClose).not.toHaveBeenCalled();
    });
  });
});
