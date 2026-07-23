import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listParents: vi.fn(),
  getParent: vi.fn(),
  registerParent: vi.fn(),
  updateParentStatus: vi.fn(),
  listStudentsForParent: vi.fn(),
  unlinkStudentFromParent: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listParentUsersForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ParentsPage } from "./ParentsPage";

const PARENT_SUMMARY: api.ParentSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  fullName: "Fatima Ali",
  status: "active",
};

const PARENT_DETAIL: api.Parent = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  fullName: "Fatima Ali",
  phone: "+252612345678",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
};

const LINKED_STUDENT: api.LinkedStudent = {
  studentId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  fullName: "Amina Hassan",
  status: "active",
  relationship: "Mother",
  isPrimary: true,
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ParentsPage />
    </QueryClientProvider>,
  );
}

describe("ParentsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listParents).mockReset();
    vi.mocked(api.getParent).mockReset().mockResolvedValue(PARENT_DETAIL);
    vi.mocked(api.updateParentStatus).mockReset();
    vi.mocked(api.listStudentsForParent).mockReset().mockResolvedValue([]);
    vi.mocked(api.unlinkStudentFromParent).mockReset();
    vi.mocked(api.listParentUsersForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("renders skeleton state while loading, then the fetched parents (name + status only)", async () => {
    let resolvePage!: (value: OffsetPage<api.ParentSummary>) => void;
    vi.mocked(api.listParents).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Fatima Ali")).not.toBeInTheDocument();

    resolvePage(pageOf([PARENT_SUMMARY], 1));

    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());
    expect(within(screen.getByRole("table")).getByText("Active")).toBeInTheDocument();
  });

  it("shows an empty state when there are no parents", async () => {
    vi.mocked(api.listParents).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No parents yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listParents).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load parents")).toBeInTheDocument());
  });

  it("opens the detail drawer and fetches the full parent record for the richer fields", async () => {
    vi.mocked(api.listParents).mockResolvedValue(pageOf([PARENT_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Fatima Ali"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getParent).toHaveBeenCalledWith(PARENT_SUMMARY.id));
    expect(await within(dialog).findByText("Green Valley School")).toBeInTheDocument();
    expect(within(dialog).getByText("+252612345678")).toBeInTheDocument();
  });

  it("shows the linked students (the mirror image of StudentsPage's Guardians section) and lets a founder unlink one", async () => {
    vi.mocked(api.listParents).mockResolvedValue(pageOf([PARENT_SUMMARY], 1));
    vi.mocked(api.listStudentsForParent).mockResolvedValue([LINKED_STUDENT]);
    vi.mocked(api.unlinkStudentFromParent).mockResolvedValue(undefined);

    renderPage();
    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Fatima Ali"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Amina Hassan · Primary guardian")).toBeInTheDocument();
    expect(within(dialog).getByText("Mother")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Unlink Amina Hassan" }));

    await waitFor(() =>
      expect(api.unlinkStudentFromParent).toHaveBeenCalledWith(PARENT_SUMMARY.id, LINKED_STUDENT.studentId),
    );
  });

  it("shows 'No students linked yet' when the parent has no linked students, and never offers an add-student action", async () => {
    vi.mocked(api.listParents).mockResolvedValue(pageOf([PARENT_SUMMARY], 1));
    vi.mocked(api.listStudentsForParent).mockResolvedValue([]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Fatima Ali"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("No students linked yet.")).toBeInTheDocument();
    // Link creation is Student-side only (LinkGuardianForm) — this drawer never offers one.
    expect(within(dialog).queryByRole("button", { name: /add student/i })).not.toBeInTheDocument();
  });

  it("lets a founder deactivate an active parent from the detail drawer", async () => {
    vi.mocked(api.listParents).mockResolvedValue(pageOf([PARENT_SUMMARY], 1));
    vi.mocked(api.updateParentStatus).mockResolvedValue({ ...PARENT_DETAIL, status: "inactive" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Fatima Ali"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(api.updateParentStatus).toHaveBeenCalledWith(PARENT_SUMMARY.id, "inactive"));
  });

  it("hides the New Parent action and drawer management actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listParents).mockResolvedValue(pageOf([PARENT_SUMMARY], 1));
    vi.mocked(api.listStudentsForParent).mockResolvedValue([LINKED_STUDENT]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Fatima Ali")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Parent/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Fatima Ali"));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Amina Hassan · Primary guardian");

    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Unlink Amina Hassan" })).not.toBeInTheDocument();
  });
});
