import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listStudents: vi.fn(),
  getStudent: vi.fn(),
  enrollStudent: vi.fn(),
  updateStudentStatus: vi.fn(),
  listGuardiansForStudent: vi.fn(),
  linkGuardianToStudent: vi.fn(),
  unlinkGuardianFromStudent: vi.fn(),
  listParentsForPicker: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

// `StudentAssignmentSection`/`AssignStudentForm` (Phase F6) are rendered inside this page's own
// detail drawer now — mocked here the same way every other cross-module dependency of this test
// file already is, defaulting `findActiveAssignmentForStudent` to `null` so the section settles
// into its honest "No active route assignment" state without any test needing to care about it.
vi.mock("../student-assignments/api", () => ({
  findActiveAssignmentForStudent: vi.fn(),
  getRouteWithStops: vi.fn(),
  listRoutesForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  assignStudentToRoute: vi.fn(),
  endStudentAssignment: vi.fn(),
}));

import * as api from "./api";
import * as assignmentApi from "../student-assignments/api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { StudentsPage } from "./StudentsPage";

const STUDENT_SUMMARY: api.StudentSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  fullName: "Amina Hassan",
  status: "active",
};

const STUDENT_DETAIL: api.Student = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  fullName: "Amina Hassan",
  externalRef: "STU-00231",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
};

const GUARDIAN: api.GuardianLink = {
  parentId: "01ARZ3NDEKTSV4RRFFQ69G5FCX",
  fullName: "Fatima Ali",
  phone: "+252612345678",
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
      <StudentsPage />
    </QueryClientProvider>,
  );
}

describe("StudentsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listStudents).mockReset();
    vi.mocked(api.getStudent).mockReset().mockResolvedValue(STUDENT_DETAIL);
    vi.mocked(api.updateStudentStatus).mockReset();
    vi.mocked(api.listGuardiansForStudent).mockReset().mockResolvedValue([]);
    vi.mocked(api.unlinkGuardianFromStudent).mockReset();
    vi.mocked(api.listParentsForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
    vi.mocked(assignmentApi.findActiveAssignmentForStudent).mockReset().mockResolvedValue(null);
    vi.mocked(assignmentApi.getRouteWithStops).mockReset();
    vi.mocked(assignmentApi.listRoutesForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(assignmentApi.listVehiclesForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(assignmentApi.assignStudentToRoute).mockReset();
    vi.mocked(assignmentApi.endStudentAssignment).mockReset();
  });

  it("renders skeleton state while loading, then the fetched students (name + status only)", async () => {
    let resolvePage!: (value: OffsetPage<api.StudentSummary>) => void;
    vi.mocked(api.listStudents).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Amina Hassan")).not.toBeInTheDocument();

    resolvePage(pageOf([STUDENT_SUMMARY], 1));

    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    expect(within(screen.getByRole("table")).getByText("Active")).toBeInTheDocument();
  });

  it("shows an empty state when there are no students", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No students yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listStudents).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load students")).toBeInTheDocument());
  });

  it("opens the detail drawer and fetches the full student record for the richer fields", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getStudent).toHaveBeenCalledWith(STUDENT_SUMMARY.id));
    expect(await within(dialog).findByText("Green Valley School")).toBeInTheDocument();
    expect(within(dialog).getByText("STU-00231")).toBeInTheDocument();
  });

  it("shows the linked guardians and lets a founder unlink one", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(api.listGuardiansForStudent).mockResolvedValue([GUARDIAN]);
    vi.mocked(api.unlinkGuardianFromStudent).mockResolvedValue(undefined);

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Fatima Ali · Primary")).toBeInTheDocument();
    expect(within(dialog).getByText("Mother · +252612345678")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Unlink Fatima Ali" }));

    await waitFor(() =>
      expect(api.unlinkGuardianFromStudent).toHaveBeenCalledWith(STUDENT_SUMMARY.id, GUARDIAN.parentId),
    );
  });

  it("shows 'No guardians linked yet' when the student has no guardians", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(api.listGuardiansForStudent).mockResolvedValue([]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("No guardians linked yet.")).toBeInTheDocument();
  });

  it("lets a founder mark an active student as graduated from the detail drawer", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(api.updateStudentStatus).mockResolvedValue({ ...STUDENT_DETAIL, status: "graduated" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark graduated" }));

    await waitFor(() =>
      expect(api.updateStudentStatus).toHaveBeenCalledWith(STUDENT_SUMMARY.id, "graduated"),
    );
  });

  it("shows the CR-1 gate's current state and lets a founder assign a student with no active route", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(assignmentApi.findActiveAssignmentForStudent).mockResolvedValue(null);

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("No active route assignment.")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Assign to route" }));
    expect(await screen.findByText("Assign Amina Hassan to a route")).toBeInTheDocument();
  });

  it("hides the New Student action, Add guardian action, and status actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(api.listGuardiansForStudent).mockResolvedValue([GUARDIAN]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Student/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Amina Hassan"));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Fatima Ali · Primary");

    expect(within(dialog).queryByRole("button", { name: "Mark graduated" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Add guardian" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Unlink Fatima Ali" })).not.toBeInTheDocument();
  });
});
