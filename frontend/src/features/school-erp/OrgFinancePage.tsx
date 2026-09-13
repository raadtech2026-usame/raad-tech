import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Banknote,
  CreditCard,
  FileSpreadsheet,
  Info,
  Landmark,
  Plus,
  ReceiptText,
  Tags,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { Card, CardBody, CardHeader } from "../../shared/components/Card/Card";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { PageSection } from "../../shared/components/PageSection/PageSection";
import { StatCard } from "../../shared/components/StatCard/StatCard";
import { Badge } from "../../shared/components/Badge/Badge";
import { DetailDrawer } from "../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import {
  currentPeriod,
  formatAmount,
  getFinanceSummary,
  getProfitAndLoss,
  listCategories,
  listExpenses,
  listIncome,
  listVehiclesForPicker,
  toLabelMap,
  voidExpense,
  voidIncome,
  type FinancialCategory,
  type LedgerEntry,
} from "./api";
import { CategoryForm } from "./CategoryForm";
import { LedgerEntryForm } from "./LedgerEntryForm";
// Parent Invoice (ADR-0042) — a real aggregate owned by `transport_ops/parents` (the same
// cross-bounded-context reuse `ParentFinancialSummary` already established, not a new pattern).
import { SetInvoicePaymentStatusForm } from "../transport-ops/parents/SetInvoicePaymentStatusForm";
import { ParentSearchSelect, type SelectedParent } from "../transport-ops/parents/ParentSearchSelect";
import { invoiceStatusLabel, invoiceStatusTone } from "../transport-ops/parents/labels";
import {
  formatParentAmount,
  generateParentInvoices,
  getParentInvoiceDetail,
  listParentInvoices,
  type ParentInvoiceStatus,
  type ParentInvoiceSummary,
} from "../transport-ops/parents/api";
import styles from "./OrgFinancePage.module.css";

/**
 * Organization — School Finance (ADR-0038, ADR-0040 §2).
 *
 * **Every figure on this page is a real read.** `GET /school-finance/summary`,
 * `/parent-invoices`, `/income`, `/expenses`, `/categories` and `/profit-and-loss` — all
 * tenant-scoped server-side by ADR-0021, so an Org Admin sees their own school's money and
 * nothing else. Nothing here is estimated, projected or placeholder.
 *
 * **The whole workflow lives on this page, in the order a bursar performs it:** set up a Parent's
 * monthly billing profile → run the month's billing → confirm each family's payment status.
 * Everything after that step is derived, never entered: the Collected KPI, Profit & Loss's Parent-
 * revenue line and every report are all computed from real `ParentInvoice` payment state. There is
 * deliberately no "add Parent fee income" action anywhere, because that money is already counted —
 * see the Income tab's own notice and `LedgerEntryForm`. Per-vehicle revenue/cost breakdowns live
 * in Reports, not here (Finance UI cleanup, 2026-09-12) — this page's own KPIs and Parent Invoice
 * list stay organization-wide.
 *
 * **This page is not the organization's RAAD subscription.** ADR-0038 §2 keeps
 * Organization→Student finance and RAAD→Organization billing in separate bounded contexts with
 * separate aggregates and permissions; mixing them in one view is what that separation exists to
 * prevent. The platform-subscription side is *linked*, never merged — see the Related section.
 *
 * Amounts arrive as exact decimal strings and are formatted, never summed, in this component
 * (see `api.ts`'s own note on why).
 */

type LedgerTab = "invoices" | "income" | "expenses" | "categories";

const LEDGER_TABS: { id: LedgerTab; label: string }[] = [
  { id: "invoices", label: "Parent invoices" },
  { id: "income", label: "Income" },
  { id: "expenses", label: "Expenses" },
  { id: "categories", label: "Categories" },
];

const LIST_PARAMS = { page: 1, pageSize: 25, sort: null, filters: {}, search: "" };
const PICKER_PARAMS = { page: 1, pageSize: 100, sort: null, filters: {}, search: "" };

const PARENT_INVOICE_STATUS_FILTERS: { id: ParentInvoiceStatus | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "unpaid", label: "Unpaid" },
  { id: "partial", label: "Partial" },
  { id: "paid", label: "Paid" },
  { id: "cancelled", label: "Cancelled" },
];

/** Trailing 12 months — the window the standalone "Profit & loss" section further down the page
 * uses, unchanged (that section's own header names this explicitly). Kept separate from
 * `currentPeriodWindow` below so this pre-existing 12-month calculation is never destroyed —
 * only the top-of-page Overview snapshot was ambiguous about mixing the two (Finance UI cleanup,
 * 2026-09-12). */
function defaultWindow(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

/** The first/last calendar day of a `YYYY-MM` period — so the "Financial overview" KPI row's own
 * Net Result card can be computed over the *same* single period as its Expected Billing/Collected/
 * Receivables siblings, instead of silently mixing in the trailing-12-month window (Finance UI
 * cleanup, 2026-09-12: "Period 2026-09" next to a Net Result labeled "12 months" was ambiguous). */
function currentPeriodWindow(period: string): { start: string; end: string } {
  const [year, month] = period.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return { start: `${period}-01`, end: `${period}-${String(lastDay).padStart(2, "0")}` };
}

export function OrgFinancePage() {
  usePageHeader("Finance", "School income, parent billing and expenses");

  const toast = useToast();
  const queryClient = useQueryClient();

  const [period] = useState(currentPeriod());
  const [tab, setTab] = useState<LedgerTab>("invoices");
  const window = defaultWindow();
  const periodWindow = currentPeriodWindow(period);

  const [categoryOpen, setCategoryOpen] = useState(false);
  const [ledgerFormMode, setLedgerFormMode] = useState<"income" | "expense" | null>(null);
  const [voidingLedgerEntry, setVoidingLedgerEntry] = useState<{
    entry: LedgerEntry;
    kind: "income" | "expense";
  } | null>(null);
  const [editingCategory, setEditingCategory] = useState<FinancialCategory | null>(null);

  // Parent Invoice tab state (ADR-0042, refined for the Finance UI cleanup) — Parent/status/
  // vehicle/date-range filters, the row-level "view" detail drawer, and the row-level "Update
  // Payment Status" quick action — one real invoice, no allocation to compute.
  const [invoiceParentFilter, setInvoiceParentFilter] = useState<SelectedParent | null>(null);
  const [invoiceVehicleFilter, setInvoiceVehicleFilter] = useState("");
  const [invoiceDateFrom, setInvoiceDateFrom] = useState("");
  const [invoiceDateTo, setInvoiceDateTo] = useState("");
  const [invoiceStatusFilter, setInvoiceStatusFilter] = useState<ParentInvoiceStatus | "all">("all");
  const [invoicePage, setInvoicePage] = useState(1);
  const [viewingInvoice, setViewingInvoice] = useState<ParentInvoiceSummary | null>(null);
  const [payingParentInvoice, setPayingParentInvoice] = useState<ParentInvoiceSummary | null>(null);

  const summary = useQuery({
    queryKey: ["school-finance", "summary", period],
    queryFn: () => getFinanceSummary(period),
    staleTime: 60_000,
  });
  // Net Result, scoped to the *same* period as `summary` above — the "Financial overview" row's
  // own figure, kept deliberately separate from `pnl` (trailing 12 months) below.
  const periodPnl = useQuery({
    queryKey: ["school-finance", "pnl", periodWindow.start, periodWindow.end],
    queryFn: () => getProfitAndLoss(periodWindow.start, periodWindow.end),
    staleTime: 60_000,
  });
  const pnl = useQuery({
    queryKey: ["school-finance", "pnl", window.start, window.end],
    queryFn: () => getProfitAndLoss(window.start, window.end),
    staleTime: 60_000,
  });
  const parentInvoices = useQuery({
    queryKey: [
      "school-finance",
      "parent-invoices",
      invoicePage,
      invoiceParentFilter?.id ?? null,
      invoiceStatusFilter,
      invoiceVehicleFilter,
      invoiceDateFrom,
      invoiceDateTo,
    ],
    queryFn: () =>
      listParentInvoices({
        page: invoicePage,
        pageSize: 25,
        parentId: invoiceParentFilter?.id ?? null,
        status: invoiceStatusFilter === "all" ? null : invoiceStatusFilter,
        vehicleId: invoiceVehicleFilter || null,
        dateFrom: invoiceDateFrom || null,
        dateTo: invoiceDateTo || null,
      }),
    staleTime: 30_000,
    enabled: tab === "invoices",
  });
  const invoiceDetailQuery = useQuery({
    queryKey: ["school-finance", "parent-invoice-detail", viewingInvoice?.id],
    queryFn: () => getParentInvoiceDetail(viewingInvoice!.id),
    enabled: viewingInvoice !== null,
  });
  const income = useQuery({
    queryKey: ["school-finance", "income"],
    queryFn: () => listIncome(LIST_PARAMS),
    staleTime: 30_000,
    enabled: tab === "income",
  });
  const expenses = useQuery({
    queryKey: ["school-finance", "expenses"],
    queryFn: () => listExpenses(LIST_PARAMS),
    staleTime: 30_000,
    enabled: tab === "expenses",
  });
  const categories = useQuery({
    queryKey: ["school-finance", "categories", "picker"],
    queryFn: () => listCategories(PICKER_PARAMS),
    staleTime: 60_000,
  });

  // Name lookup. An invoice carries `vehicle_id` only — ADR-0040 §3 stores the id so the bill
  // stays historically true, and `.claude/rules/backend.md` #3 forbids the join that would carry
  // a name alongside. Doubles as the new Vehicle filter's own human-readable options below — the
  // raw id remains the fallback rather than a blank, so a vehicle removed since being billed still
  // shows *something* traceable.
  const vehicleLookup = useQuery({
    queryKey: ["school-finance", "vehicles", "picker"],
    queryFn: () => listVehiclesForPicker(),
    staleTime: 5 * 60_000,
  });

  const vehicleNames = useMemo(() => toLabelMap(vehicleLookup.data), [vehicleLookup.data]);
  const categoryNames = useMemo(
    () => new Map((categories.data?.data ?? []).map((c) => [c.id, c.name])),
    [categories.data],
  );

  const vehicleName = (id: string | null | undefined) =>
    id ? vehicleNames.get(id) ?? id : null;

  const currency = summary.data?.currency ?? "USD";

  // Whether the empty state should read as "nothing matches these filters" rather than "nothing
  // has ever been billed" — a Vehicle (or any other) filter narrowing a real, non-empty list down
  // to zero rows is a materially different situation from a school that hasn't billed anyone yet.
  const invoiceFiltersActive =
    invoiceParentFilter !== null ||
    invoiceStatusFilter !== "all" ||
    invoiceVehicleFilter !== "" ||
    invoiceDateFrom !== "" ||
    invoiceDateTo !== "";

  const voidLedgerMutation = useMutation({
    mutationFn: (target: { entry: LedgerEntry; kind: "income" | "expense" }) =>
      target.kind === "income"
        ? voidIncome(target.entry.id, "Voided by school")
        : voidExpense(target.entry.id, "Voided by school"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success("Entry voided", "It stays on record as voided and no longer counts toward totals.");
      setVoidingLedgerEntry(null);
    },
    onError: (error) => {
      toast.error(
        "Could not void the entry",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  /** The monthly billing run (Part 18): every active Billing Profile whose billing has started
   * is picked up automatically for the current period — idempotent, so re-running it never
   * double-charges a family already invoiced this month. */
  const generateInvoicesMutation = useMutation({
    mutationFn: () => generateParentInvoices(period),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        created.length > 0 ? "Invoices generated" : "Already up to date",
        created.length > 0
          ? `${created.length} Parent Invoice${created.length === 1 ? "" : "s"} issued for ${period}.`
          : `Every billed family already has an invoice for ${period}.`,
      );
    },
    onError: (error) => {
      toast.error(
        "Could not generate invoices",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const ledgerAction = (() => {
    switch (tab) {
      case "invoices":
        return (
          <Button
            size="sm"
            leadingIcon={<Plus size={14} />}
            loading={generateInvoicesMutation.isPending}
            onClick={() => generateInvoicesMutation.mutate()}
          >
            Generate monthly invoices
          </Button>
        );
      case "income":
        return (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setLedgerFormMode("income")}>
            Record income
          </Button>
        );
      case "expenses":
        return (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setLedgerFormMode("expense")}>
            Record expense
          </Button>
        );
      case "categories":
        return (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setCategoryOpen(true)}>
            New category
          </Button>
        );
      default:
        return null;
    }
  })();

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      {/* ---- KPI row ---- */}
      <PageSection title="Financial overview" description={`Period ${period}`}>
        <div className={styles.kpiGrid}>
          <StatCard
            icon={<ReceiptText size={18} />}
            tone="brand"
            label="Expected Billing"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.billedAmount, currency) : "—"}
            meta={summary.data ? `${summary.data.invoiceCount} invoices` : undefined}
            metaTone="neutral"
            footnote="Amount expected from Parent monthly billing"
          />
          <StatCard
            icon={<Banknote size={18} />}
            tone="success"
            label="Collected"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.collectedAmount, currency) : "—"}
            meta={summary.data ? `${summary.data.paidInvoiceCount} paid` : undefined}
            metaTone="success"
            footnote="Payments received against Parent Invoices"
          />
          <StatCard
            icon={<Landmark size={18} />}
            tone="warning"
            label="Receivables"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.outstandingAmount, currency) : "—"}
            metaTone="neutral"
            footnote="What families still owe"
          />
          <StatCard
            icon={<TrendingUp size={18} />}
            tone="purple"
            label="Net Result"
            isLoading={periodPnl.isLoading}
            value={periodPnl.data ? formatAmount(periodPnl.data.netProfit, periodPnl.data.currency) : "—"}
            footnote="This period's collected Parent revenue + other income − expenses"
          />
        </div>
      </PageSection>

      {/* ---- Ledger ---- */}
      <PageSection
        title="Ledger"
        action={
          <div className={styles.sectionActions}>
            <Tabs
              options={LEDGER_TABS}
              activeId={tab}
              onSelect={(id) => setTab(id as LedgerTab)}
            />
            {ledgerAction}
          </div>
        }
      >
        <Card>
          {tab === "invoices" && (
            <>
              <CardHeader
                icon={<ReceiptText size={18} />}
                title="Parent invoices"
                subtitle={
                  parentInvoices.data ? `${parentInvoices.data.page.total} total` : "Loading…"
                }
              />
              <CardBody className={styles.filterRow}>
                <FormField label="Parent">
                  <ParentSearchSelect
                    value={invoiceParentFilter}
                    onChange={(parent) => {
                      setInvoiceParentFilter(parent);
                      setInvoicePage(1);
                    }}
                    aria-label="Filter parent invoices by parent"
                  />
                </FormField>
                <FormField label="Payment Status">
                  <Select
                    value={invoiceStatusFilter}
                    onChange={(e) => {
                      setInvoiceStatusFilter(e.target.value as ParentInvoiceStatus | "all");
                      setInvoicePage(1);
                    }}
                    aria-label="Filter parent invoices by payment status"
                  >
                    {PARENT_INVOICE_STATUS_FILTERS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Vehicle">
                  <Select
                    value={invoiceVehicleFilter}
                    onChange={(e) => {
                      setInvoiceVehicleFilter(e.target.value);
                      setInvoicePage(1);
                    }}
                    aria-label="Filter parent invoices by vehicle"
                  >
                    <option value="">All Vehicles</option>
                    {(vehicleLookup.data ?? []).map((vehicle) => (
                      <option key={vehicle.id} value={vehicle.id}>
                        {vehicle.label}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="From">
                  <Input
                    type="date"
                    value={invoiceDateFrom}
                    max={invoiceDateTo || undefined}
                    onChange={(e) => {
                      setInvoiceDateFrom(e.target.value);
                      setInvoicePage(1);
                    }}
                    aria-label="Filter parent invoices from this date"
                  />
                </FormField>
                <FormField label="To">
                  <Input
                    type="date"
                    value={invoiceDateTo}
                    min={invoiceDateFrom || undefined}
                    onChange={(e) => {
                      setInvoiceDateTo(e.target.value);
                      setInvoicePage(1);
                    }}
                    aria-label="Filter parent invoices to this date"
                  />
                </FormField>
              </CardBody>
              {parentInvoices.isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : (parentInvoices.data?.data.length ?? 0) === 0 ? (
                invoiceFiltersActive ? (
                  <EmptyState
                    icon={<ReceiptText size={20} />}
                    title="No parent invoices found"
                    description="No parents match the selected filters. Try All Vehicles, All statuses, or a wider date range."
                  />
                ) : (
                  <EmptyState
                    icon={<ReceiptText size={20} />}
                    title="No parent invoices yet"
                    description="Run a monthly billing batch against a fee plan to issue this period's invoices."
                  />
                )
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Invoice</th>
                        <th>Parent</th>
                        <th className={styles.alignRight}>Children</th>
                        <th>Period</th>
                        <th className={styles.alignRight}>Amount</th>
                        <th className={styles.alignRight}>Paid</th>
                        <th className={styles.alignRight}>Receivable</th>
                        <th>Status</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {parentInvoices.data?.data.map((row) => (
                        <tr key={row.id}>
                          <td className={styles.mono}>{row.invoiceNumber}</td>
                          <td className={styles.strong}>{row.parentName}</td>
                          <td className={styles.alignRight}>{row.childrenCount}</td>
                          <td>{row.period}</td>
                          <td className={styles.alignRight}>
                            {formatParentAmount(row.amount, row.currency)}
                          </td>
                          <td className={styles.alignRight}>
                            {formatParentAmount(row.amountPaid, row.currency)}
                          </td>
                          <td className={clsx(styles.alignRight, styles.strong)}>
                            {formatParentAmount(row.balanceDue, row.currency)}
                          </td>
                          <td>
                            <Badge variant={invoiceStatusTone(row.status)} dot>
                              {invoiceStatusLabel(row.status)}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            <div className={styles.rowActions}>
                              <Button size="sm" variant="ghost" onClick={() => setViewingInvoice(row)}>
                                View
                              </Button>
                              {row.status !== "cancelled" && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  leadingIcon={<Wallet size={13} />}
                                  onClick={() => setPayingParentInvoice(row)}
                                >
                                  Payment status
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {(tab === "income" || tab === "expenses") && (
            <>
              <CardHeader
                icon={
                  tab === "income" ? <TrendingUp size={18} /> : <TrendingDown size={18} />
                }
                title={tab === "income" ? "Other income" : "Expenses"}
                subtitle={
                  tab === "income"
                    ? "Income that is not a student fee — student fees reach the ledger through invoices"
                    : "School expenditure, optionally attributed to a bus"
                }
              />
              {tab === "income" && (
                <CardBody>
                  <div className={styles.autoNotice}>
                    <Info size={16} className={styles.autoNoticeIcon} aria-hidden="true" />
                    <div>
                      <span className={styles.autoNoticeTitle}>
                        Student fee revenue is recorded automatically
                      </span>
                      <p className={styles.autoNoticeText}>
                        {pnl.data ? (
                          <>
                            <strong>
                              {formatAmount(pnl.data.studentRevenue, pnl.data.currency)}
                            </strong>{" "}
                            of student fee revenue has already been counted for the last 12
                            months, derived from payments recorded against invoices. It is not
                            listed below and must never be added here — an entry for the same
                            money would be counted twice. This ledger is for donations,
                            sponsorships, grants, government support and other income with no
                            student invoice behind it.
                          </>
                        ) : (
                          <>
                            Student fee revenue is derived from payments recorded against
                            invoices and is never listed below. This ledger is for donations,
                            sponsorships, grants, government support and other income with no
                            student invoice behind it.
                          </>
                        )}
                      </p>
                    </div>
                  </div>
                </CardBody>
              )}
              {(tab === "income" ? income : expenses).isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : ((tab === "income" ? income : expenses).data?.data.length ?? 0) === 0 ? (
                <EmptyState
                  icon={
                    tab === "income" ? <TrendingUp size={20} /> : <TrendingDown size={20} />
                  }
                  title={tab === "income" ? "No other income recorded" : "No expenses recorded"}
                  description={
                    tab === "income"
                      ? "Donations, sponsorships, grants and government support appear here."
                      : "Fuel, maintenance, salaries and other costs appear here."
                  }
                />
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th className={styles.alignRight}>Amount</th>
                        <th>Category</th>
                        <th>Description</th>
                        {tab === "expenses" && <th>Vehicle</th>}
                        <th>Reference</th>
                        <th>State</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {(tab === "income" ? income : expenses).data?.data.map((e) => (
                        <tr key={e.id} className={e.isVoided ? styles.voidedRow : undefined}>
                          <td>{e.occurredOn}</td>
                          <td className={styles.alignRight}>
                            {formatAmount(e.amount, e.currency)}
                          </td>
                          <td>
                            {e.categoryId ? (
                              categoryNames.get(e.categoryId) ?? (
                                <span className={styles.muted}>—</span>
                              )
                            ) : (
                              <span className={styles.muted}>Uncategorised</span>
                            )}
                          </td>
                          <td>{e.description ?? <span className={styles.muted}>—</span>}</td>
                          {tab === "expenses" && (
                            <td>
                              {vehicleName(e.vehicleId) ?? (
                                <span className={styles.muted}>—</span>
                              )}
                            </td>
                          )}
                          <td>{e.reference ?? <span className={styles.muted}>—</span>}</td>
                          <td>
                            <Badge variant={e.isVoided ? "danger" : "success"} dot>
                              {e.isVoided ? "Voided" : "Recorded"}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            {!e.isVoided && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setVoidingLedgerEntry({ entry: e, kind: tab === "income" ? "income" : "expense" })}
                              >
                                Void
                              </Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {tab === "categories" && (
            <>
              <CardHeader
                icon={<Tags size={18} />}
                title="Financial categories"
                subtitle="The headings income and expenses are filed under, and what Profit & Loss groups by"
              />
              {categories.isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : (categories.data?.data.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<Tags size={20} />}
                  title="No categories yet"
                  description="Entries can be recorded without one, but categories are what make the Profit & Loss breakdown useful."
                />
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Side</th>
                        <th>Nested under</th>
                        <th>Description</th>
                        <th>Status</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {categories.data?.data.map((category) => (
                        <tr key={category.id}>
                          <td className={styles.strong}>{category.name}</td>
                          <td>
                            <Badge variant={category.kind === "income" ? "success" : "warning"}>
                              {category.kind === "income" ? "Income" : "Expense"}
                            </Badge>
                          </td>
                          <td>
                            {category.parentCategoryId
                              ? categoryNames.get(category.parentCategoryId) ?? "—"
                              : <span className={styles.muted}>Top level</span>}
                          </td>
                          <td>
                            {category.description ?? <span className={styles.muted}>—</span>}
                          </td>
                          <td>
                            <Badge
                              variant={category.status === "active" ? "success" : "neutral"}
                              dot
                            >
                              {category.status === "active" ? "Active" : "Archived"}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            {category.status === "active" && (
                              <Button size="sm" variant="ghost" onClick={() => setEditingCategory(category)}>
                                Edit
                              </Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Card>
      </PageSection>

      {/* ---- Profit & loss ---- */}
      <PageSection title="Profit & loss" description="Trailing 12 months, recorded transactions only">
        <Card>
          <CardHeader
            icon={<FileSpreadsheet size={18} />}
            title="Income against expenses"
            subtitle={pnl.data ? `${pnl.data.start} – ${pnl.data.end}` : "Loading…"}
            action={
              <Link to="/org/reports" className={styles.inlineLink}>
                Export <ArrowUpRight size={14} />
              </Link>
            }
          />
          <CardBody>
            {pnl.isLoading ? (
              <>
                <Skeleton height={18} />
                <Skeleton height={18} />
              </>
            ) : pnl.isError ? (
              <EmptyState icon={<FileSpreadsheet size={20} />} title="Could not load profit & loss" />
            ) : pnl.data ? (
              <dl className={styles.pnl}>
                <div className={styles.pnlRow}>
                  <dt>
                    Parent transportation collections
                    <span className={styles.pnlHint}>
                      Derived from recorded payments — never entered by hand
                    </span>
                  </dt>
                  <dd>{formatAmount(pnl.data.studentRevenue, pnl.data.currency)}</dd>
                </div>
                <div className={styles.pnlRow}>
                  <dt>
                    Other income
                    <span className={styles.pnlHint}>
                      Donations, sponsorships, grants and government support
                    </span>
                  </dt>
                  <dd>{formatAmount(pnl.data.otherIncome, pnl.data.currency)}</dd>
                </div>
                <div className={styles.pnlRow}>
                  <dt>Total income</dt>
                  <dd>{formatAmount(pnl.data.totalIncome, pnl.data.currency)}</dd>
                </div>
                <div className={styles.pnlRow}>
                  <dt>Total expenses</dt>
                  <dd>{formatAmount(pnl.data.totalExpenses, pnl.data.currency)}</dd>
                </div>
                <div className={clsx(styles.pnlRow, styles.pnlTotal)}>
                  <dt>Net Result</dt>
                  <dd>{formatAmount(pnl.data.netProfit, pnl.data.currency)}</dd>
                </div>
              </dl>
            ) : null}
          </CardBody>
        </Card>
      </PageSection>

      {/* ---- Related ---- */}
      <PageSection title="Related">
        <div className={styles.relatedRow}>
          <Card className={styles.relatedCard}>
            <CardHeader
              icon={<CreditCard size={18} />}
              title="Platform subscription"
              subtitle="A separate financial domain — RAAD bills your organization"
            />
            <CardBody>
              <p className={styles.note}>
                Your organization&apos;s own RAAD subscription, its invoices and its payment
                history are platform billing, not school finance. The two are kept apart
                deliberately: one is money your organization pays RAAD, the other is money
                students pay your school. They have separate records and are never combined into
                a single balance.
              </p>
              <div>
                <Link to="/org/billing" className={styles.inlineLink}>
                  Open Billing <ArrowUpRight size={14} />
                </Link>
              </div>
            </CardBody>
          </Card>

          <Card className={styles.relatedCard}>
            <CardHeader
              icon={<FileSpreadsheet size={18} />}
              title="Reports"
              subtitle="Parent billing, vehicle revenue and receivables"
            />
            <CardBody>
              <p className={styles.note}>
                Every view on this page has a matching report that renders to PDF or Excel,
                including the printable per-bus roster with each student&apos;s fee and balance.
              </p>
              <div>
                <Link to="/org/reports" className={styles.inlineLink}>
                  Open Reports <ArrowUpRight size={14} />
                </Link>
              </div>
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* ---- Actions ---- */}
      <DetailDrawer
        open={viewingInvoice !== null}
        onClose={() => setViewingInvoice(null)}
        icon={<ReceiptText size={20} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={viewingInvoice?.invoiceNumber}
        subtitle={viewingInvoice?.parentName}
        status={
          invoiceDetailQuery.data && (
            <Badge variant={invoiceStatusTone(invoiceDetailQuery.data.status)} dot>
              {invoiceStatusLabel(invoiceDetailQuery.data.status)}
            </Badge>
          )
        }
        stats={
          invoiceDetailQuery.data
            ? [
                { key: "Amount", value: formatParentAmount(invoiceDetailQuery.data.amount, invoiceDetailQuery.data.currency) },
                { key: "Paid", value: formatParentAmount(invoiceDetailQuery.data.amountPaid, invoiceDetailQuery.data.currency) },
                {
                  key: "Receivable",
                  value: formatParentAmount(invoiceDetailQuery.data.balanceDue, invoiceDetailQuery.data.currency),
                  color: invoiceDetailQuery.data.balanceDue !== "0.00" ? "var(--color-danger)" : undefined,
                },
              ]
            : undefined
        }
        mapSlot={
          <div className={styles.childLineItems}>
            <span className={styles.childLineItemsTitle}>Children on this invoice</span>
            {invoiceDetailQuery.isLoading && <Skeleton height={36} />}
            {invoiceDetailQuery.data?.lines.map((line) => (
              <div key={line.studentId} className={styles.childLineItemRow}>
                <div>
                  <div className={styles.strong}>{line.fullName}</div>
                  <div className={styles.muted}>{vehicleName(line.vehicleId) ?? "No vehicle assigned"}</div>
                </div>
                <span className={styles.muted}>
                  {formatParentAmount(line.amount, invoiceDetailQuery.data!.currency)}
                </span>
              </div>
            ))}
          </div>
        }
        footer={
          viewingInvoice &&
          invoiceDetailQuery.data &&
          invoiceDetailQuery.data.status !== "cancelled" && (
            <Button leadingIcon={<Wallet size={14} />} onClick={() => setPayingParentInvoice(viewingInvoice)}>
              Payment status
            </Button>
          )
        }
      />
      <SetInvoicePaymentStatusForm
        open={payingParentInvoice !== null}
        onClose={() => setPayingParentInvoice(null)}
        invoice={payingParentInvoice}
      />
      <CategoryForm
        open={categoryOpen || editingCategory !== null}
        onClose={() => {
          setCategoryOpen(false);
          setEditingCategory(null);
        }}
        defaultKind="expense"
        categories={categories.data?.data ?? []}
        editing={editingCategory}
      />
      <LedgerEntryForm
        open={ledgerFormMode !== null}
        onClose={() => setLedgerFormMode(null)}
        mode={ledgerFormMode ?? "expense"}
        currency={currency}
      />

      <ConfirmDialog
        open={voidingLedgerEntry !== null}
        title={voidingLedgerEntry?.kind === "income" ? "Void this income entry?" : "Void this expense entry?"}
        description={
          voidingLedgerEntry
            ? `${formatAmount(voidingLedgerEntry.entry.amount, voidingLedgerEntry.entry.currency)} will be reversed. The entry stays on record as voided and no longer counts toward Profit & Loss.`
            : undefined
        }
        confirmLabel="Void entry"
        tone="danger"
        loading={voidLedgerMutation.isPending}
        onConfirm={() => voidingLedgerEntry && voidLedgerMutation.mutate(voidingLedgerEntry)}
        onCancel={() => setVoidingLedgerEntry(null)}
      />
    </div>
  );
}
