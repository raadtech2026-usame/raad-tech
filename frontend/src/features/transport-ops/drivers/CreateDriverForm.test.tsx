import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerDriver: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
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

const REGISTER_RESULT: api.RegisterDriverResult = {
  driver: {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
    organizationId: ORG_OPTION.id,
    userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
    licenseNo: "DL-00231",
    status: "active",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  },
  temporaryPassword: "Temp#1234",
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
    vi.mocked(api.registerDriver).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  describe("as founder", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("shows an organization picker", async () => {
      renderForm();

      expect(await screen.findByLabelText("Organization")).toBeInTheDocument();
      await screen.findByText(ORG_OPTION.name);
    });

    it("requires at least one of email or phone", async () => {
      renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Hassan Warsame"), "Hassan Warsame");
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");

      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      expect(
        await screen.findByText("At least one of email or phone is required, to create the driver's login."),
      ).toBeInTheDocument();
      expect(api.registerDriver).not.toHaveBeenCalled();
    });

    it("submits the exact RegisterDriverRequest shape and shows the one-time password on success", async () => {
      vi.mocked(api.registerDriver).mockResolvedValue(REGISTER_RESULT);
      const { onClose } = renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Hassan Warsame"), "Hassan Warsame");
      await userEvent.type(screen.getByPlaceholderText("e.g. hassan@example.com"), "hassan@example.com");
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");

      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      await waitFor(() =>
        expect(api.registerDriver).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          fullName: "Hassan Warsame",
          email: "hassan@example.com",
          phone: null,
          licenseNo: "DL-00231",
        }),
      );

      expect(await screen.findByText("Driver registered")).toBeInTheDocument();
      expect(screen.getByText("Temp#1234")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", { name: "Done" }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("as org_admin", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u2", role: "org_admin", organizationId: ORG_OPTION.id, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("hides the organization picker, using the caller's own organizationId", async () => {
      renderForm();

      await waitFor(() => expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument());
      expect(api.listOrganizationsForPicker).not.toHaveBeenCalled();
    });

    it("submits with the org's own organizationId and a phone-only login", async () => {
      vi.mocked(api.registerDriver).mockResolvedValue(REGISTER_RESULT);
      renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Hassan Warsame"), "Hassan Warsame");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");

      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      await waitFor(() =>
        expect(api.registerDriver).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          fullName: "Hassan Warsame",
          email: null,
          phone: "+252612345678",
          licenseNo: "DL-00231",
        }),
      );
    });

    it("surfaces a backend error via a toast and keeps the drawer open", async () => {
      vi.mocked(api.registerDriver).mockRejectedValue(
        new ApiError(422, { code: "VALIDATION_ERROR", message: "Request validation failed.", correlationId: null }),
      );
      const { onClose } = renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Hassan Warsame"), "Hassan Warsame");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");
      await userEvent.type(screen.getByPlaceholderText("e.g. DL-00231"), "DL-00231");

      await userEvent.click(screen.getByRole("button", { name: "Register driver" }));

      await waitFor(() =>
        expect(useToastStore.getState().toasts[0]).toMatchObject({
          variant: "error",
          title: "Registration failed",
          description: "Request validation failed.",
        }),
      );
      expect(onClose).not.toHaveBeenCalled();
    });
  });
});
