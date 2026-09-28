import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listStudents: vi.fn(),
  getStudent: vi.fn(),
  enrollStudent: vi.fn(),
  updateStudent: vi.fn(),
  updateStudentStatus: vi.fn(),
  listGuardiansForStudent: vi.fn(),
  linkGuardianToStudent: vi.fn(),
  unlinkGuardianFromStudent: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

// `LinkGuardianForm` now uses `ParentSearchSelect` (`../parents/ParentSearchSelect.tsx`), which
// reads `../parents/api.ts` directly rather than a `./api.ts` picker — mocked here the same way
// every other cross-module dependency of this test file already is.
vi.mock("../parents/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../parents/api")>()),
  listParentsForPicker: vi.fn(),
  getParent: vi.fn(),
  listStudentsForParent: vi.fn(),
  getParentInvoiceDetail: vi.fn(),
  recordParentPayment: vi.fn(),
  setStudentBillingFee: vi.fn(),
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

// `StudentFinanceSection` (school_erp, ADR-0047) is a cross-bounded-context component in the
// detail drawer — mocked via `importOriginal` so only its reads are fake and the formatting
// helpers stay real.
vi.mock("../../school-erp/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../school-erp/api")>()),
  getStudentFinance: vi.fn(),
  voidStudentPayment: vi.fn(),
}));

import * as api from "./api";
import * as parentsApi from "../parents/api";
import * as assignmentApi from "../student-assignments/api";
import * as schoolErpApi from "../../school-erp/api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { StudentsPage } from "./StudentsPage";

const EMPTY_FINANCE: schoolErpApi.StudentFinance = {
  studentId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  fullName: "Amina Hassan",
  status: "active",
  parents: [],
  currency: "USD",
  totalCharged: "0.00",
  totalPaid: "0.00",
  balanceDue: "0.00",
  charges: [],
  payments: [],
  legacyInvoices: [],
  legacyPayments: [],
  monthlyFee: null,
  monthlyFeeCurrency: null,
};

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
  dateOfBirth: null,
  gender: null,
  notes: null,
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
    vi.mocked(api.updateStudent).mockReset();
    vi.mocked(parentsApi.listParentsForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(parentsApi.getParent).mockReset();
    vi.mocked(parentsApi.listStudentsForParent).mockReset().mockResolvedValue([]);
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
    vi.mocked(assignmentApi.findActiveAssignmentForStudent).mockReset().mockResolvedValue(null);
    vi.mocked(assignmentApi.getRouteWithStops).mockReset();
    vi.mocked(assignmentApi.listRoutesForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(assignmentApi.listVehiclesForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(assignmentApi.assignStudentToRoute).mockReset();
    vi.mocked(assignmentApi.endStudentAssignment).mockReset();
    vi.mocked(schoolErpApi.getStudentFinance).mockReset().mockResolvedValue(EMPTY_FINANCE);
    vi.mocked(parentsApi.getParentInvoiceDetail).mockReset();
    vi.mocked(parentsApi.recordParentPayment).mockReset();
    vi.mocked(parentsApi.setStudentBillingFee).mockReset().mockResolvedValue(undefined);
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

  it("opens the new student's detail drawer with transport assignment ready right after enrollment", async () => {
    // Registration flows straight into guardian linking and transport assignment without a
    // second navigation step. Billing follows from the guardian's Parent Invoice (ADR-0047), so
    // there is no invoice drawer here any more.
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([], 0));
    const enrolled: api.Student = {
      id: "01ARZ3NDEKTSV4RRFFQ69G5FDZ",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      fullName: "Yusuf Omar",
      externalRef: null,
      status: "active",
      createdAt: "2026-01-03T00:00:00Z",
      updatedAt: "2026-01-03T00:00:00Z",
      dateOfBirth: null,
      gender: null,
      notes: null,
    };
    vi.mocked(api.enrollStudent).mockResolvedValue(enrolled);
    vi.mocked(api.getStudent).mockResolvedValue(enrolled);

    renderPage();
    await waitFor(() => expect(screen.getByText("No students yet")).toBeInTheDocument());

    // Two "New Student" buttons render when the table is empty (header + empty-state CTA) —
    // either opens the identical `CreateStudentForm`, so the first is as good as either.
    await userEvent.click(screen.getAllByRole("button", { name: "New Student" })[0]);
    await screen.findByText("Green Valley School");
    await userEvent.selectOptions(screen.getByLabelText("Organization"), enrolled.organizationId);
    await userEvent.type(screen.getByPlaceholderText("e.g. Amina Hassan"), "Yusuf Omar");
    await userEvent.click(screen.getByRole("button", { name: "Enroll student" }));

    await waitFor(() => expect(api.enrollStudent).toHaveBeenCalled());

    // All three drawers this flow opens carry the student's name — the detail drawer's title is
    // the exact string "Yusuf Omar", while the other two embed it in a sentence, so the query
    // needs `exact: false` to count them all; an exact match against "Yusuf Omar" alone only
    // ever finds the first, even once the other two have genuinely opened (this is what the
    // original assertion here got wrong before the transport-assignment-only version of this
    // chain was fixed).
    await waitFor(() =>
      expect(screen.getAllByText("Yusuf Omar", { exact: false }).length).toBeGreaterThanOrEqual(3),
    );
    expect(screen.getByText("Link a parent to Yusuf Omar")).toBeInTheDocument();
    expect(screen.getByText("Assign Yusuf Omar to a route")).toBeInTheDocument();
    expect(screen.queryByText(/Issue the first invoice/)).not.toBeInTheDocument();
    expect(api.getStudent).toHaveBeenCalledWith(enrolled.id);
  });

  it("lets an org admin set the student's own monthly fee; a founder only sees it (ADR-0048)", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    useAuthStore.setState({
      principal: { userId: "u2", role: "org_admin", organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW", regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    renderPage();
    await userEvent.click(await screen.findByText("Amina Hassan"));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Monthly fee: not set")).toBeInTheDocument();
    expect(within(drawer).getByText("Not invoiced until a fee is set.")).toBeInTheDocument();

    await userEvent.click(within(drawer).getByRole("button", { name: "Set fee" }));
    await userEvent.type(await screen.findByLabelText("Monthly fee amount"), "20.00");
    await userEvent.click(screen.getByRole("button", { name: "Save fee" }));

    await waitFor(() =>
      expect(parentsApi.setStudentBillingFee).toHaveBeenCalledWith(STUDENT_SUMMARY.id, {
        monthlyFee: "20.00",
        currency: "USD",
      }),
    );
  });

  it("shows but does not offer to change the fee for a founder", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(schoolErpApi.getStudentFinance).mockResolvedValue({
      ...EMPTY_FINANCE,
      monthlyFee: "15.00",
      monthlyFeeCurrency: "USD",
    });
    renderPage();
    await userEvent.click(await screen.findByText("Amina Hassan"));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText(/Monthly fee:/)).toHaveTextContent("15.00");
    expect(within(drawer).queryByRole("button", { name: /fee/i })).not.toBeInTheDocument();
  });

  it("shows the student's own charges and payments and records a payment for that student only", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(schoolErpApi.getStudentFinance).mockResolvedValue({
      ...EMPTY_FINANCE,
      parents: [{ parentId: "p1", fullName: "Fatima Ali", isPrimary: true }],
      totalCharged: "40.00",
      totalPaid: "10.00",
      balanceDue: "30.00",
      charges: [
        {
          invoiceId: "inv-1",
          invoiceNumber: "2026-09-ABC123",
          lineId: "line-amina",
          period: "2026-09",
          parentId: "p1",
          parentName: "Fatima Ali",
          amount: "40.00",
          amountPaid: "10.00",
          balanceDue: "30.00",
          invoiceStatus: "partial",
          dueDate: "2026-09-10",
          vehicleId: null,
          currency: "USD",
        },
      ],
      payments: [
        {
          paymentId: "pay-1",
          invoiceId: "inv-1",
          invoiceNumber: "2026-09-ABC123",
          period: "2026-09",
          receivedOn: "2026-09-05",
          method: "cash",
          reference: "R-1",
          amount: "10.00",
          paymentTotal: "20.00",
          currency: "USD",
          isVoided: false,
          voidedReason: null,
        },
      ],
    });
    vi.mocked(parentsApi.getParentInvoiceDetail).mockResolvedValue({
      id: "inv-1",
      parentId: "p1",
      parentName: "Fatima Ali",
      period: "2026-09",
      invoiceNumber: "2026-09-ABC123",
      amount: "80.00",
      amountPaid: "20.00",
      balanceDue: "60.00",
      status: "partial",
      currency: "USD",
      invoiceDate: "2026-09-01",
      dueDate: "2026-09-10",
      notes: null,
      lines: [
        {
          lineId: "line-amina", studentId: STUDENT_SUMMARY.id, fullName: "Amina Hassan", amount: "40.00",
          amountPaid: "10.00", balanceDue: "30.00", vehicleId: null, routeId: null,
        },
        {
          lineId: "line-sibling", studentId: "sibling", fullName: "Sibling", amount: "40.00",
          amountPaid: "10.00", balanceDue: "30.00", vehicleId: null, routeId: null,
        },
      ],
    });
    vi.mocked(parentsApi.recordParentPayment).mockResolvedValue({
      id: "pay-2", parentId: "p1", invoiceId: "inv-1", invoiceNumber: "2026-09-ABC123", period: "2026-09",
      amount: "30.00", currency: "USD", method: "cash", reference: null, receivedOn: "2026-09-12", notes: null,
      isVoided: false, voidedReason: null, createdAt: "2026-09-12T00:00:00Z",
      allocations: [{ studentId: STUDENT_SUMMARY.id, fullName: "Amina Hassan", amount: "30.00", vehicleId: null }],
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Billed to Fatima Ali")).toBeInTheDocument();
    expect(within(dialog).getByText(/part of a \$20\.00 family payment/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Record payment" }));
    const amount = await screen.findByLabelText("Amount paid for Amina Hassan");
    expect(amount).toHaveValue("30.00");
    await userEvent.click(screen.getByRole("button", { name: "Save payment" }));
    const confirm = await screen.findByRole("dialog", { name: "Record this payment?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Record payment" }));

    await waitFor(() =>
      expect(parentsApi.recordParentPayment).toHaveBeenCalledWith(
        "inv-1",
        expect.objectContaining({
          amount: "30.00",
          allocations: [{ studentId: STUDENT_SUMMARY.id, amount: "30.00" }],
        }),
      ),
    );
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
    expect(within(dialog).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("lets a founder edit a student's profile from the detail drawer", async () => {
    vi.mocked(api.listStudents).mockResolvedValue(pageOf([STUDENT_SUMMARY], 1));
    vi.mocked(api.updateStudent).mockResolvedValue({ ...STUDENT_DETAIL, notes: "Allergic to peanuts." });

    renderPage();
    await waitFor(() => expect(screen.getByText("Amina Hassan")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Amina Hassan"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Edit" }));

    const editDialog = await screen.findByText("Edit student");
    expect(editDialog).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Optional"), "Allergic to peanuts.");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(api.updateStudent).toHaveBeenCalledWith(
        STUDENT_SUMMARY.id,
        expect.objectContaining({ notes: "Allergic to peanuts." }),
      ),
    );
  });
});
