import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetListParams } from "../../shared/api/listParams";
import type { OffsetPage } from "../../shared/api/types";
import type { PlatformStats } from "../platform-analytics/api";
import type { Invoice, Payment } from "./api";

vi.mock("../platform-analytics/api", () => ({ getPlatformStats: vi.fn() }));
vi.mock("../platform-finance/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../platform-finance/api")>()),
  getPlatformPnl: vi.fn(),
  listPlatformExpenses: vi.fn(),
  listPlatformIncome: vi.fn(),
  listPlatformCategories: vi.fn(),
  createPlatformCategory: vi.fn(),
  voidPlatformExpense: vi.fn(),
  voidPlatformIncome: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listInvoices: vi.fn(),
  listPayments: vi.fn(),
}));

import { getPlatformStats } from "../platform-analytics/api";
import {
  createPlatformCategory,
  getPlatformPnl,
  listPlatformCategories,
  listPlatformExpenses,
  listPlatformIncome,
  voidPlatformExpense,
  voidPlatformIncome,
  type PlatformExpense,
  type PlatformIncome,
} from "../platform-finance/api";
import { listInvoices, listPayments } from "./api";
import { PlatformFinancePage } from "./PlatformFinancePage";

const STATS: PlatformStats = {
  organizations: { total: 3, byStatus: { active: 2 }, createdToday: 1 },
  vehicles: { total: 8 },
  devices: { total: 5, online: 4, offline: 1 },
  users: { total: 20, byStatus: { active: 18 }, monthlyActive: 12, createdToday: 2 },
  billing: {
    subscriptionByStatus: { active: 6, trial: 1, past_due: 1 },
    expiringSoon: 2,
    revenue: 4500,
    activeByBillingCycle: { monthly: 5, annual: 2 },
  },
  paymentDueOrganizations: 3,
  systemHealth: { database: "ok", broker: "ok" },
};

function invoice(id: string, amount: number, currency = "USD"): Invoice {
  return {
    id,
    organizationId: "org1",
    subscriptionId: "s1",
    number: `INV-${id}`,
    amount,
    currency,
    periodStart: "2026-08-01",
    periodEnd: "2026-08-31",
    status: "issued",
    issuedAt: "2026-08-01T00:00:00Z",
    dueAt: "2026-08-15T00:00:00Z",
    paidAt: null,
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
  };
}

function payment(id: string, amount: number): Payment {
  return {
    id,
    organizationId: "org1",
    invoiceId: "i1",
    provider: "stripe",
    providerRef: "pi_1",
    amount,
    currency: "USD",
    status: "paid",
    failureReason: null,
    createdAt: "2026-08-02T00:00:00Z",
    confirmedAt: "2026-08-02T00:00:00Z",
  };
}

function pageOf<T>(rows: T[], total = rows.length): OffsetPage<T> {
  return { data: rows, page: { total, page: 1, pageSize: rows.length || 1 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PlatformFinancePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The finance page composes existing billing reads into an ERP-style overview. Its whole
 * correctness claim is that it never presents a figure it did not actually receive, so these
 * tests target exactly that: real values from real payloads, exact counts, and an explicit
 * disclosure whenever a total covers a sample rather than the whole set.
 */
describe("PlatformFinancePage", () => {
  beforeEach(() => {
    vi.mocked(getPlatformStats).mockResolvedValue(STATS);
    vi.mocked(listPayments).mockResolvedValue(pageOf([payment("p1", 375)]));
    vi.mocked(listInvoices).mockImplementation(async (params: OffsetListParams) => {
      if (params.filters.status === "issued") {
        return pageOf([invoice("a", 100), invoice("b", 150)]);
      }
      if (params.filters.status === "paid") {
        return pageOf([invoice("c", 400)]);
      }
      return pageOf<Invoice>([]);
    });
    vi.mocked(getPlatformPnl).mockResolvedValue({
      start: "2026-09-01",
      end: "2026-09-08",
      subscriptionRevenue: "4500.00",
      subscriptionInvoiced: "5000.00",
      subscriptionReceivables: "500.00",
      otherIncome: "0.00",
      totalRevenue: "4500.00",
      totalExpenses: "1200.00",
      netProfit: "3300.00",
      expensesByKind: {},
      incomeByKind: {},
      currency: "USD",
    });
    vi.mocked(listPlatformExpenses).mockResolvedValue(
      pageOf<never>([]) as never,
    );
    vi.mocked(listPlatformIncome).mockResolvedValue(pageOf<never>([]) as never);
    vi.mocked(listPlatformCategories).mockResolvedValue([]);
  });

  it("shows Invoiced/Collected/Receivables/Revenue/Expenses/Net profit as real financial amounts", async () => {
    renderPage();
    expect(await screen.findByText("Invoiced")).toBeInTheDocument();
    expect(await screen.findByText("$5,000.00")).toBeInTheDocument(); // subscriptionInvoiced — unique to this card
    expect(screen.getByText("Collected")).toBeInTheDocument();
    // "Receivables" also titles the invoice-list PageSection further down the page.
    expect(screen.getAllByText("Receivables").length).toBeGreaterThan(0);
    expect(screen.getByText("$500.00")).toBeInTheDocument(); // subscriptionReceivables — unique to this card
    expect(screen.getByText("Expenses")).toBeInTheDocument();
    // "Net profit" and the three amounts below also appear in the lower Platform P&L detail
    // card, so these assert presence rather than a single unique match.
    expect(screen.getAllByText("Net profit").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$4,500.00").length).toBeGreaterThan(0); // subscriptionRevenue / totalRevenue
    expect(screen.getAllByText("$1,200.00").length).toBeGreaterThan(0); // totalExpenses
    expect(screen.getAllByText("$3,300.00").length).toBeGreaterThan(0); // netProfit
  });

  it("lets the Founder change the financial overview's period", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("$5,000.00");
    // This mock is shared (and not cleared) across every test in this file, so the call count
    // going in is not necessarily zero — assert the increment the interaction causes, not an
    // absolute total.
    const callsBefore = vi.mocked(getPlatformPnl).mock.calls.length;

    await user.selectOptions(screen.getByLabelText("Date range"), "this_year");

    await waitFor(() =>
      expect(vi.mocked(getPlatformPnl).mock.calls.length).toBe(callsBefore + 1),
    );
  });

  it("renders platform-wide subscription metrics from real backend counts", async () => {
    renderPage();
    await screen.findByText("Subscription metrics");
    expect(screen.getByText("Payment due")).toBeInTheDocument();
    // "Past due" also labels an item in the Subscription mix bar further down the page.
    expect(screen.getAllByText("Past due").length).toBeGreaterThan(0);
    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.getByText("Annual")).toBeInTheDocument();
  });

  it("totals invoices from the rows actually returned in the Receivables list", async () => {
    renderPage();
    // 100 + 150 from the two issued invoices above.
    expect(await screen.findByText(/\$250\.00/)).toBeInTheDocument();
  });

  it("says a total is complete when every matching row was fetched", async () => {
    renderPage();
    expect(await screen.findByText(/Across all 2 invoices/)).toBeInTheDocument();
  });

  it("discloses when a total covers only a sample of the matching rows", async () => {
    // 2 rows returned, but the endpoint reports 40 matching — the card must say so rather than
    // presenting the partial sum as a settled balance.
    vi.mocked(listInvoices).mockImplementation(async (params: OffsetListParams) => {
      if (params.filters.status === "issued") {
        return pageOf([invoice("a", 100), invoice("b", 150)], 40);
      }
      return pageOf<Invoice>([]);
    });

    renderPage();
    expect(
      await screen.findByText(/Across the 2 most recent of 40 invoices/),
    ).toBeInTheDocument();
  });

  it("states plainly that no revenue trend is available rather than drawing one", async () => {
    renderPage();
    expect(
      await screen.findByText(/no historical revenue series endpoint/i),
    ).toBeInTheDocument();
  });

  it("renders the subscription mix from the real status breakdown", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Subscription mix")).toBeInTheDocument());
    // "Active"/"Trial" also label cards in the Subscription Metrics section above, so these
    // assert at least one match (the mix bar's own) rather than a single unique one.
    expect((await screen.findAllByText("Active")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trial").length).toBeGreaterThan(0);
  });

  it("surfaces a load failure instead of rendering a zero", async () => {
    vi.mocked(getPlatformStats).mockRejectedValue(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Could not load subscriptions")).toBeInTheDocument();
  });

  // ---- Platform operations (platform_finance, C12) ----------------------------------------

  it("offers a record action for RAAD's own operating costs", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: /record expense/i })).toBeInTheDocument();
  });

  it("keeps subscription revenue out of the manual income ledger", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("button", { name: /record expense/i });

    await user.click(screen.getByRole("tab", { name: "Other income" }));

    // The empty state names what this ledger *is* for and says subscription revenue arrives on
    // its own — the double-count rule ADR-0040 §1 makes structural, made visible.
    expect(
      await screen.findByText(/Subscription revenue is read from billing automatically/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /record income/i }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText(/Not for subscription revenue/i)).toBeInTheDocument();
    // The heading select must not offer it at all, not merely warn about it.
    expect(
      within(drawer).queryByRole("option", { name: /subscription/i }),
    ).not.toBeInTheDocument();
  });

  // ---- Categories and void (pre-deployment audit §C: "no frontend at all") -----------------

  it("creates a platform financial category", async () => {
    const user = userEvent.setup();
    vi.mocked(createPlatformCategory).mockResolvedValue({
      id: "cat-1",
      name: "Cloud infrastructure",
      kind: "expense",
      description: null,
      status: "active",
    });
    renderPage();
    await screen.findByRole("button", { name: /record expense/i });

    await user.click(screen.getByRole("button", { name: /new category/i }));
    const drawer = await screen.findByRole("dialog");
    await user.type(within(drawer).getByPlaceholderText("Cloud infrastructure"), "Cloud infrastructure");
    await user.click(within(drawer).getByRole("button", { name: /create category/i }));

    await waitFor(() =>
      expect(createPlatformCategory).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Cloud infrastructure", kind: "expense" }),
      ),
    );
  });

  it("offers a category picker in the entry form, filtered to the matching kind", async () => {
    const user = userEvent.setup();
    vi.mocked(listPlatformCategories).mockResolvedValue([
      { id: "cat-expense", name: "Cloud hosting", kind: "expense", description: null, status: "active" },
      { id: "cat-income", name: "Reseller margin", kind: "income", description: null, status: "active" },
    ]);
    renderPage();
    await screen.findByRole("button", { name: /record expense/i });

    await user.click(screen.getByRole("button", { name: /record expense/i }));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByRole("option", { name: "Cloud hosting" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("option", { name: "Reseller margin" })).not.toBeInTheDocument();
  });

  it("voids a platform expense after confirmation", async () => {
    const user = userEvent.setup();
    const expense: PlatformExpense = {
      id: "exp-1",
      kind: "rent",
      categoryId: null,
      amount: "500.00",
      currency: "USD",
      occurredOn: "2026-09-01",
      description: null,
      vendor: "Landlord",
      reference: null,
      isVoided: false,
      voidedReason: null,
    };
    vi.mocked(listPlatformExpenses).mockResolvedValue(pageOf([expense]));
    vi.mocked(voidPlatformExpense).mockResolvedValue({ ...expense, isVoided: true });
    renderPage();

    await screen.findByText("Landlord");
    await user.click(screen.getByRole("button", { name: "Void" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/expense entry/i);
    const confirm = within(dialog).getByRole("button", { name: /void entry/i });
    // A void removes money from the P&L, so it cannot be confirmed without saying why.
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/reason/i), "   ");
    expect(confirm).toBeDisabled();
    await user.clear(within(dialog).getByLabelText(/reason/i));
    await user.type(within(dialog).getByLabelText(/reason/i), "  Rent entered twice  ");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(voidPlatformExpense).toHaveBeenCalledWith("exp-1", "Rent entered twice"),
    );
  });

  it("shows the recorded reason on a voided expense instead of a Void button", async () => {
    const voided: PlatformExpense = {
      id: "exp-2",
      kind: "rent",
      categoryId: null,
      amount: "500.00",
      currency: "USD",
      occurredOn: "2026-09-01",
      description: null,
      vendor: "Landlord",
      reference: null,
      isVoided: true,
      voidedReason: "Rent entered twice",
    };
    vi.mocked(listPlatformExpenses).mockResolvedValue(pageOf([voided]));
    renderPage();

    expect(await screen.findByText("Rent entered twice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Void" })).not.toBeInTheDocument();
  });

  it("voids a platform income entry after confirmation", async () => {
    const user = userEvent.setup();
    const income: PlatformIncome = {
      id: "inc-1",
      kind: "grant",
      categoryId: null,
      amount: "2000.00",
      currency: "USD",
      occurredOn: "2026-09-01",
      description: null,
      source: "Ministry of Education",
      reference: null,
      isVoided: false,
      voidedReason: null,
    };
    vi.mocked(listPlatformIncome).mockResolvedValue(pageOf([income]));
    vi.mocked(voidPlatformIncome).mockResolvedValue({ ...income, isVoided: true });
    renderPage();
    await screen.findByRole("button", { name: /record expense/i });

    await user.click(screen.getByRole("tab", { name: "Other income" }));
    await screen.findByText("Ministry of Education");
    await user.click(screen.getByRole("button", { name: "Void" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/income entry/i);
    await user.type(within(dialog).getByLabelText(/reason/i), "Grant was withdrawn");
    await user.click(within(dialog).getByRole("button", { name: /void entry/i }));

    await waitFor(() =>
      expect(voidPlatformIncome).toHaveBeenCalledWith("inc-1", "Grant was withdrawn"),
    );
  });
});
