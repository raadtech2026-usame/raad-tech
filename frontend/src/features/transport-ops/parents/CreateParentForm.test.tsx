import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  registerParent: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  findParentByExactPhone: vi.fn(),
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

const PARENT: api.Parent = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  organizationId: ORG_OPTION.id,
  userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  fullName: "Fatima Ali",
  phone: "+252612345678",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  alternatePhone: null,
  address: null,
  emergencyContactName: null,
  emergencyContactPhone: null,
  notes: null,
};

const REGISTERED: api.RegisterParentResult = {
  parent: PARENT,
  temporaryPassword: "Tmp-Pass-123",
  children: [],
};

function renderForm(onClose = vi.fn(), onOpenExisting = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateParentForm open onClose={onClose} onOpenExisting={onOpenExisting} />
    </QueryClientProvider>,
  );
  return { onClose, onOpenExisting };
}

describe("CreateParentForm", () => {
  beforeEach(() => {
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG_OPTION]);
    vi.mocked(api.registerParent).mockReset();
    vi.mocked(api.findParentByExactPhone).mockReset().mockResolvedValue(null);
    useToastStore.setState({ toasts: [] });
  });

  describe("as founder (sees an organization picker)", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("shows an organization picker and no linked-user field", async () => {
      renderForm();

      expect(await screen.findByLabelText("Organization")).toBeInTheDocument();
      expect(screen.queryByLabelText("Linked user")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Linked user ID")).not.toBeInTheDocument();
    });

    it("submits the current RegisterParentRequest shape, with no user_id", async () => {
      vi.mocked(api.registerParent).mockResolvedValue(REGISTERED);
      renderForm();
      await screen.findByText(ORG_OPTION.name);

      await userEvent.selectOptions(screen.getByLabelText("Organization"), ORG_OPTION.id);
      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");

      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      await waitFor(() =>
        expect(api.registerParent).toHaveBeenCalledWith({
          organizationId: ORG_OPTION.id,
          fullName: "Fatima Ali",
          email: null,
          phone: "+252612345678",
          alternatePhone: null,
          address: null,
          emergencyContactName: null,
          emergencyContactPhone: null,
          notes: null,
          children: [],
          routeId: null,
          pickupStopId: null,
          dropoffStopId: null,
          vehicleId: null,
        }),
      );
      // Success switches to the temporary-password hand-off panel rather than closing.
      expect(await screen.findByText("Tmp-Pass-123")).toBeInTheDocument();
    });
  });

  describe("as org_admin (own organization is implicit)", () => {
    beforeEach(() => {
      useAuthStore.setState({
        principal: { userId: "u2", role: "org_admin", organizationId: ORG_OPTION.id, regionIds: [] },
        accessToken: "t",
        refreshToken: "r",
        status: "authenticated",
        error: null,
      });
    });

    it("hides the organization picker", async () => {
      renderForm();
      await waitFor(() => expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument());
    });

    it("requires at least one of email or phone", async () => {
      renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      expect(
        await screen.findByText("At least one of email or phone is required, to create the parent's login."),
      ).toBeInTheDocument();
      expect(api.registerParent).not.toHaveBeenCalled();
    });

    it("validates phone as E.164 format when provided", async () => {
      renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "0612345678");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      expect(await screen.findByText("Phone must be E.164 format, e.g. +252612345678")).toBeInTheDocument();
      expect(api.registerParent).not.toHaveBeenCalled();
    });

    it("shows a duplicate-phone warning and lets the admin open the existing parent", async () => {
      const existing: api.ParentSummary = { id: "01ARZ3NDEKTSV4RRFFQ69G5FCX", fullName: "Ahmed Mohamed", status: "active" };
      vi.mocked(api.findParentByExactPhone).mockResolvedValue(existing);
      const { onOpenExisting } = renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");

      expect(await screen.findByText(/A parent with this phone number already exists/)).toBeInTheDocument();
      expect(screen.getByText("Ahmed Mohamed")).toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Open existing parent" }));
      expect(onOpenExisting).toHaveBeenCalledWith(existing);
    });

    it("surfaces a backend error via a toast and keeps the drawer open", async () => {
      vi.mocked(api.registerParent).mockRejectedValue(
        new ApiError(409, { code: "CONFLICT", message: "Phone already in use.", correlationId: null }),
      );
      const { onClose } = renderForm();

      await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
      await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");
      await userEvent.click(screen.getByRole("button", { name: "Register parent" }));

      await waitFor(() =>
        expect(useToastStore.getState().toasts[0]).toMatchObject({
          variant: "error",
          title: "Registration failed",
          description: "Phone already in use.",
        }),
      );
      expect(onClose).not.toHaveBeenCalled();
    });

    describe("children (ADR-0041 §2)", () => {
      it("starts with no children and lets the admin add one", async () => {
        renderForm();
        expect(screen.queryByText("Student 1")).not.toBeInTheDocument();

        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        expect(screen.getByText("Student 1")).toBeInTheDocument();
        // The submit button relabels once at least one child is present.
        expect(screen.getByRole("button", { name: "Save parent & children" })).toBeInTheDocument();
      });

      it("removes a child row", async () => {
        renderForm();
        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        expect(screen.getByText("Student 1")).toBeInTheDocument();
        expect(screen.getByText("Student 2")).toBeInTheDocument();

        await userEvent.click(screen.getByRole("button", { name: "Remove student 1" }));
        expect(screen.queryByText("Student 2")).not.toBeInTheDocument();
        expect(screen.getByText("Student 1")).toBeInTheDocument();
      });

      it("requires a full name for every added child before submitting", async () => {
        renderForm();
        await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Fatima Ali");
        await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");
        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        await userEvent.click(screen.getByRole("button", { name: "Save parent & children" }));

        expect(await screen.findByText("Child's full name is required")).toBeInTheDocument();
        expect(api.registerParent).not.toHaveBeenCalled();
      });

      it("submits the parent and every child together in one call", async () => {
        vi.mocked(api.registerParent).mockResolvedValue({
          ...REGISTERED,
          children: [
            { id: "s1", fullName: "Mohamed Ahmed", dateOfBirth: "2015-01-01", gender: "male", status: "active" },
            { id: "s2", fullName: "Aisha Ahmed", dateOfBirth: null, gender: null, status: "active" },
          ],
        });
        renderForm();

        await userEvent.type(screen.getByPlaceholderText("e.g. Fatima Ali"), "Ahmed Mohamed");
        await userEvent.type(screen.getByPlaceholderText("+252612345678"), "+252612345678");

        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        await userEvent.type(screen.getByPlaceholderText("e.g. Mohamed Ahmed"), "Mohamed Ahmed");

        await userEvent.click(screen.getByRole("button", { name: "Add student" }));
        const secondNameInputs = screen.getAllByPlaceholderText("e.g. Mohamed Ahmed");
        await userEvent.type(secondNameInputs[1], "Aisha Ahmed");

        await userEvent.click(screen.getByRole("button", { name: "Save parent & children" }));

        await waitFor(() =>
          expect(api.registerParent).toHaveBeenCalledWith(
            expect.objectContaining({
              fullName: "Ahmed Mohamed",
              children: [
                expect.objectContaining({ fullName: "Mohamed Ahmed" }),
                expect.objectContaining({ fullName: "Aisha Ahmed" }),
              ],
            }),
          ),
        );

        // Success panel names the created children too.
        expect(await screen.findByText("2 children registered")).toBeInTheDocument();
        expect(screen.getByText("Mohamed Ahmed")).toBeInTheDocument();
        expect(screen.getByText("Aisha Ahmed")).toBeInTheDocument();
      });
    });
  });
});
