import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listUsers: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  updateUserStatus: vi.fn(),
  updateUserMfa: vi.fn(),
  inviteUser: vi.fn(),
  resetUserPassword: vi.fn(),
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
import { useAuthStore } from "../../../shared/stores/authStore";
import { UsersPage } from "./UsersPage";

const USER: api.User = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  role: "org_admin",
  email: "amina@greenvalley.example",
  phone: null,
  fullName: "Amina Hassan",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  mfaEnabled: false,
  lastLoginAt: "2026-01-03T08:00:00Z",
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <UsersPage />
    </QueryClientProvider>,
  );
}

describe("UsersPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listUsers).mockReset();
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
    vi.mocked(api.updateUserStatus).mockReset();
    vi.mocked(api.updateUserMfa).mockReset();
    vi.mocked(api.resetUserPassword).mockReset();
  });

  it("renders skeleton state while loading, then the fetched users", async () => {
    let resolvePage!: (value: OffsetPage<api.User>) => void;
    vi.mocked(api.listUsers).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    // Loading: the table shell is present, but no real row data has rendered yet.
    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Amina Hassan")).not.toBeInTheDocument();

    resolvePage(pageOf([USER], 1));

    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    expect(screen.getByText("Green Valley School")).toBeInTheDocument();
    const table = document.querySelector("table") as HTMLTableElement;
    expect(within(table).getByText("Org Admin")).toBeInTheDocument();
  });

  it("shows an empty state when there are no users", async () => {
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No users yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listUsers).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load users")).toBeInTheDocument());
  });

  it("opens the detail drawer with the user's details on row click", async () => {
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([USER], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Email")).toBeInTheDocument();
    expect(within(dialog).getByText("amina@greenvalley.example")).toBeInTheDocument();
    expect(within(dialog).getByText(USER.id)).toBeInTheDocument();
  });

  it("lets a founder disable an active user from the detail drawer", async () => {
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([USER], 1));
    vi.mocked(api.updateUserStatus).mockResolvedValue({ ...USER, status: "disabled" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Disable" }));

    await waitFor(() =>
      expect(api.updateUserStatus).toHaveBeenCalledWith("01ARZ3NDEKTSV4RRFFQ69G5FAV", "disabled"),
    );
  });

  it("hides the Invite user action and drawer management actions for a non-founder role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([USER], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /Invite user/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Amina Hassan"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
  });

  it("lets a founder reset a user's password from the detail drawer", async () => {
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([USER], 1));
    vi.mocked(api.resetUserPassword).mockResolvedValue({
      user: USER,
      temporaryPassword: "Sw4pped!Pass9000",
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));

    // Both the detail drawer's trigger and the confirmation drawer's own button share the
    // label "Reset password" and may both be mounted at once - scope to the most recently
    // opened dialog rather than assuming a single global match.
    const dialogs = await screen.findAllByRole("dialog");
    const resetDialog = dialogs[dialogs.length - 1];
    await userEvent.click(within(resetDialog).getByRole("button", { name: "Reset password" }));

    await waitFor(() =>
      expect(api.resetUserPassword).toHaveBeenCalledWith("01ARZ3NDEKTSV4RRFFQ69G5FAV"),
    );
    expect(await screen.findByDisplayValue("Sw4pped!Pass9000")).toBeInTheDocument();
  });

  it("regional_manager sees the Reset password action but not Activate/Disable", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listUsers).mockResolvedValue(pageOf([USER], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Reset password" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });
});
