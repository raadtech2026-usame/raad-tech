import { useQueries, useQuery } from "@tanstack/react-query";
import type { OffsetListParams } from "../../shared/api/listParams";
import {
  listInvoices,
  listPayments,
  type Invoice,
  type InvoiceStatus,
  type PaymentStatus,
} from "./api";

/**
 * Read helpers backing the RAAD Platform finance surface (`PlatformFinancePage`).
 *
 * **No new backend route, no new permission, no new aggregate.** Every figure here is composed
 * from endpoints that already exist and are already reachable by the roles that can open the
 * page: `GET /billing/invoices`, `GET /billing/payments`, and (in the page itself)
 * `GET /admin/platform-stats`. Nothing in this file invents a number.
 *
 * Two honesty constraints shape the whole design, and both are load-bearing:
 *
 * 1. **Counts are exact; sums are sampled.** The list endpoints return an offset page with a
 *    true `page.total`, so a per-status *count* obtained with `pageSize: 1` is the real count
 *    of matching rows. A per-status *sum* is not available from any endpoint — there is no
 *    aggregate route — so it has to be computed over rows actually fetched. Every consumer of
 *    `summariseAmounts` is therefore handed `isComplete`, and the page states plainly when a
 *    total covers a sample rather than the whole set. Silently summing one page and calling it
 *    "outstanding balance" would be a fabricated figure with a real number's authority.
 *
 * 2. **Amounts are grouped by currency, never added across them.** `invoices.currency` and
 *    `payments.currency` are per-row. Summing 100 USD and 100 EUR into "200" is wrong in a way
 *    that looks right, so `summariseAmounts` returns one total per currency and the page renders
 *    the dominant one with the rest disclosed beside it.
 */

/** Largest page the list endpoints accept (API Contracts §7 — `page_size` is capped at 100). */
export const MAX_PAGE_SIZE = 100;

function listParams(
  filters: Record<string, string>,
  pageSize: number,
  sort: OffsetListParams["sort"] = null,
): OffsetListParams {
  return { page: 1, pageSize, sort, filters, search: "" };
}

/* ------------------------------------------------------------------------------------------ */
/* Amount summaries                                                                             */
/* ------------------------------------------------------------------------------------------ */

export interface CurrencyTotal {
  currency: string;
  total: number;
  count: number;
}

export interface AmountSummary {
  /** The currency with the most rows behind it, or `null` when there are no rows at all. */
  primary: CurrencyTotal | null;
  /** Every other currency present, largest count first. Empty in the ordinary single-currency
   * case; non-empty means the primary figure is deliberately not the whole picture. */
  others: CurrencyTotal[];
  /** `false` when more rows match the filter than were fetched — the caller must say so rather
   * than presenting a sampled sum as a settled total. */
  isComplete: boolean;
  /** True number of matching rows, from the endpoint's own `page.total`. Always exact. */
  matchingRows: number;
}

export function summariseAmounts(
  rows: { amount: number; currency: string }[],
  matchingRows: number,
): AmountSummary {
  const byCurrency = new Map<string, CurrencyTotal>();
  for (const row of rows) {
    const entry = byCurrency.get(row.currency) ?? { currency: row.currency, total: 0, count: 0 };
    entry.total += row.amount;
    entry.count += 1;
    byCurrency.set(row.currency, entry);
  }

  const sorted = [...byCurrency.values()].sort((a, b) => b.count - a.count || b.total - a.total);

  return {
    primary: sorted[0] ?? null,
    others: sorted.slice(1),
    isComplete: rows.length >= matchingRows,
    matchingRows,
  };
}

/* ------------------------------------------------------------------------------------------ */
/* Invoices                                                                                     */
/* ------------------------------------------------------------------------------------------ */

export const INVOICE_STATUSES: InvoiceStatus[] = ["draft", "issued", "paid", "void"];

export interface StatusCounts<T extends string> {
  counts: Record<T, number>;
  total: number;
  isLoading: boolean;
  isError: boolean;
}

/** One `pageSize: 1` request per status, reading only `page.total`. Exact counts, four small
 * requests — the same count-only technique `app/dashboard/hooks.ts` already uses for vehicle
 * status, rather than paging the whole invoice table into the browser to count it. */
export function useInvoiceStatusCounts(): StatusCounts<InvoiceStatus> {
  const results = useQueries({
    queries: INVOICE_STATUSES.map((status) => ({
      queryKey: ["finance", "invoice-count", status],
      queryFn: async () => (await listInvoices(listParams({ status }, 1))).page.total,
      staleTime: 60_000,
    })),
  });

  const counts = INVOICE_STATUSES.reduce(
    (acc, status, index) => {
      acc[status] = results[index].data ?? 0;
      return acc;
    },
    {} as Record<InvoiceStatus, number>,
  );

  return {
    counts,
    total: Object.values<number>(counts).reduce((sum, value) => sum + value, 0),
    isLoading: results.some((r) => r.isLoading),
    isError: results.some((r) => r.isError),
  };
}

export interface InvoiceSample {
  invoices: Invoice[];
  summary: AmountSummary;
  isLoading: boolean;
  isError: boolean;
}

/** Invoices for one status, newest first, capped at `MAX_PAGE_SIZE`. `summary.isComplete` says
 * whether that cap was actually reached. */
export function useInvoicesByStatus(status: InvoiceStatus, pageSize = MAX_PAGE_SIZE): InvoiceSample {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["finance", "invoices", status, pageSize],
    queryFn: () =>
      listInvoices(listParams({ status }, pageSize, { field: "created_at", direction: "desc" })),
    staleTime: 60_000,
  });

  return {
    invoices: data?.data ?? [],
    summary: summariseAmounts(data?.data ?? [], data?.page.total ?? 0),
    isLoading,
    isError,
  };
}

/* ------------------------------------------------------------------------------------------ */
/* Payments                                                                                     */
/* ------------------------------------------------------------------------------------------ */

export const PAYMENT_STATUSES: PaymentStatus[] = [
  "pending",
  "processing",
  "paid",
  "failed",
  "expired",
];

export function usePaymentStatusCounts(): StatusCounts<PaymentStatus> {
  const results = useQueries({
    queries: PAYMENT_STATUSES.map((status) => ({
      queryKey: ["finance", "payment-count", status],
      queryFn: async () => (await listPayments(listParams({ status }, 1))).page.total,
      staleTime: 60_000,
    })),
  });

  const counts = PAYMENT_STATUSES.reduce(
    (acc, status, index) => {
      acc[status] = results[index].data ?? 0;
      return acc;
    },
    {} as Record<PaymentStatus, number>,
  );

  return {
    counts,
    total: Object.values<number>(counts).reduce((sum, value) => sum + value, 0),
    isLoading: results.some((r) => r.isLoading),
    isError: results.some((r) => r.isError),
  };
}

/** Most recent payments regardless of status — the cash-flow feed. */
export function useRecentPayments(pageSize = 8) {
  return useQuery({
    queryKey: ["finance", "recent-payments", pageSize],
    queryFn: () =>
      listPayments(listParams({}, pageSize, { field: "created_at", direction: "desc" })),
    staleTime: 30_000,
  });
}
