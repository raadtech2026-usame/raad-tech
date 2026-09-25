import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../shared/api/types";
import { useCurrentPageHeader } from "../../app/layout/PageHeaderContext";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getFinanceSummary: vi.fn(),
  getProfitAndLoss: vi.fn(),
  listIncome: vi.fn(),
  listExpenses: vi.fn(),
  listCategories: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  voidIncome: vi.fn(),
  voidExpense: vi.fn(),
  updateCategory: vi.fn(),
}));

// ADR-0042 — the real Parent Invoice aggregate this page's own invoices tab now uses, owned by
// `transport_ops/parents` (the same cross-bounded-context reuse this page's own imports already
// establish for `ParentFinancialSummary`). `listParentsForPicker`/`getParent`/
// `listStudentsForParent` back the new Parent filter's own `ParentSearchSelect`.
vi.mock("../transport-ops/parents/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../transport-ops/parents/api")>()),
  listParentInvoices: vi.fn(),
  getParentInvoiceDetail: vi.fn(),
  setParentInvoicePaymentStatus: vi.fn(),
  generateParentInvoices: vi.fn(),
  listParentsForPicker: vi.fn(),
  getParent: vi.fn(),
  listStudentsForParent: vi.fn(),
}));

import {
  getFinanceSummary,
  getProfitAndLoss,
  listCategories,
  listExpenses,
  listIncome,
  listVehiclesForPicker,
  updateCategory,
  voidExpense,
  voidIncome,
  type FinancialCategory,
  type LedgerEntry,
} from "./api";
import {
  generateParentInvoices,
  getParent,
  getParentInvoiceDetail,
  listParentInvoices,
  listParentsForPicker,
  listStudentsForParent,
  setParentInvoicePaymentStatus,
  type ParentInvoiceDetail,
  type ParentInvoiceSummary,
} from "../transport-ops/parents/api";
import { OrgFinancePage } from "./OrgFinancePage";

function emptyPage<T>(): OffsetPage<T> {
  return { data: [], page: { total: 0, page: 1, pageSize: 25 } };
}

const PARENT_INVOICE: ParentInvoiceSummary = {
  id: "invoice-1",
  parentId: "parent-1",
  parentName: "Fatima Ali",
  period: "2026-09",
  invoiceNumber: "2026-09-PARENT1",
  childrenCount: 2,
  amount: "90.00",
  amountPaid: "40.00",
  balanceDue: "50.00",
  status: "partial",
  invoiceDate: "2026-09-01",
  dueDate: "2026-09-30",
  currency: "USD",
};

const PARENT_INVOICE_DETAIL: ParentInvoiceDetail = {
  id: "invoice-1",
  parentId: "parent-1",
  parentName: "Fatima Ali",
  period: "2026-09",
  invoiceNumber: "2026-09-PARENT1",
  amount: "90.00",
  amountPaid: "40.00",
  balanceDue: "50.00",
  status: "partial",
  currency: "USD",
  invoiceDate: "2026-09-01",
  dueDate: "2026-09-30",
  notes: null,
  lines: [
    {
      studentId: "student-1",
      fullName: "Amina Hassan",
      amount: "45.00",
      vehicleId: "bus-1",
      routeId: "route-1",
    },
  ],
};

/** Renders `OrgFinancePage` alongside a small probe that surfaces `usePageHeader`'s own state as
 * plain text — `AppShell`'s `TopBar` is the store's only other consumer, and mounting the whole
 * shell just to read a subtitle would be disproportionate to what's being checked. */
function HeaderSubtitleProbe() {
  const { subtitle } = useCurrentPageHeader();
  return <span data-testid="header-subtitle">{subtitle}</span>;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HeaderSubtitleProbe />
        <OrgFinancePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The Organization school-finance surface (ADR-0038, ADR-0040 §2, Finance UI cleanup 2026-09-12).
 *
 * These tests pin three properties. Two were here from the start: every figure comes from a real
 * read (nothing is fabricated or derived client-side), and the ADR-0038 §2 boundary between
 * school finance and RAAD platform billing stays visible rather than being quietly merged.
 *
 * The third is the automatic-accounting rule: recording a family's payment is the *only* action
 * that produces student revenue, and the Income ledger must actively steer an operator away from
 * entering that same money by hand — which is how a school ends up counting it twice.
 *
 * The Finance UI cleanup (2026-09-12) added a fourth: the page is Parent-based end to end — no
 * Vehicle Financial Overview, no Payments/Fee plans tabs, full monetary values, and a Parent
 * Invoices filter bar (Parent/Status/Vehicle/date-range) that never asks for a raw id.
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
    vi.mocked(listParentInvoices).mockResolvedValue({
      data: [PARENT_INVOICE],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    vi.mocked(getParentInvoiceDetail).mockResolvedValue(PARENT_INVOICE_DETAIL);
    vi.mocked(listIncome).mockResolvedValue(emptyPage());
    vi.mocked(listExpenses).mockResolvedValue(emptyPage());
    vi.mocked(listCategories).mockResolvedValue(emptyPage());
    vi.mocked(listVehiclesForPicker).mockResolvedValue([
      { id: "bus-1", label: "BUS-042 · Route A" },
    ]);
    vi.mocked(listParentsForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(getParent).mockReset();
    vi.mocked(listStudentsForParent).mockReset();
    vi.mocked(setParentInvoicePaymentStatus).mockResolvedValue({
      ...PARENT_INVOICE,
      status: "paid",
      amountPaid: "90.00",
      balanceDue: "0.00",
    });
    vi.mocked(generateParentInvoices).mockResolvedValue([]);
  });

  it("renders the KPI row from the finance summary endpoint, with full (never truncated) amounts", async () => {
    renderPage();

    expect(await screen.findByText("$1,200.00")).toBeInTheDocument();
    // Collected also appears as the P&L's student-revenue line, so both are legitimate.
    expect(screen.getAllByText("$800.00").length).toBeGreaterThan(0);
    expect(screen.getByText("$400.00")).toBeInTheDocument();
    expect(screen.getByText("12 invoices")).toBeInTheDocument();
    // "8 settled" (Student-billing-flavoured) is gone — Parent-oriented wording instead.
    expect(screen.getByText("8 paid")).toBeInTheDocument();
    expect(screen.queryByText(/settled/i)).not.toBeInTheDocument();
  });

  it("computes the Net Result KPI over the same period as the rest of the Overview row, not a silently-mixed trailing-12-month figure", async () => {
    renderPage();

    await screen.findByText("$1,200.00");
    expect(getProfitAndLoss).toHaveBeenCalled();
    // Net Result no longer carries a "12 months" pill next to Overview siblings scoped to one
    // calendar period — it reads as this same period's own figure.
    expect(screen.queryByText("12 months")).not.toBeInTheDocument();
    expect(screen.getByText(/this period's collected parent revenue/i)).toBeInTheDocument();
  });

  it("has no Vehicle Financial Overview / Revenue per bus section anywhere on the page", async () => {
    renderPage();
    await screen.findByText("$1,200.00");

    expect(screen.queryByText("Vehicle financial overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Revenue per bus")).not.toBeInTheDocument();
  });

  it("no longer describes itself as student billing in the page subtitle", async () => {
    renderPage();

    expect(await screen.findByTestId("header-subtitle")).toHaveTextContent(
      "School income, parent billing and expenses",
    );
    expect(screen.queryByText(/student billing/i)).not.toBeInTheDocument();
  });

  it("shows only Parent invoices / Income / Expenses / Categories tabs — Payments and Fee plans are gone", async () => {
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    expect(screen.getByRole("tab", { name: "Parent invoices" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Income" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Expenses" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Categories" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Payments" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Fee plans" })).not.toBeInTheDocument();
  });

  it("names the parent and shows the children count, grouped by (parent, period) (ADR-0041 §1)", async () => {
    renderPage();

    expect(await screen.findByText("Fatima Ali")).toBeInTheDocument();
    expect(screen.getByText("2026-09-PARENT1")).toBeInTheDocument();
    // childrenCount, not a raw list of student ids — the row is family-level.
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("uses Receivable rather than Balance/Outstanding as the table's column header", async () => {
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    expect(screen.getByRole("columnheader", { name: "Receivable" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Balance" })).not.toBeInTheDocument();
  });

  it("renders every required Parent Invoice table column and action (table layout fix, 2026-09-12)", async () => {
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    for (const name of [
      "Invoice",
      "Parent",
      "Children",
      "Period",
      "Amount",
      "Paid",
      "Receivable",
      "Status",
    ]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "View" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /payment status/i })).toBeInTheDocument();
  });

  it("renders a long Parent name in full — never truncated with an ellipsis (table layout fix, 2026-09-12)", async () => {
    const longName = "Abdirahman Mohamed Warsame Hassan Ali Yusuf";
    vi.mocked(listParentInvoices).mockResolvedValue({
      data: [{ ...PARENT_INVOICE, parentName: longName }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    renderPage();

    expect(await screen.findByText(longName)).toBeInTheDocument();
  });

  it("keeps financial amounts fully visible in the table — the Finance Overview truncation fix must not regress here", async () => {
    vi.mocked(listParentInvoices).mockResolvedValue({
      data: [{ ...PARENT_INVOICE, amount: "12500.00", amountPaid: "5000.00", balanceDue: "7500.00" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    renderPage();

    expect(await screen.findByText("USD 12500.00")).toBeInTheDocument();
    expect(screen.getByText("USD 5000.00")).toBeInTheDocument();
    expect(screen.getByText("USD 7500.00")).toBeInTheDocument();
  });

  it("shows a filtered empty state (not the zero-billing state) when a filter narrows the list to nothing", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    vi.mocked(listParentInvoices).mockResolvedValue(emptyPage());
    await user.selectOptions(screen.getByLabelText("Filter parent invoices by vehicle"), "bus-1");

    expect(await screen.findByText("No parent invoices found")).toBeInTheDocument();
    expect(screen.queryByText("No parent invoices yet")).not.toBeInTheDocument();
  });

  it("shows the zero-billing empty state when no filters are active and there truly are no invoices", async () => {
    vi.mocked(listParentInvoices).mockResolvedValue(emptyPage());
    renderPage();

    expect(await screen.findByText("No parent invoices yet")).toBeInTheDocument();
    expect(screen.queryByText("No parent invoices found")).not.toBeInTheDocument();
  });

  it("renders a partially-paid parent invoice with its real balance, not a recomputed one", async () => {
    renderPage();

    const row = (await screen.findByText("2026-09-PARENT1")).closest("tr")!;
    expect(within(row).getByText("Partial")).toBeInTheDocument();
    // 90.00 billed, 40.00 paid, 50.00 still owed — all server-computed on the real ParentInvoice.
    expect(within(row).getByText("USD 90.00")).toBeInTheDocument();
    expect(within(row).getByText("USD 40.00")).toBeInTheDocument();
    expect(within(row).getByText("USD 50.00")).toBeInTheDocument();
  });

  it("opens the Parent Invoice detail drawer and shows the child line items behind it", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fatima Ali");

    await user.click(screen.getByRole("button", { name: "View" }));

    const dialog = await screen.findByRole("dialog");
    // The per-child breakdown ADR-0042 says a real Parent Invoice must never lose.
    expect(await within(dialog).findByText("Amina Hassan")).toBeInTheDocument();
    expect(getParentInvoiceDetail).toHaveBeenCalledWith("invoice-1");
  });

  it("only fetches a ledger tab's data once that tab is selected", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    // Income is not fetched while the Invoices tab is active — every ledger endpoint firing on
    // every page load is exactly the waste `enabled` exists to prevent.
    expect(listIncome).not.toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "Income" }));
    await waitFor(() => expect(listIncome).toHaveBeenCalled());
  });

  // ---- Parent Invoices filter bar (Finance UI cleanup, 2026-09-12) ------------------------

  describe("Parent Invoices filter bar", () => {
    it("filters by Payment Status without touching the underlying status logic", async () => {
      const user = userEvent.setup();
      renderPage();
      await screen.findByText("2026-09-PARENT1");
      vi.mocked(listParentInvoices).mockClear();

      await user.selectOptions(
        screen.getByLabelText("Filter parent invoices by payment status"),
        "paid",
      );

      await waitFor(() =>
        expect(listParentInvoices).toHaveBeenCalledWith(
          expect.objectContaining({ status: "paid" }),
        ),
      );
    });

    it("filters by a human-readable Vehicle option, never a raw vehicle id in the UI", async () => {
      const user = userEvent.setup();
      renderPage();
      await screen.findByText("2026-09-PARENT1");

      const vehicleSelect = screen.getByLabelText("Filter parent invoices by vehicle") as HTMLSelectElement;
      expect(within(vehicleSelect).getByText("All Vehicles")).toBeInTheDocument();
      expect(within(vehicleSelect).getByText("BUS-042 · Route A")).toBeInTheDocument();
      expect(within(vehicleSelect).queryByText("bus-1")).not.toBeInTheDocument();

      vi.mocked(listParentInvoices).mockClear();
      await user.selectOptions(vehicleSelect, "bus-1");

      await waitFor(() =>
        expect(listParentInvoices).toHaveBeenCalledWith(
          expect.objectContaining({ vehicleId: "bus-1" }),
        ),
      );
    });

    it("defaults to All Vehicles — no vehicle restriction sent (null, not an empty string)", async () => {
      renderPage();
      await screen.findByText("2026-09-PARENT1");

      // The very first request, before any filter is touched, must carry no vehicle
      // restriction at all — `""` (the "All Vehicles" option's own value) is sent as `null`,
      // never as an empty-string id the backend would try to match against a real vehicle.
      await waitFor(() =>
        expect(listParentInvoices).toHaveBeenCalledWith(
          expect.objectContaining({ vehicleId: null }),
        ),
      );
    });

    it("filters by a From/To date range using real date inputs, not a YYYY-MM period field", async () => {
      renderPage();
      await screen.findByText("2026-09-PARENT1");

      const from = screen.getByLabelText("Filter parent invoices from this date");
      const to = screen.getByLabelText("Filter parent invoices to this date");
      expect(from).toHaveAttribute("type", "date");
      expect(to).toHaveAttribute("type", "date");
      expect(screen.queryByPlaceholderText("2026-09")).not.toBeInTheDocument();

      vi.mocked(listParentInvoices).mockClear();
      await userEvent.type(from, "2026-09-01");
      await userEvent.type(to, "2026-09-30");

      await waitFor(() =>
        expect(listParentInvoices).toHaveBeenCalledWith(
          expect.objectContaining({ dateFrom: "2026-09-01", dateTo: "2026-09-30" }),
        ),
      );
    });

    it("searches and filters by Parent name — never asking for a Parent ID/UUID", async () => {
      const user = userEvent.setup();
      vi.mocked(listParentsForPicker).mockResolvedValue([
        { id: "parent-1", fullName: "Fatima Ali", status: "active" },
      ]);
      vi.mocked(getParent).mockResolvedValue({
        id: "parent-1",
        organizationId: "org-1",
        userId: "user-1",
        fullName: "Fatima Ali",
        phone: "+252611111111",
        status: "active",
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
        alternatePhone: null,
        address: null,
        emergencyContactName: null,
        emergencyContactPhone: null,
        notes: null,
      });
      vi.mocked(listStudentsForParent).mockResolvedValue([]);
      renderPage();
      await screen.findByText("2026-09-PARENT1");
      vi.mocked(listParentInvoices).mockClear();

      const search = screen.getByLabelText("Filter parent invoices by parent");
      expect(screen.queryByText(/parent id/i)).not.toBeInTheDocument();
      await user.click(search);
      await user.type(search, "Fatima");
      await user.click(await screen.findByRole("option", { name: "Fatima Ali" }));

      await waitFor(() =>
        expect(listParentInvoices).toHaveBeenCalledWith(
          expect.objectContaining({ parentId: "parent-1" }),
        ),
      );
    });
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

  // ---- The workflow -----------------------------------------------------------------------

  it("offers Payment status on an unsettled Parent Invoice, confirms, and PATCHes the new status (ADR-0042 Part 9)", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fatima Ali");

    await user.click(screen.getByRole("button", { name: /payment status/i }));

    const drawer = await screen.findByRole("dialog");
    // The invoice was already `partial` — selecting Paid changes the status, which triggers the
    // directive's own required confirmation step before saving.
    await user.click(within(drawer).getByRole("radio", { name: "Paid" }));
    await user.click(within(drawer).getByRole("button", { name: "Save" }));

    const confirmDialog = await screen.findByText(/confirm payment status/i);
    await user.click(within(confirmDialog.closest('[role="dialog"]') ?? document.body).getByRole("button", {
      name: /confirm & save/i,
    }));

    await waitFor(() =>
      expect(setParentInvoicePaymentStatus).toHaveBeenCalledWith(
        "invoice-1",
        expect.objectContaining({ status: "paid" }),
      ),
    );
  });

  it("does not offer Payment status on a cancelled Parent Invoice", async () => {
    vi.mocked(listParentInvoices).mockResolvedValue({
      data: [{ ...PARENT_INVOICE, status: "cancelled", amountPaid: "0.00", balanceDue: "90.00" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    renderPage();

    await screen.findByText("Fatima Ali");
    expect(screen.queryByRole("button", { name: /payment status/i })).not.toBeInTheDocument();
  });

  it("tells the operator on the Income tab that student revenue is already counted", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("2026-09-PARENT1");

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

  // ---- Void / edit actions (pre-deployment audit §C) --------------------------------------

  const EXPENSE_ENTRY: LedgerEntry = {
    id: "exp-1",
    organizationId: "org-1",
    categoryId: null,
    amount: "75.00",
    currency: "USD",
    occurredOn: "2026-09-01",
    description: "Fuel",
    reference: null,
    vehicleId: "bus-1",
    isVoided: false,
    voidedReason: null,
  };

  it("voids an expense entry after confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue({
      data: [EXPENSE_ENTRY],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    vi.mocked(voidExpense).mockResolvedValue({ ...EXPENSE_ENTRY, isVoided: true });
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    await user.click(screen.getByRole("tab", { name: "Expenses" }));
    await screen.findByText("Fuel");
    await user.click(screen.getByRole("button", { name: "Void" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/expense entry/i);
    const confirm = within(dialog).getByRole("button", { name: /void entry/i });
    // A void removes money from Profit & Loss, so it cannot be confirmed without saying why.
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/reason/i), "  Fuel receipt entered twice ");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(voidExpense).toHaveBeenCalledWith("exp-1", "Fuel receipt entered twice"),
    );
  });

  it("shows the recorded reason under a voided entry", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue({
      data: [{ ...EXPENSE_ENTRY, isVoided: true, voidedReason: "Fuel receipt entered twice" }],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    await user.click(screen.getByRole("tab", { name: "Expenses" }));
    expect(await screen.findByText("Fuel receipt entered twice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Void" })).not.toBeInTheDocument();
  });

  it("voids an income entry after confirmation", async () => {
    const user = userEvent.setup();
    const incomeEntry: LedgerEntry = { ...EXPENSE_ENTRY, id: "inc-1", description: "Donation" };
    vi.mocked(listIncome).mockResolvedValue({
      data: [incomeEntry],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    vi.mocked(voidIncome).mockResolvedValue({ ...incomeEntry, isVoided: true });
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    await user.click(screen.getByRole("tab", { name: "Income" }));
    await screen.findByText("Donation");
    await user.click(screen.getByRole("button", { name: "Void" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/income entry/i);
    await user.type(within(dialog).getByLabelText(/reason/i), "Donation was returned");
    await user.click(within(dialog).getByRole("button", { name: /void entry/i }));

    await waitFor(() =>
      expect(voidIncome).toHaveBeenCalledWith("inc-1", "Donation was returned"),
    );
  });

  const CATEGORY: FinancialCategory = {
    id: "cat-1",
    organizationId: "org-1",
    name: "Fuel",
    kind: "expense",
    parentCategoryId: null,
    description: null,
    status: "active",
  };

  it("edits an existing category's name without exposing its fixed kind as editable", async () => {
    const user = userEvent.setup();
    vi.mocked(listCategories).mockResolvedValue({
      data: [CATEGORY],
      page: { total: 1, page: 1, pageSize: 25 },
    });
    vi.mocked(updateCategory).mockResolvedValue({ ...CATEGORY, name: "Fuel & Maintenance" });
    renderPage();
    await screen.findByText("2026-09-PARENT1");

    await user.click(screen.getByRole("tab", { name: "Categories" }));
    await screen.findByText("Fuel");
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByDisplayValue("Fuel")).toBeInTheDocument();
    // Kind is fixed once created — the update endpoint doesn't accept it, so edit mode must not
    // offer a control that would silently be ignored.
    expect(within(drawer).queryByText("Side of the ledger")).not.toBeInTheDocument();

    await user.click(within(drawer).getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(updateCategory).toHaveBeenCalledWith(
        "cat-1",
        expect.objectContaining({ name: "Fuel" }),
      ),
    );
  });
});
