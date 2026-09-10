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
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listInvoices: vi.fn(),
  listPayments: vi.fn(),
}));

import { getPlatformStats } from "../platform-analytics/api";
import {
  getPlatformPnl,
  listPlatformExpenses,
  listPlatformIncome,
} from "../platform-finance/api";
import { listInvoices, listPayments } from "./api";
import { PlatformFinancePage } from "./PlatformFinancePage";

const STATS: PlatformStats = {
  organizations: { total: 3, byStatus: { active: 2 }, createdToday: 1 },
  vehicles: { total: 8 },
  devices: { total: 5, online: 4, offline: 1 },
  users: { total: 20, byStatus: { active: 18 }, monthlyActive: 12, createdToday: 2 },
  billing: { subscriptionByStatus: { active: 6, trial: 1 }, expiringSoon: 2, revenue: 4500 },
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
      start: "2025-09-08",
      end: "2026-09-08",
      subscriptionRevenue: "4500.00",
      otherIncome: "0.00",
      totalRevenue: "4500.00",
      totalExpenses: "0.00",
      netProfit: "4500.00",
      expensesByKind: {},
      incomeByKind: {},
      currency: "USD",
    });
    vi.mocked(listPlatformExpenses).mockResolvedValue(
      pageOf<never>([]) as never,
    );
    vi.mocked(listPlatformIncome).mockResolvedValue(pageOf<never>([]) as never);
  });

  it("shows month-to-date revenue from platform stats, not a computed guess", async () => {
    renderPage();
    expect(await screen.findByText("$4,500")).toBeInTheDocument();
    expect(screen.getByText("Month to date")).toBeInTheDocument();
  });

  it("totals outstanding invoices from the rows actually returned", async () => {
    renderPage();
    // 100 + 150 from the two issued invoices above.
    expect(await screen.findByText("$250.00")).toBeInTheDocument();
    expect(screen.getByText("2 unpaid")).toBeInTheDocument();
  });

  it("says a total is complete when every matching row was fetched", async () => {
    renderPage();
    expect(await screen.findByText("Across all 2 issued invoices")).toBeInTheDocument();
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
      await screen.findByText("Across the 2 most recent of 40 issued invoices"),
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
    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Trial")).toBeInTheDocument();
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
});
