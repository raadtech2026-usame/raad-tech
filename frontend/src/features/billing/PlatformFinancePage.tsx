import { useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  Banknote,
  Calendar,
  CalendarRange,
  CreditCard,
  FileText,
  Hourglass,
  Landmark,
  Plus,
  ReceiptText,
  Scale,
  Tags,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { Card, CardHeader, CardBody } from "../../shared/components/Card/Card";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { PageSection } from "../../shared/components/PageSection/PageSection";
import { StatCard } from "../../shared/components/StatCard/StatCard";
import { Badge } from "../../shared/components/Badge/Badge";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { DateRangePresetFilter } from "../reports/components/DateRangePresetFilter";
import { getPlatformStats, type PlatformStats } from "../platform-analytics/api";
import { StatBar, type StatBarItem } from "../../app/dashboard/StatBar";
import {
  expenseKindLabel,
  getPlatformPnl,
  listPlatformCategories,
  listPlatformExpenses,
  listPlatformIncome,
  voidPlatformExpense,
  voidPlatformIncome,
  type PlatformExpense,
  type PlatformIncome,
} from "../platform-finance/api";
import {
  PlatformEntryForm,
  type PlatformEntryMode,
} from "../platform-finance/PlatformEntryForm";
import { PlatformCategoryForm } from "../platform-finance/PlatformCategoryForm";
import {
  useInvoiceStatusCounts,
  useInvoicesByStatus,
  usePaymentStatusCounts,
  useRecentPayments,
  type AmountSummary,
} from "./finance";
import { formatAmount, formatDateOnly, formatDateTime } from "./format";
import {
  invoiceStatusLabel,
  invoiceStatusTone,
  paymentStatusLabel,
  paymentStatusTone,
  subscriptionStatusLabel,
  subscriptionStatusTone,
} from "./labels";
import type { SubscriptionStatus } from "./api";
import styles from "./PlatformFinancePage.module.css";

/**
 * RAAD Platform — Finance.
 *
 * RAAD's own financial picture: revenue it bills Organizations, what it has collected, what is
 * still outstanding, and — since ADR-0040 §1 — what it spends to operate.
 *
 * **Two bounded contexts, kept visibly apart on one page.** `billing` (C8, RAAD -> Organization)
 * supplies every revenue and receivables figure; `platform_finance` (C12, Vendor -> RAAD)
 * supplies the operating-cost section at the foot. They are read through separate clients and
 * rendered as separate sections rather than merged into one ledger, because they are separate
 * money flows with separate permissions.
 *
 * **Neither of them is school finance.** Fee plans, student invoices, student payments and
 * organization income/expenses are the `school_erp` context (C11, Organization -> Student), which
 * ADR-0038 §2 requires to stay a separate domain with its own aggregates. This page reads nothing
 * from it, and the Organization Finance page reads nothing from these two.
 *
 * **Every figure is real.** Sources, all pre-existing and all already permitted for the roles
 * that can reach this route:
 *   - `GET /admin/platform-stats` (ADR-0020) — month-to-date revenue, subscription mix,
 *     subscriptions expiring soon.
 *   - `GET /billing/invoices` — invoice counts per status (exact) and amounts (sampled, see
 *     below).
 *   - `GET /billing/payments` — payment counts per status (exact), amounts, and the recent
 *     payment feed.
 *
 * **What this page deliberately does not show, and why.** There is no revenue *trend*: no
 * endpoint in this backend returns a historical series, and `platform_stats.billing.revenue` is
 * a single point-in-time month-to-date total (ADR-0020). A sparkline here would be invented, so
 * the Revenue Analytics section shows composition — which is genuinely derivable from real rows
 * — and says plainly that period-over-period comparison needs a backend capability that does not
 * exist yet. Likewise, amount totals are summed over the rows actually fetched (up to 100 per
 * status); wherever more rows match than were fetched, the card says so rather than presenting a
 * sample as a settled balance. See `finance.ts` for the full reasoning.
 *
 * No new API, no new permission, no new route on the backend — this is a composition of reads
 * that already existed.
 */

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/** Formats an `AmountSummary`'s primary currency total, or an em dash when there is nothing to
 * total. Never adds across currencies (see `finance.ts`). */
function formatSummary(summary: AmountSummary): string {
  if (!summary.primary) return "—";
  return formatAmount(summary.primary.total, summary.primary.currency);
}

/** The disclosure line under a sampled total. Returns `null` when the figure is complete and
 * single-currency, so an accurate total is not decorated with a caveat it does not need. */
function summaryFootnote(summary: AmountSummary, noun: string): string {
  if (!summary.primary) return `No ${noun} yet`;

  const parts: string[] = [];
  parts.push(
    summary.isComplete
      ? `Across all ${summary.matchingRows} ${noun}`
      : `Across the ${summary.primary.count} most recent of ${summary.matchingRows} ${noun}`,
  );
  if (summary.others.length > 0) {
    parts.push(`plus ${summary.others.length} other currency${summary.others.length === 1 ? "" : "ies"}`);
  }
  return parts.join(" · ");
}

/** Formats a `Date` as `YYYY-MM-DD` using its own *local* calendar date — mirrors
 * `DateRangePresetFilter`'s own `isoDate` helper (never `.toISOString()`, which normalises to
 * UTC first and can silently shift the day for a timezone behind UTC). */
function isoDate(d: Date): string {
  const year = String(d.getFullYear()).padStart(4, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** The page's initial period: month-to-date — the conventional default for a finance dashboard.
 * The Founder can widen or narrow it via the period selector; nothing below assumes this range. */
function defaultWindow(): { start: string; end: string } {
  const now = new Date();
  return { start: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)), end: isoDate(now) };
}

type ReceivablesTab = "issued" | "paid" | "draft" | "void";

const RECEIVABLES_TABS: { id: ReceivablesTab; label: string }[] = [
  { id: "issued", label: "Unpaid" },
  { id: "paid", label: "Paid" },
  { id: "draft", label: "Draft" },
  { id: "void", label: "Void" },
];

/** The two sides of RAAD's own ledger — deliberately not including subscription revenue, which
 * lives in `billing` and is only ever read into the P&L (ADR-0040 §1). */
type OpexTab = "expenses" | "income";

const OPEX_TABS: { id: OpexTab; label: string }[] = [
  { id: "expenses", label: "Operating expenses" },
  { id: "income", label: "Other income" },
];

export function PlatformFinancePage() {
  usePageHeader("Finance", "Revenue, receivables and payments across the platform");

  const toast = useToast();
  const queryClient = useQueryClient();

  const [receivablesTab, setReceivablesTab] = useState<ReceivablesTab>("issued");
  const [opexTab, setOpexTab] = useState<OpexTab>("expenses");
  const [period, setPeriod] = useState(defaultWindow);
  const [entryMode, setEntryMode] = useState<PlatformEntryMode | null>(null);
  const [categoryFormOpen, setCategoryFormOpen] = useState(false);
  const [voidingEntry, setVoidingEntry] = useState<{
    entry: PlatformExpense | PlatformIncome;
    kind: "income" | "expense";
  } | null>(null);
  const [voidReason, setVoidReason] = useState("");

  const stats = useQuery<PlatformStats>({
    queryKey: ["platform-analytics-stats"],
    queryFn: getPlatformStats,
    staleTime: 60_000,
  });

  const invoiceCounts = useInvoiceStatusCounts();
  const paymentCounts = usePaymentStatusCounts();
  const tabInvoices = useInvoicesByStatus(receivablesTab);
  const recentPayments = useRecentPayments(8);

  // ADR-0040 §1 — RAAD's own operating costs, and (since the Organization Management phase)
  // the platform's own Invoiced/Collected/Receivables figures too. `subscription_revenue`/
  // `subscription_invoiced`/`subscription_receivables` are `billing` (C8) figures the P&L
  // endpoint reads through `SubscriptionRevenuePort` — a different bounded context from the
  // `platform_finance` (C12) expense/income reads below, composed here into one query only
  // because the endpoint itself already composes them server-side (ADR-0038 §2's separation is
  // about aggregates and permissions, not about which page may display a number).
  const platformPnl = useQuery({
    queryKey: ["platform-finance", "pnl", period.start, period.end],
    queryFn: () => getPlatformPnl(period.start, period.end),
    staleTime: 60_000,
  });
  const platformExpenses = useQuery({
    queryKey: ["platform-finance", "expenses"],
    queryFn: () =>
      listPlatformExpenses({ page: 1, pageSize: 15, sort: null, filters: {}, search: "" }),
    staleTime: 60_000,
  });
  const platformIncome = useQuery({
    queryKey: ["platform-finance", "income"],
    queryFn: () =>
      listPlatformIncome({ page: 1, pageSize: 15, sort: null, filters: {}, search: "" }),
    staleTime: 60_000,
    enabled: opexTab === "income",
  });
  const platformCategories = useQuery({
    queryKey: ["platform-finance", "categories"],
    queryFn: listPlatformCategories,
    staleTime: 60_000,
  });
  const categoryNames = new Map((platformCategories.data ?? []).map((c) => [c.id, c.name]));

  const voidMutation = useMutation({
    // Explicit `Promise<void>` return, mirroring `PlatformEntryForm`'s own mutation for the
    // identical reason: the two branches resolve to different DTOs (`PlatformExpense` vs
    // `PlatformIncome`), and `useMutation` infers the union rather than widening, which
    // `MutationFunction` rejects. Nothing here reads the result, so `void` is both honest and
    // the narrowest thing that works.
    mutationFn: async (target: {
      entry: PlatformExpense | PlatformIncome;
      kind: "income" | "expense";
      reason: string;
    }): Promise<void> => {
      if (target.kind === "income") {
        await voidPlatformIncome(target.entry.id, target.reason);
      } else {
        await voidPlatformExpense(target.entry.id, target.reason);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-finance"] });
      toast.success("Entry voided", "It stays on record as voided and no longer counts toward the platform P&L.");
      setVoidingEntry(null);
      setVoidReason("");
    },
    onError: (error) => {
      toast.error(
        "Could not void the entry",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const subscriptionItems: StatBarItem[] = stats.data
    ? Object.entries(stats.data.billing.subscriptionByStatus).map(([status, value]) => ({
        key: status,
        label: subscriptionStatusLabel(status as SubscriptionStatus),
        value,
        tone: subscriptionStatusTone(status as SubscriptionStatus),
      }))
    : [];

  const invoiceItems: StatBarItem[] = invoiceCounts.isLoading
    ? []
    : [
        { key: "paid", label: "Paid", value: invoiceCounts.counts.paid, tone: "success" },
        { key: "issued", label: "Issued", value: invoiceCounts.counts.issued, tone: "warning" },
        { key: "draft", label: "Draft", value: invoiceCounts.counts.draft, tone: "neutral" },
        { key: "void", label: "Void", value: invoiceCounts.counts.void, tone: "danger" },
      ];

  const paymentItems: StatBarItem[] = paymentCounts.isLoading
    ? []
    : [
        { key: "paid", label: "Paid", value: paymentCounts.counts.paid, tone: "success" },
        { key: "processing", label: "Processing", value: paymentCounts.counts.processing, tone: "info" },
        { key: "pending", label: "Pending", value: paymentCounts.counts.pending, tone: "neutral" },
        { key: "failed", label: "Failed", value: paymentCounts.counts.failed, tone: "danger" },
        { key: "expired", label: "Expired", value: paymentCounts.counts.expired, tone: "purple" },
      ];

  const activeSubscriptions = stats.data?.billing.subscriptionByStatus.active ?? 0;
  const pnlError = platformPnl.isError
    ? platformPnl.error instanceof ApiError
      ? platformPnl.error.message
      : "Something went wrong. Please try again."
    : null;
  const netProfitValue = platformPnl.data ? Number(platformPnl.data.netProfit) : 0;

  const subscriptionByStatus = stats.data?.billing.subscriptionByStatus ?? {};
  const activeByBillingCycle = stats.data?.billing.activeByBillingCycle ?? {};

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      {/* ---- Financial KPIs ---- */}
      <PageSection
        title="Financial overview"
        description={
          platformPnl.data ? `${platformPnl.data.start} – ${platformPnl.data.end}` : undefined
        }
        action={
          <DateRangePresetFilter
            start={period.start}
            end={period.end}
            onChange={(range) => setPeriod(range)}
          />
        }
      >
        {pnlError ? (
          <EmptyState icon={<Scale size={20} />} title="Could not load the financial overview" description={pnlError} />
        ) : (
          <div className={styles.kpiGrid}>
            <StatCard
              icon={<FileText size={18} />}
              tone="brand"
              label="Invoiced"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(Number(platformPnl.data.subscriptionInvoiced), platformPnl.data.currency)
                  : "—"
              }
              footnote="Billed to organizations in the selected period"
            />

            <StatCard
              icon={<Banknote size={18} />}
              tone="success"
              label="Collected"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(Number(platformPnl.data.subscriptionRevenue), platformPnl.data.currency)
                  : "—"
              }
              footnote="Subscription payments actually received"
            />

            <StatCard
              icon={<Landmark size={18} />}
              tone="warning"
              label="Receivables"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(Number(platformPnl.data.subscriptionReceivables), platformPnl.data.currency)
                  : "—"
              }
              footnote={`As of ${platformPnl.data?.end ?? "today"} — not limited to the selected period`}
            />

            <StatCard
              icon={<TrendingUp size={18} />}
              tone="brand"
              label="Revenue"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(Number(platformPnl.data.totalRevenue), platformPnl.data.currency)
                  : "—"
              }
              footnote="Subscription collections plus other platform income"
            />

            <StatCard
              icon={<TrendingDown size={18} />}
              tone="danger"
              label="Expenses"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(Number(platformPnl.data.totalExpenses), platformPnl.data.currency)
                  : "—"
              }
              footnote="RAAD's own operating costs in the selected period"
            />

            <StatCard
              icon={<Scale size={18} />}
              tone={netProfitValue >= 0 ? "success" : "danger"}
              label="Net profit"
              isLoading={platformPnl.isLoading}
              value={
                platformPnl.data
                  ? formatAmount(netProfitValue, platformPnl.data.currency)
                  : "—"
              }
              footnote="Revenue minus expenses for the selected period"
            />
          </div>
        )}
      </PageSection>

      {/* ---- Subscription metrics ---- */}
      <PageSection
        title="Subscription metrics"
        description="Platform-wide subscription counts — independent of the period selected above."
      >
        <div className={styles.kpiGrid}>
          <StatCard
            icon={<CreditCard size={18} />}
            tone="success"
            label="Active"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(activeSubscriptions) : "—"}
            meta={stats.data ? `${stats.data.billing.expiringSoon} expiring soon` : undefined}
            metaTone={stats.data && stats.data.billing.expiringSoon > 0 ? "warning" : "neutral"}
            footnote="Subscriptions currently billing organizations"
          />

          <StatCard
            icon={<Hourglass size={18} />}
            tone="purple"
            label="Trial"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(subscriptionByStatus.trial ?? 0) : "—"}
            footnote="Subscriptions still in their one-time trial label"
          />

          <StatCard
            icon={<AlertTriangle size={18} />}
            tone={stats.data && stats.data.paymentDueOrganizations > 0 ? "danger" : "neutral"}
            label="Payment due"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(stats.data.paymentDueOrganizations) : "—"}
            footnote="Organizations whose trial ended with no subscription opened yet"
          />

          <StatCard
            icon={<AlertCircle size={18} />}
            tone={subscriptionByStatus.past_due ? "warning" : "neutral"}
            label="Past due"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(subscriptionByStatus.past_due ?? 0) : "—"}
            footnote="Subscriptions with an unpaid period past its end date"
          />

          <StatCard
            icon={<Calendar size={18} />}
            tone="brand"
            label="Monthly"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(activeByBillingCycle.monthly ?? 0) : "—"}
            footnote="Active subscribers on a monthly billing cycle"
          />

          <StatCard
            icon={<CalendarRange size={18} />}
            tone="purple"
            label="Annual"
            isLoading={stats.isLoading}
            value={stats.data ? numberFormatter.format(activeByBillingCycle.annual ?? 0) : "—"}
            footnote="Active subscribers on an annual billing cycle"
          />
        </div>
      </PageSection>

      {/* ---- Revenue analytics (composition, not trend — see this file's docstring) ---- */}
      <PageSection
        title="Revenue analytics"
        description="Composition of current billing. Period-over-period comparison is not available."
      >
        <div className={styles.splitRow}>
          <Card className={styles.splitHalf}>
            <CardHeader
              icon={<CreditCard size={18} />}
              title="Subscription mix"
              subtitle="Every subscription, by lifecycle status"
            />
            <CardBody>
              {stats.isError ? (
                <EmptyState
                  icon={<CreditCard size={20} />}
                  title="Could not load subscriptions"
                  description={
                    stats.error instanceof ApiError
                      ? stats.error.message
                      : "Something went wrong. Please try again."
                  }
                />
              ) : stats.isLoading || !stats.data ? (
                <Skeleton height={10} />
              ) : (
                <>
                  <StatBar items={subscriptionItems} emptyLabel="No subscriptions opened yet." />
                  <p className={styles.note}>
                    Month-to-date revenue is a single point-in-time total. RAAD has no historical
                    revenue series endpoint, so no trend is shown here rather than an estimated one.
                  </p>
                </>
              )}
            </CardBody>
          </Card>

          <Card className={styles.splitHalf}>
            <CardHeader
              icon={<ReceiptText size={18} />}
              title="Invoice mix"
              subtitle="Exact counts across every invoice"
            />
            <CardBody>
              {invoiceCounts.isError ? (
                <EmptyState icon={<ReceiptText size={20} />} title="Could not load invoices" />
              ) : invoiceCounts.isLoading ? (
                <Skeleton height={10} />
              ) : (
                <>
                  <StatBar items={invoiceItems} emptyLabel="No invoices issued yet." />
                  <p className={styles.note}>
                    {invoiceCounts.total} invoice{invoiceCounts.total === 1 ? "" : "s"} in total.
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* ---- Receivables ---- */}
      <PageSection
        title="Receivables"
        action={
          <Tabs
            options={RECEIVABLES_TABS}
            activeId={receivablesTab}
            onSelect={(id) => setReceivablesTab(id as ReceivablesTab)}
          />
        }
      >
        <Card>
          <CardHeader
            icon={<FileText size={18} />}
            title={`${RECEIVABLES_TABS.find((t) => t.id === receivablesTab)?.label} invoices`}
            subtitle={
              tabInvoices.isLoading
                ? "Loading…"
                : `${formatSummary(tabInvoices.summary)} · ${summaryFootnote(tabInvoices.summary, "invoices")}`
            }
            action={
              <Link to="/platform/billing" className={styles.inlineLink}>
                Open Billing <ArrowUpRight size={14} />
              </Link>
            }
          />
          {tabInvoices.isError ? (
            <EmptyState
              icon={<FileText size={20} />}
              title="Could not load invoices"
              description="The billing service did not return invoices for this status."
            />
          ) : tabInvoices.isLoading ? (
            <CardBody>
              <Skeleton height={16} />
              <Skeleton height={16} />
              <Skeleton height={16} />
            </CardBody>
          ) : tabInvoices.invoices.length === 0 ? (
            <EmptyState
              icon={<FileText size={20} />}
              title={`No ${RECEIVABLES_TABS.find((t) => t.id === receivablesTab)?.label.toLowerCase()} invoices`}
              description="Invoices appear here as subscriptions are billed."
            />
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Period</th>
                    <th>Due</th>
                    <th>Status</th>
                    <th className={styles.alignRight}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {tabInvoices.invoices.slice(0, 10).map((invoice) => (
                    <tr key={invoice.id}>
                      <td className={styles.strong}>{invoice.number}</td>
                      <td>
                        {formatDateOnly(invoice.periodStart)} – {formatDateOnly(invoice.periodEnd)}
                      </td>
                      <td>{formatDateTime(invoice.dueAt)}</td>
                      <td>
                        <Badge variant={invoiceStatusTone(invoice.status)} dot>
                          {invoiceStatusLabel(invoice.status)}
                        </Badge>
                      </td>
                      <td className={clsx(styles.alignRight, styles.strong)}>
                        {formatAmount(invoice.amount, invoice.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </PageSection>

      {/* ---- Cash flow ---- */}
      <PageSection title="Cash flow">
        <div className={styles.splitRow}>
          <Card className={styles.splitWide}>
            <CardHeader
              icon={<Wallet size={18} />}
              title="Recent payments"
              subtitle="Newest payment attempts across every organization"
            />
            {recentPayments.isError ? (
              <EmptyState icon={<Wallet size={20} />} title="Could not load payments" />
            ) : recentPayments.isLoading ? (
              <CardBody>
                <Skeleton height={16} />
                <Skeleton height={16} />
                <Skeleton height={16} />
              </CardBody>
            ) : (recentPayments.data?.data.length ?? 0) === 0 ? (
              <EmptyState
                icon={<Wallet size={20} />}
                title="No payments yet"
                description="Payments appear here once an organization pays an invoice."
              />
            ) : (
              <ul className={styles.feed}>
                {recentPayments.data?.data.map((payment) => (
                  <li key={payment.id} className={styles.feedRow}>
                    <div className={styles.feedMain}>
                      <span className={styles.feedAmount}>
                        {formatAmount(payment.amount, payment.currency)}
                      </span>
                      <span className={styles.feedProvider}>{payment.provider}</span>
                    </div>
                    <div className={styles.feedMeta}>
                      <Badge variant={paymentStatusTone(payment.status)} dot>
                        {paymentStatusLabel(payment.status)}
                      </Badge>
                      <span className={styles.feedTime}>
                        {formatDateTime(payment.confirmedAt ?? payment.createdAt)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className={styles.splitNarrow}>
            <CardHeader
              icon={<Banknote size={18} />}
              title="Payment outcomes"
              subtitle="Exact counts across every payment attempt"
            />
            <CardBody>
              {paymentCounts.isError ? (
                <EmptyState icon={<Banknote size={20} />} title="Could not load payments" />
              ) : paymentCounts.isLoading ? (
                <Skeleton height={10} />
              ) : (
                <>
                  <StatBar items={paymentItems} emptyLabel="No payment attempts yet." />
                  <p className={styles.note}>
                    {paymentCounts.total} attempt{paymentCounts.total === 1 ? "" : "s"} recorded.
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* ---- Reporting ---- */}
      {/* ---- RAAD operating costs (platform_finance, C12) ---- */}
      <PageSection
        title="Platform operations"
        description="What RAAD spends to run the platform — a separate financial domain from the revenue above."
        action={
          <div className={styles.sectionActions}>
            <Tabs
              options={OPEX_TABS}
              activeId={opexTab}
              onSelect={(id) => setOpexTab(id as OpexTab)}
            />
            <Button
              size="sm"
              variant="secondary"
              leadingIcon={<Tags size={14} />}
              onClick={() => setCategoryFormOpen(true)}
            >
              New category
            </Button>
            <Button
              size="sm"
              leadingIcon={<Plus size={14} />}
              onClick={() => setEntryMode(opexTab === "income" ? "income" : "expense")}
            >
              {opexTab === "income" ? "Record income" : "Record expense"}
            </Button>
          </div>
        }
      >
        <div className={styles.splitRow}>
          <Card className={styles.splitNarrow}>
            <CardHeader
              icon={<Scale size={18} />}
              title="Platform profit & loss"
              subtitle={
                platformPnl.data
                  ? `${platformPnl.data.start} – ${platformPnl.data.end}`
                  : "Trailing 12 months"
              }
            />
            <CardBody>
              {platformPnl.isError ? (
                <EmptyState
                  icon={<Scale size={20} />}
                  title="Could not load platform P&L"
                  description="This view is restricted to Founder and Finance Staff."
                />
              ) : platformPnl.isLoading ? (
                <>
                  <Skeleton height={16} />
                  <Skeleton height={16} />
                </>
              ) : platformPnl.data ? (
                <dl className={styles.pnl}>
                  <div className={styles.pnlRow}>
                    <dt>Subscription revenue (collected)</dt>
                    <dd>
                      {formatAmount(
                        Number(platformPnl.data.subscriptionRevenue),
                        platformPnl.data.currency,
                      )}
                    </dd>
                  </div>
                  <div className={styles.pnlRow}>
                    <dt>Other platform income</dt>
                    <dd>
                      {formatAmount(
                        Number(platformPnl.data.otherIncome),
                        platformPnl.data.currency,
                      )}
                    </dd>
                  </div>
                  <div className={styles.pnlRow}>
                    <dt>Total operating expenses</dt>
                    <dd>
                      {formatAmount(
                        Number(platformPnl.data.totalExpenses),
                        platformPnl.data.currency,
                      )}
                    </dd>
                  </div>
                  <div className={clsx(styles.pnlRow, styles.pnlTotal)}>
                    <dt>Net profit</dt>
                    <dd>
                      {formatAmount(
                        Number(platformPnl.data.netProfit),
                        platformPnl.data.currency,
                      )}
                    </dd>
                  </div>
                </dl>
              ) : null}
              <p className={styles.note}>
                Subscription revenue is read from the billing module rather than recorded
                here, so the same payment can never be counted twice.
              </p>
            </CardBody>
          </Card>

          <Card className={styles.splitWide}>
            {opexTab === "expenses" ? (
              <>
                <CardHeader
                  icon={<TrendingDown size={18} />}
                  title="Operating expenses"
                  subtitle="Salaries, rent, utilities, equipment, fuel and other platform costs"
                />
                {platformExpenses.isError ? (
                  <EmptyState
                    icon={<TrendingDown size={20} />}
                    title="Could not load expenses"
                    description="This view is restricted to Founder and Finance Staff."
                  />
                ) : platformExpenses.isLoading ? (
                  <CardBody>
                    <Skeleton height={16} />
                    <Skeleton height={16} />
                  </CardBody>
                ) : (platformExpenses.data?.data.length ?? 0) === 0 ? (
                  <EmptyState
                    icon={<TrendingDown size={20} />}
                    title="No operating expenses recorded"
                    description="Record salaries, rent, utilities and other platform costs to build the P&L beside this."
                  />
                ) : (
                  <div className={styles.tableScroll}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Heading</th>
                          <th>Category</th>
                          <th>Vendor</th>
                          <th className={styles.alignRight}>Amount</th>
                          <th aria-label="Actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {platformExpenses.data?.data.map((expense) => (
                          <tr
                            key={expense.id}
                            className={expense.isVoided ? styles.voidedRow : undefined}
                          >
                            <td>{expense.occurredOn}</td>
                            <td className={styles.strong}>{expenseKindLabel(expense.kind)}</td>
                            <td>
                              {expense.categoryId
                                ? categoryNames.get(expense.categoryId) ?? "—"
                                : "Uncategorised"}
                            </td>
                            <td>{expense.vendor ?? "—"}</td>
                            <td className={styles.alignRight}>
                              {formatAmount(Number(expense.amount), expense.currency)}
                            </td>
                            {expense.isVoided ? (
                              <td className={styles.voidReason}>{expense.voidedReason ?? ""}</td>
                            ) : (
                              <td>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => setVoidingEntry({ entry: expense, kind: "expense" })}
                                >
                                  Void
                                </Button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            ) : (
              <>
                <CardHeader
                  icon={<TrendingUp size={18} />}
                  title="Other platform income"
                  subtitle="Hardware, installation, support contracts and grants — never subscription revenue"
                />
                {platformIncome.isError ? (
                  <EmptyState
                    icon={<TrendingUp size={20} />}
                    title="Could not load income"
                    description="This view is restricted to Founder and Finance Staff."
                  />
                ) : platformIncome.isLoading ? (
                  <CardBody>
                    <Skeleton height={16} />
                    <Skeleton height={16} />
                  </CardBody>
                ) : (platformIncome.data?.data.length ?? 0) === 0 ? (
                  <EmptyState
                    icon={<TrendingUp size={20} />}
                    title="No other income recorded"
                    description="Subscription revenue is read from billing automatically and is never listed here. This is for hardware sales, installations, support contracts and grants."
                  />
                ) : (
                  <div className={styles.tableScroll}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Heading</th>
                          <th>Category</th>
                          <th>Source</th>
                          <th className={styles.alignRight}>Amount</th>
                          <th aria-label="Actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {platformIncome.data?.data.map((entry) => (
                          <tr
                            key={entry.id}
                            className={entry.isVoided ? styles.voidedRow : undefined}
                          >
                            <td>{entry.occurredOn}</td>
                            <td className={styles.strong}>{expenseKindLabel(entry.kind)}</td>
                            <td>
                              {entry.categoryId
                                ? categoryNames.get(entry.categoryId) ?? "—"
                                : "Uncategorised"}
                            </td>
                            <td>{entry.source ?? "—"}</td>
                            <td className={styles.alignRight}>
                              {formatAmount(Number(entry.amount), entry.currency)}
                            </td>
                            {entry.isVoided ? (
                              <td className={styles.voidReason}>{entry.voidedReason ?? ""}</td>
                            ) : (
                              <td>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => setVoidingEntry({ entry, kind: "income" })}
                                >
                                  Void
                                </Button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </Card>
        </div>
      </PageSection>

      <PageSection title="Financial reporting">
        <Card>
          <CardHeader
            icon={<FileText size={18} />}
            title="Reports"
            subtitle="Revenue, subscriptions, invoices, payments and platform expenses"
          />
          <CardBody>
            <p className={styles.note}>
              Every figure on this page has a matching report that renders to real PDF or
              Excel (ADR-0040 §6). Reports stream on demand rather than being staged as
              stored artifacts, so a download is the finished file, not a job reference.
            </p>
            <div>
              <Link to="/platform/reports" className={styles.inlineLink}>
                Open Reports <ArrowUpRight size={14} />
              </Link>
            </div>
          </CardBody>
        </Card>
      </PageSection>

      <PlatformEntryForm
        open={entryMode !== null}
        onClose={() => setEntryMode(null)}
        mode={entryMode ?? "expense"}
        currency={platformPnl.data?.currency ?? "USD"}
      />

      <PlatformCategoryForm
        open={categoryFormOpen}
        onClose={() => setCategoryFormOpen(false)}
        defaultKind={opexTab === "income" ? "income" : "expense"}
      />

      <ConfirmDialog
        open={voidingEntry !== null}
        title={voidingEntry?.kind === "income" ? "Void this income entry?" : "Void this expense entry?"}
        description={
          voidingEntry
            ? `${formatAmount(Number(voidingEntry.entry.amount), voidingEntry.entry.currency)} will be reversed. The entry stays on record as voided and no longer counts toward the platform P&L.`
            : undefined
        }
        confirmLabel="Void entry"
        tone="danger"
        loading={voidMutation.isPending}
        confirmDisabled={voidReason.trim() === ""}
        onConfirm={() =>
          voidingEntry && voidMutation.mutate({ ...voidingEntry, reason: voidReason.trim() })
        }
        onCancel={() => {
          setVoidingEntry(null);
          setVoidReason("");
        }}
      >
        <FormField label="Reason" hint="Required. Kept on the voided entry for the audit record.">
          <Input
            value={voidReason}
            maxLength={255}
            placeholder="e.g. Invoice from vendor was entered twice"
            onChange={(event) => setVoidReason(event.target.value)}
          />
        </FormField>
      </ConfirmDialog>
    </div>
  );
}
