import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerDriver: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listDriverUsersForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateDriverForm } from "./CreateDriverForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const USER_OPTION: api.UserOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  fullName: "Hassan Warsame",
  email: "hassan@example.com",
  phone: null,
};

const DRIVER: api.Driver = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  organizationId: ORG_OPTION.id,
  userId: USER_OPTION.id,
  licenseNo: "DL-00231",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateDriverForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateDriverForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.listDriverUsersForPicker).mockReset().mockResolvedValue([USER_OPTION]);
    vi.mocked(api.registerDriver).mockReset();
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
      expect(screen.getByLabelText("Linked user")).toBeDisabled();

      await screen.findByText(ORG_OPTION.name);
      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);

      await waitFor(() => expect(api.listDriverUsersForPicker).toHaveBeenCalledWith(ORG_OPTION.id, ""));
      expect(await screen.findByText("Hassan Warsame — hassan@example.com")).toBeInTheDocument();
    });

    it("submits the exact RegisterDriverRequest shape using the picked user", async () => {
      vi.mocked(api.registerDriver).mockResolvedValue(DRIVER);
      const { onClose } = renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await screen.findByText("Hassan Warsame — hassan@example.com");
      await userEvent.selectOptions(screen.getByLabelText("Linked user"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");

      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      await waitFor(() =>
        expect(api.registerDriver).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          userId: USER_OPTION.id,
          licenseNo: "DL-00231",
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
      expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Driver registered" });
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
      expect(api.listDriverUsersForPicker).not.toHaveBeenCalled();
    });

    it("rejects a manually-entered user id that isn't a valid ULID", async () => {
      renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), "not-a-ulid");
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");
      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      expect(await screen.findByText("Must be a valid user ID (26-character ULID)")).toBeInTheDocument();
      expect(api.registerDriver).not.toHaveBeenCalled();
    });

    it("submits a valid manually-entered user id with the org's own organizationId", async () => {
      vi.mocked(api.registerDriver).mockResolvedValue(DRIVER);
      const { onClose } = renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");
      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      await waitFor(() =>
        expect(api.registerDriver).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          userId: USER_OPTION.id,
          licenseNo: "DL-00231",
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    });

    it("surfaces a backend error via a toast and keeps the drawer open", async () => {
      vi.mocked(api.registerDriver).mockRejectedValue(
        new ApiError(404, { code: "NOT_FOUND", message: "User 01XYZ not found.", correlationId: null }),
      );
      const { onClose } = renderForm();

      await userEvent.type(screen.getByLabelText("Linked user ID"), USER_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");
      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

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
