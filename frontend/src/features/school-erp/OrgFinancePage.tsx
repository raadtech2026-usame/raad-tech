import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Banknote,
  Bus,
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
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import {
  archiveFeePlan,
  currentPeriod,
  formatAmount,
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
  toLabelMap,
  voidStudentPayment,
  type StudentInvoice,
  type StudentInvoiceStatus,
  type StudentPayment,
} from "./api";
import { CategoryForm } from "./CategoryForm";
import { FeePlanForm } from "./FeePlanForm";
import { GenerateInvoicesForm } from "./GenerateInvoicesForm";
import { LedgerEntryForm } from "./LedgerEntryForm";
import { RecordPaymentForm } from "./RecordPaymentForm";
import styles from "./OrgFinancePage.module.css";

/**
 * Organization — School Finance (ADR-0038, ADR-0040 §2).
 *
 * **Every figure on this page is a real read.** `GET /school-finance/summary`,
 * `/vehicles`, `/student-invoices`, `/student-payments`, `/income`, `/expenses`, `/fee-plans`,
 * `/categories` and `/profit-and-loss` — all tenant-scoped server-side by ADR-0021, so an Org
 * Admin sees their own school's money and nothing else. Nothing here is estimated, projected or
 * placeholder.
 *
 * **The whole workflow lives on this page, in the order a bursar performs it:** create a fee
 * plan → run the month's billing → record each family's payment. Everything after that step is
 * derived, never entered: the Collected KPI, per-bus revenue, Profit & Loss's student-revenue
 * line and every report are all computed from `erp_student_payments`. There is deliberately no
 * "add student fee income" action anywhere, because that money is already counted — see the
 * Income tab's own notice and `LedgerEntryForm`.
 *
 * **This page is not the organization's RAAD subscription.** ADR-0038 §2 keeps
 * Organization→Student finance and RAAD→Organization billing in separate bounded contexts with
 * separate aggregates and permissions; mixing them in one view is what that separation exists to
 * prevent. The platform-subscription side is *linked*, never merged — see the Related section.
 *
 * Amounts arrive as exact decimal strings and are formatted, never summed, in this component
 * (see `api.ts`'s own note on why).
 */

const STATUS_TONE: Record<StudentInvoiceStatus, "success" | "warning" | "danger" | "neutral" | "info"> = {
  draft: "neutral",
  issued: "warning",
  partially_paid: "info",
  paid: "success",
  overdue: "danger",
  cancelled: "neutral",
};

const STATUS_LABEL: Record<StudentInvoiceStatus, string> = {
  draft: "Draft",
  issued: "Issued",
  partially_paid: "Partially paid",
  paid: "Paid",
  overdue: "Overdue",
  cancelled: "Cancelled",
};

type LedgerTab = "invoices" | "payments" | "income" | "expenses" | "feePlans" | "categories";

const LEDGER_TABS: { id: LedgerTab; label: string }[] = [
  { id: "invoices", label: "Student invoices" },
  { id: "payments", label: "Payments" },
  { id: "income", label: "Income" },
  { id: "expenses", label: "Expenses" },
  { id: "feePlans", label: "Fee plans" },
  { id: "categories", label: "Categories" },
];

const LIST_PARAMS = { page: 1, pageSize: 25, sort: null, filters: {}, search: "" };
const PICKER_PARAMS = { page: 1, pageSize: 100, sort: null, filters: {}, search: "" };

/** An invoice can still take money unless it is fully settled or cancelled. */
function isPayable(invoice: StudentInvoice): boolean {
  return invoice.status !== "paid" && invoice.status !== "cancelled";
}

/** Trailing 12 months — the window the Profit & Loss endpoint defaults to server-side too. */
function defaultWindow(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function OrgFinancePage() {
  usePageHeader("Finance", "School income, expenses and student billing");

  const toast = useToast();
  const queryClient = useQueryClient();

  const [period] = useState(currentPeriod());
  const [tab, setTab] = useState<LedgerTab>("invoices");
  const window = defaultWindow();

  const [payingInvoice, setPayingInvoice] = useState<StudentInvoice | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [feePlanOpen, setFeePlanOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [ledgerFormMode, setLedgerFormMode] = useState<"income" | "expense" | null>(null);
  const [voidingPayment, setVoidingPayment] = useState<StudentPayment | null>(null);
  const [archivingPlanId, setArchivingPlanId] = useState<string | null>(null);

  const summary = useQuery({
    queryKey: ["school-finance", "summary", period],
    queryFn: () => getFinanceSummary(period),
    staleTime: 60_000,
  });
  const vehicles = useQuery({
    queryKey: ["school-finance", "vehicles", period],
    queryFn: () => listVehicleFinance(period),
    staleTime: 60_000,
  });
  const pnl = useQuery({
    queryKey: ["school-finance", "pnl", window.start, window.end],
    queryFn: () => getProfitAndLoss(window.start, window.end),
    staleTime: 60_000,
  });
  const invoices = useQuery({
    queryKey: ["school-finance", "invoices"],
    queryFn: () => listStudentInvoices(LIST_PARAMS),
    staleTime: 30_000,
    enabled: tab === "invoices",
  });
  const payments = useQuery({
    queryKey: ["school-finance", "payments"],
    queryFn: () => listStudentPayments(LIST_PARAMS),
    staleTime: 30_000,
    enabled: tab === "payments",
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
  const feePlans = useQuery({
    queryKey: ["school-finance", "fee-plans"],
    queryFn: () => listFeePlans(PICKER_PARAMS),
    staleTime: 60_000,
    enabled: tab === "feePlans",
  });
  const categories = useQuery({
    queryKey: ["school-finance", "categories", "picker"],
    queryFn: () => listCategories(PICKER_PARAMS),
    staleTime: 60_000,
  });

  // Name lookups. An invoice carries `student_id`/`vehicle_id` only — ADR-0040 §3 stores the ids
  // so the bill stays historically true, and `.claude/rules/backend.md` #3 forbids the join that
  // would carry a name alongside. Two cached list reads resolve every row on the page; the raw
  // id remains the fallback rather than a blank, so a student removed since being billed still
  // shows *something* traceable.
  const studentLookup = useQuery({
    queryKey: ["school-finance", "students", "picker"],
    queryFn: () => listStudentsForPicker(),
    staleTime: 5 * 60_000,
  });
  const vehicleLookup = useQuery({
    queryKey: ["school-finance", "vehicles", "picker"],
    queryFn: () => listVehiclesForPicker(),
    staleTime: 5 * 60_000,
  });

  const studentNames = useMemo(() => toLabelMap(studentLookup.data), [studentLookup.data]);
  const vehicleNames = useMemo(() => toLabelMap(vehicleLookup.data), [vehicleLookup.data]);
  const categoryNames = useMemo(
    () => new Map((categories.data?.data ?? []).map((c) => [c.id, c.name])),
    [categories.data],
  );

  const studentName = (id: string) => studentNames.get(id) ?? id;
  const vehicleName = (id: string | null | undefined) =>
    id ? vehicleNames.get(id) ?? id : null;

  const currency = summary.data?.currency ?? "USD";

  const voidMutation = useMutation({
    mutationFn: (payment: StudentPayment) => voidStudentPayment(payment.id, "Voided by school"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        "Payment voided",
        "The invoice balance has been restored and revenue totals adjusted.",
      );
      setVoidingPayment(null);
    },
    onError: (error) => {
      toast.error(
        "Could not void the payment",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (planId: string) => archiveFeePlan(planId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success("Fee plan archived", "Invoices already issued from it are unchanged.");
      setArchivingPlanId(null);
    },
    onError: (error) => {
      toast.error(
        "Could not archive the fee plan",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const ledgerAction = (() => {
    switch (tab) {
      case "invoices":
        return (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setGenerateOpen(true)}>
            Generate invoices
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
      case "feePlans":
        return (
          <Button size="sm" leadingIcon={<Plus size={14} />} onClick={() => setFeePlanOpen(true)}>
            New fee plan
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
            label="Billed"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.billedAmount, currency) : "—"}
            meta={summary.data ? `${summary.data.invoiceCount} invoices` : undefined}
            metaTone="neutral"
            footnote="Net of discounts, cancelled invoices excluded"
          />
          <StatCard
            icon={<Banknote size={18} />}
            tone="success"
            label="Collected"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.collectedAmount, currency) : "—"}
            meta={summary.data ? `${summary.data.paidInvoiceCount} settled` : undefined}
            metaTone="success"
            footnote="Payments received against student invoices"
          />
          <StatCard
            icon={<Landmark size={18} />}
            tone="warning"
            label="Outstanding"
            isLoading={summary.isLoading}
            value={summary.data ? formatAmount(summary.data.outstandingAmount, currency) : "—"}
            meta={summary.data ? `${summary.data.overdueInvoiceCount} overdue` : undefined}
            metaTone={
              summary.data && summary.data.overdueInvoiceCount > 0 ? "danger" : "neutral"
            }
            footnote="What families still owe"
          />
          <StatCard
            icon={<TrendingUp size={18} />}
            tone="purple"
            label="Net profit"
            isLoading={pnl.isLoading}
            value={pnl.data ? formatAmount(pnl.data.netProfit, pnl.data.currency) : "—"}
            meta="12 months"
            metaTone="purple"
            footnote="Income less expenses, from recorded transactions"
          />
        </div>
      </PageSection>

      {/* ---- Vehicle financial overview ---- */}
      <PageSection
        title="Vehicle financial overview"
        description="Students, revenue, outstanding balance and attributed cost, per bus"
      >
        <Card>
          <CardHeader
            icon={<Bus size={18} />}
            title="Revenue per bus"
            subtitle={
              vehicles.data
                ? `${vehicles.data.length} vehicle${vehicles.data.length === 1 ? "" : "s"} with billing activity`
                : "Loading…"
            }
          />
          {vehicles.isError ? (
            <EmptyState
              icon={<Bus size={20} />}
              title="Could not load vehicle finance"
              description={
                vehicles.error instanceof ApiError
                  ? vehicles.error.message
                  : "Something went wrong. Please try again."
              }
            />
          ) : vehicles.isLoading ? (
            <CardBody>
              <Skeleton height={18} />
              <Skeleton height={18} />
              <Skeleton height={18} />
            </CardBody>
          ) : (vehicles.data?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Bus size={20} />}
              title="No billing activity yet"
              description="Once student invoices are issued, each bus appears here with its own revenue and outstanding balance."
            />
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Vehicle</th>
                    <th className={styles.alignRight}>Students</th>
                    <th className={styles.alignRight}>Paid</th>
                    <th className={styles.alignRight}>Unpaid</th>
                    <th className={styles.alignRight}>Billed</th>
                    <th className={styles.alignRight}>Collected</th>
                    <th className={styles.alignRight}>Outstanding</th>
                    <th className={styles.alignRight}>Cost</th>
                    <th className={styles.alignRight}>Net</th>
                  </tr>
                </thead>
                <tbody>
                  {vehicles.data?.map((v) => (
                    <tr key={v.vehicleId ?? "unassigned"}>
                      <td className={styles.strong}>
                        {vehicleName(v.vehicleId) ?? (
                          <span className={styles.muted}>Unassigned</span>
                        )}
                      </td>
                      <td className={styles.alignRight}>{v.studentCount}</td>
                      <td className={styles.alignRight}>{v.paidStudentCount}</td>
                      <td className={styles.alignRight}>
                        {v.unpaidStudentCount > 0 ? (
                          <Badge variant="warning">{v.unpaidStudentCount}</Badge>
                        ) : (
                          v.unpaidStudentCount
                        )}
                      </td>
                      <td className={styles.alignRight}>
                        {formatAmount(v.billedAmount, v.currency)}
                      </td>
                      <td className={styles.alignRight}>
                        {formatAmount(v.collectedAmount, v.currency)}
                      </td>
                      <td className={styles.alignRight}>
                        {formatAmount(v.outstandingAmount, v.currency)}
                      </td>
                      <td className={styles.alignRight}>
                        {formatAmount(v.expenseAmount, v.currency)}
                      </td>
                      <td className={clsx(styles.alignRight, styles.strong)}>
                        {formatAmount(v.netAmount, v.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
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
                title="Student invoices"
                subtitle={
                  invoices.data ? `${invoices.data.page.total} total` : "Loading…"
                }
              />
              {invoices.isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : (invoices.data?.data.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<ReceiptText size={20} />}
                  title="No student invoices yet"
                  description="Run a monthly billing batch against a fee plan to issue this period's invoices."
                />
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Period</th>
                        <th>Student</th>
                        <th>Vehicle</th>
                        <th className={styles.alignRight}>Net</th>
                        <th className={styles.alignRight}>Paid</th>
                        <th className={styles.alignRight}>Balance</th>
                        <th>Due</th>
                        <th>Status</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {invoices.data?.data.map((inv) => (
                        <tr key={inv.id}>
                          <td>{inv.period}</td>
                          <td className={styles.strong}>{studentName(inv.studentId)}</td>
                          <td>
                            {vehicleName(inv.vehicleId) ?? (
                              <span className={styles.muted}>—</span>
                            )}
                          </td>
                          <td className={styles.alignRight}>
                            {formatAmount(inv.netAmount, inv.currency)}
                          </td>
                          <td className={styles.alignRight}>
                            {formatAmount(inv.amountPaid, inv.currency)}
                          </td>
                          <td className={clsx(styles.alignRight, styles.strong)}>
                            {formatAmount(inv.balanceDue, inv.currency)}
                          </td>
                          <td>{inv.dueDate}</td>
                          <td>
                            <Badge variant={STATUS_TONE[inv.status]} dot>
                              {STATUS_LABEL[inv.status]}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            {isPayable(inv) && (
                              <Button
                                size="sm"
                                variant="secondary"
                                leadingIcon={<Wallet size={13} />}
                                onClick={() => setPayingInvoice(inv)}
                              >
                                Record payment
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

          {tab === "payments" && (
            <>
              <CardHeader
                icon={<Wallet size={18} />}
                title="Payments received"
                subtitle={payments.data ? `${payments.data.page.total} total` : "Loading…"}
              />
              {payments.isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : (payments.data?.data.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<Wallet size={20} />}
                  title="No payments recorded"
                  description="Payments appear here once a family pays against a student invoice."
                />
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Received</th>
                        <th>Student</th>
                        <th className={styles.alignRight}>Amount</th>
                        <th>Method</th>
                        <th>Reference</th>
                        <th>State</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {payments.data?.data.map((p) => (
                        <tr key={p.id}>
                          <td>{p.receivedOn}</td>
                          <td className={styles.strong}>{studentName(p.studentId)}</td>
                          <td className={styles.alignRight}>
                            {formatAmount(p.amount, p.currency)}
                          </td>
                          <td className={styles.capitalize}>
                            {p.method.replace(/_/g, " ")}
                          </td>
                          <td>{p.reference ?? <span className={styles.muted}>—</span>}</td>
                          <td>
                            <Badge variant={p.isVoided ? "danger" : "success"} dot>
                              {p.isVoided ? "Voided" : "Recorded"}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            {!p.isVoided && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setVoidingPayment(p)}
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {tab === "feePlans" && (
            <>
              <CardHeader
                icon={<FileSpreadsheet size={18} />}
                title="Fee plans"
                subtitle="The recurring charges a monthly billing run bills against"
              />
              {feePlans.isLoading ? (
                <CardBody>
                  <Skeleton height={18} />
                  <Skeleton height={18} />
                </CardBody>
              ) : (feePlans.data?.data.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<FileSpreadsheet size={20} />}
                  title="No fee plans yet"
                  description="A fee plan sets the amount each student is billed per period. Create one to start the monthly billing run."
                />
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th className={styles.alignRight}>Amount</th>
                        <th className={styles.alignRight}>Standard discount</th>
                        <th>Description</th>
                        <th>Status</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {feePlans.data?.data.map((plan) => (
                        <tr key={plan.id}>
                          <td className={styles.strong}>{plan.name}</td>
                          <td className={styles.alignRight}>
                            {formatAmount(plan.amount, plan.currency)}
                          </td>
                          <td className={styles.alignRight}>
                            {formatAmount(plan.defaultDiscountAmount, plan.currency)}
                          </td>
                          <td>{plan.description ?? <span className={styles.muted}>—</span>}</td>
                          <td>
                            <Badge variant={plan.status === "active" ? "success" : "neutral"} dot>
                              {plan.status === "active" ? "Active" : "Archived"}
                            </Badge>
                          </td>
                          <td className={styles.rowAction}>
                            {plan.status === "active" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setArchivingPlanId(plan.id)}
                              >
                                Archive
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
                    Student fee revenue (collected)
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
                  <dt>Net profit</dt>
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
              subtitle="Student billing, vehicle revenue and outstanding balances"
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
      <RecordPaymentForm
        open={payingInvoice !== null}
        onClose={() => setPayingInvoice(null)}
        invoice={payingInvoice}
        studentLabel={payingInvoice ? studentName(payingInvoice.studentId) : ""}
      />
      <GenerateInvoicesForm
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        period={period}
      />
      <FeePlanForm
        open={feePlanOpen}
        onClose={() => setFeePlanOpen(false)}
        currency={currency}
      />
      <CategoryForm
        open={categoryOpen}
        onClose={() => setCategoryOpen(false)}
        defaultKind="expense"
        categories={categories.data?.data ?? []}
      />
      <LedgerEntryForm
        open={ledgerFormMode !== null}
        onClose={() => setLedgerFormMode(null)}
        mode={ledgerFormMode ?? "expense"}
        currency={currency}
      />

      <ConfirmDialog
        open={voidingPayment !== null}
        title="Void this payment?"
        description={
          voidingPayment
            ? `${formatAmount(voidingPayment.amount, voidingPayment.currency)} from ${studentName(voidingPayment.studentId)} will be reversed. The payment stays on record as voided, the invoice balance is restored, and revenue totals adjust accordingly.`
            : undefined
        }
        confirmLabel="Void payment"
        tone="danger"
        loading={voidMutation.isPending}
        onConfirm={() => voidingPayment && voidMutation.mutate(voidingPayment)}
        onCancel={() => setVoidingPayment(null)}
      />

      <ConfirmDialog
        open={archivingPlanId !== null}
        title="Archive this fee plan?"
        description="It can no longer be used for new billing runs. Invoices already issued from it keep their own amounts and are unaffected."
        confirmLabel="Archive"
        tone="danger"
        loading={archiveMutation.isPending}
        onConfirm={() => archivingPlanId && archiveMutation.mutate(archivingPlanId)}
        onCancel={() => setArchivingPlanId(null)}
      />
    </div>
  );
}
