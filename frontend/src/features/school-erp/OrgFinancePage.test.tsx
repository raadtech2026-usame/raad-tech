import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../shared/api/types";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getFinanceSummary: vi.fn(),
  listVehicleFinance: vi.fn(),
  getProfitAndLoss: vi.fn(),
  listStudentInvoices: vi.fn(),
  listStudentPayments: vi.fn(),
  listIncome: vi.fn(),
  listExpenses: vi.fn(),
  listFeePlans: vi.fn(),
  listCategories: vi.fn(),
  listStudentsForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  recordStudentPayment: vi.fn(),
}));

import {
  getFinanceSummary,
  getProfitAndLoss,
  listCategories,
  listExpenses,
  listFeePlans,
  listIncome,
  listStudentInvoices,
  listStudentPayments,
  listStudentsForPicker,
  listVehicleFinance,
  listVehiclesForPicker,
  recordStudentPayment,
  type StudentInvoice,
} from "./api";
import { OrgFinancePage } from "./OrgFinancePage";

function emptyPage<T>(): OffsetPage<T> {
  return { data: [], page: { total: 0, page: 1, pageSize: 25 } };
}

const INVOICE: StudentInvoice = {
  id: "inv-1",
  organizationId: "org-1",
  studentId: "student-1",
  feePlanId: null,
  period: "2026-09",
  amount: "100.00",
  discountAmount: "10.00",
  netAmount: "90.00",
  amountPaid: "40.00",
  balanceDue: "50.00",
  currency: "USD",
  dueDate: "2026-09-30",
  status: "partially_paid",
  routeId: "route-1",
  vehicleId: "bus-1",
  driverId: null,
  notes: null,
  issuedAt: "2026-09-01T00:00:00Z",
  paidAt: null,
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OrgFinancePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The Organization school-finance surface (ADR-0038, ADR-0040 §2).
 *
 * These tests pin three properties. Two were here from the start: every figure comes from a real
 * read (nothing is fabricated or derived client-side), and the ADR-0038 §2 boundary between
 * school finance and RAAD platform billing stays visible rather than being quietly merged.
 *
 * The third is the automatic-accounting rule: recording a family's payment is the *only* action
 * that produces student revenue, and the Income ledger must actively steer an operator away from
 * entering that same money by hand — which is how a school ends up counting it twice.
 */
describe("OrgFinancePage", () => {
  beforeEach(() => {
    vi.mocked(getFinanceSummary).mockResolvedValue({
      billedAmount: "1200.00",
      collectedAmount: "800.00",
      outstandingAmount: "400.00",
      invoiceCount: 12,
      paidInvoiceCount: 8,
      overdueInvoiceCount: 2,
      currency: "USD",
    });
    vi.mocked(listVehicleFinance).mockResolvedValue([
      {
        vehicleId: "bus-1",
        studentCount: 30,
        invoiceCount: 30,
        billedAmount: "900.00",
        collectedAmount: "600.00",
        outstandingAmount: "300.00",
        paidStudentCount: 20,
        unpaidStudentCount: 10,
        expenseAmount: "150.00",
        netAmount: "450.00",
        currency: "USD",
      },
    ]);
    vi.mocked(getProfitAndLoss).mockResolvedValue({
      start: "2025-09-05",
      end: "2026-09-05",
      studentRevenue: "800.00",
      otherIncome: "50.00",
      totalIncome: "850.00",
      totalExpenses: "300.00",
      netProfit: "550.00",
      incomeByCategory: {},
      expensesByCategory: {},
      currency: "USD",
    });
    vi.mocked(listStudentInvoices).mockResolvedValue({
      data: [INVOICE],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    vi.mocked(listStudentPayments).mockResolvedValue(emptyPage());
    vi.mocked(listIncome).mockResolvedValue(emptyPage());
    vi.mocked(listExpenses).mockResolvedValue(emptyPage());
    vi.mocked(listFeePlans).mockResolvedValue(emptyPage());
    vi.mocked(listCategories).mockResolvedValue(emptyPage());
    vi.mocked(listStudentsForPicker).mockResolvedValue([
      { id: "student-1", label: "Amina Hassan" },
    ]);
    vi.mocked(listVehiclesForPicker).mockResolvedValue([
      { id: "bus-1", label: "BUS-042 · Route A" },
    ]);
    vi.mocked(recordStudentPayment).mockResolvedValue({
      id: "pay-1",
      organizationId: "org-1",
      invoiceId: "inv-1",
      studentId: "student-1",
      amount: "50.00",
      currency: "USD",
      method: "cash",
      reference: null,
      receivedOn: "2026-09-08",
      notes: null,
      isVoided: false,
      voidedReason: null,
    });
  });

  it("renders the KPI row from the finance summary endpoint", async () => {
    renderPage();

    expect(await screen.findByText("$1,200.00")).toBeInTheDocument();
    // Collected also appears as the P&L's student-revenue line, so both are legitimate.
    expect(screen.getAllByText("$800.00").length).toBeGreaterThan(0);
    expect(screen.getByText("$400.00")).toBeInTheDocument();
    expect(screen.getByText("12 invoices")).toBeInTheDocument();
    expect(screen.getByText("2 overdue")).toBeInTheDocument();
  });

  it("shows revenue, collections, outstanding and attributed cost per bus", async () => {
    renderPage();

    // Students on the bus, and the paid/unpaid split — the core of the requirement.
    expect(await screen.findByText("30")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("$900.00")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
  });

  it("names the bus and the student rather than showing raw ids", async () => {
    renderPage();

    // `vehicle_id`/`student_id` are all an invoice carries (ADR-0040 §3); the label is resolved
    // from a cached lookup so the operator reads a plate, not a ULID.
    expect(await screen.findByText("Amina Hassan")).toBeInTheDocument();
    expect(screen.getAllByText("BUS-042 · Route A").length).toBeGreaterThan(0);
    expect(screen.queryByText("student-1")).not.toBeInTheDocument();
  });

  it("falls back to the raw id when a lookup cannot resolve a name", async () => {
    vi.mocked(listStudentsForPicker).mockResolvedValue([]);
    renderPage();

    // A student removed since being billed still shows something traceable, never a blank.
    expect(await screen.findByText("student-1")).toBeInTheDocument();
  });

  it("renders a partially-paid invoice with its real balance, not a recomputed one", async () => {
    renderPage();

    expect(await screen.findByText("Partially paid")).toBeInTheDocument();
    // 90.00 net (100 less a 10 discount), 40.00 paid, 50.00 still owed — all server-computed.
    expect(screen.getByText("$90.00")).toBeInTheDocument();
    expect(screen.getByText("$40.00")).toBeInTheDocument();
    expect(screen.getAllByText("$50.00").length).toBeGreaterThan(0);
  });

  it("only fetches a ledger tab's data once that tab is selected", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Partially paid");

    // Payments are not fetched while the Invoices tab is active — six ledger endpoints firing
    // on every page load is exactly the waste `enabled` exists to prevent.
    expect(listStudentPayments).not.toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "Payments" }));
    await waitFor(() => expect(listStudentPayments).toHaveBeenCalled());
  });

  it("shows the profit & loss lines separately, so student fees stay distinguishable", async () => {
    renderPage();

    expect(await screen.findByText(/Student fee revenue \(collected\)/)).toBeInTheDocument();
    expect(screen.getByText(/^Other income$/)).toBeInTheDocument();
    // "Net profit" is both a KPI card label and the P&L bottom line — both are intended.
    expect(screen.getAllByText("Net profit").length).toBe(2);
    expect(screen.getAllByText("$550.00").length).toBeGreaterThan(0);
  });

  it("keeps RAAD platform billing a separate domain, linked rather than merged", async () => {
    renderPage();

    expect(await screen.findByText("Platform subscription")).toBeInTheDocument();
    expect(
      screen.getByText(/never combined into\s+a single balance/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open billing/i })).toHaveAttribute(
      "href",
      "/org/billing",
    );
  });

  it("surfaces a failed load rather than rendering a zero", async () => {
    vi.mocked(listVehicleFinance).mockRejectedValue(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Could not load vehicle finance")).toBeInTheDocument();
  });

  // ---- The workflow -----------------------------------------------------------------------

  it("offers Record payment on an unsettled invoice and posts the remaining balance", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Partially paid");

    await user.click(screen.getByRole("button", { name: /record payment/i }));

    const drawer = await screen.findByRole("dialog");
    // Pre-filled with what is still owed, not the invoice total — a part payment already
    // happened and re-charging the full amount would be wrong.
    expect(within(drawer).getByDisplayValue("50.00")).toBeInTheDocument();

    await user.click(within(drawer).getByRole("button", { name: /^record payment$/i }));

    await waitFor(() =>
      expect(recordStudentPayment).toHaveBeenCalledWith(
        "inv-1",
        expect.objectContaining({ amount: "50.00", currency: "USD", method: "cash" }),
      ),
    );
  });

  it("does not offer Record payment on a settled invoice", async () => {
    vi.mocked(listStudentInvoices).mockResolvedValue({
      data: [{ ...INVOICE, status: "paid", amountPaid: "90.00", balanceDue: "0.00" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    renderPage();

    // "Paid" is both this invoice's status badge and a column header, so scope to the badge.
    expect(await screen.findByText("$0.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /record payment/i })).not.toBeInTheDocument();
  });

  it("tells the operator on the Income tab that student revenue is already counted", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Partially paid");

    await user.click(screen.getByRole("tab", { name: "Income" }));

    // The rule made visible where it can actually prevent a double entry: the amount already
    // counted from payments is named, and the ledger's real purpose is spelled out.
    expect(
      await screen.findByText(/Student fee revenue is recorded automatically/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/must never be added here/i)).toBeInTheDocument();
    // The empty-state copy names the same three sources, so scope to the notice itself.
    expect(
      screen.getByText(/must never be added here/i).textContent,
    ).toMatch(/donations,\s+sponsorships, grants/i);
  });

  it("exposes the fee-plan and billing-run steps that start the workflow", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Partially paid");

    expect(screen.getByRole("button", { name: /generate invoices/i })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Fee plans" }));
    expect(await screen.findByRole("button", { name: /new fee plan/i })).toBeInTheDocument();
    expect(screen.getByText("No fee plans yet")).toBeInTheDocument();
  });
});
