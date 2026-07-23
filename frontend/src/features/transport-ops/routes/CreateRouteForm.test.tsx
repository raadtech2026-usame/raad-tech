import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  createRoute: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToastStore } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { CreateRouteForm } from "./CreateRouteForm";

const ORG_OPTION: api.OrganizationOption = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Green Valley School",
};

const ROUTE: api.Route = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  organizationId: ORG_OPTION.id,
  name: "Morning Route A",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  stops: [],
};

function renderForm(onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateRouteForm open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateRouteForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.createRoute).mockReset();
    useToastStore.setState({ toasts: [] });
  });

  describe("as founder (no organization of their own)", () => {
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

    it("submits the exact CreateRouteRequest shape using the picked organization", async () => {
      vi.mocked(api.createRoute).mockResolvedValue(ROUTE);
      const { onClose } = renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Morning Route A"), "Morning Route A");
      await userEvent.click(screen.getByRole("button", { name: "Create route" }));

      await waitFor(() =>
        expect(api.createRoute).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          name: "Morning Route A",
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
      expect(useToastStore.getState().toasts[0]).toMatchObject({ variant: "success", title: "Route created" });
    });
  });

  describe("as org_admin (uses their own organization)", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u2", role: "org_admin", organizationId: ORG_OPTION.id, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("hides the organization picker entirely", async () => {
      renderForm();

      await waitFor(() => expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument());
    });

    it("requires a non-empty route name", async () => {
      renderForm();

      await userEvent.click(screen.getByRole("button", { name: "Create route" }));

      expect(await screen.findByText("Route name is required")).toBeInTheDocument();
      expect(api.createRoute).not.toHaveBeenCalled();
    });

    it("submits with the org's own organizationId", async () => {
      vi.mocked(api.createRoute).mockResolvedValue(ROUTE);
      const { onClose } = renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Morning Route A"), "Morning Route A");
      await userEvent.click(screen.getByRole("button", { name: "Create route" }));

      await waitFor(() =>
        expect(api.createRoute).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          name: "Morning Route A",
        }),
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    });

    it("surfaces a backend error via a toast and keeps the drawer open", async () => {
      vi.mocked(api.createRoute).mockRejectedValue(
        new ApiError(409, { code: "CONFLICT", message: "A route with this name already exists.", correlationId: null }),
      );
      const { onClose } = renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Morning Route A"), "Morning Route A");
      await userEvent.click(screen.getByRole("button", { name: "Create route" }));

      await waitFor(() =>
        expect(useToastStore.getState().toasts[0]).toMatchObject({
          variant: "error",
          title: "Create failed",
          description: "A route with this name already exists.",
        }),
      );
      expect(onClose).not.toHaveBeenCalled();
    });
  });
});
