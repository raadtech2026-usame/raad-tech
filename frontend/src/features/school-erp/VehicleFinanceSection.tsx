import { useMemo, useState } from "react";
import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Bus, Plus } from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { CardBody, CardHeader } from "../../shared/components/Card/Card";
import { DetailDrawer } from "../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import {
  formatAmount,
  getVehicleFinanceReport,
  listVehicleFinance,
  type IncomeType,
  type VehicleFinance,
} from "./api";
import styles from "./OrgFinancePage.module.css";

/** The current calendar month as an inclusive ISO date range — the default window. */
export function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const lastDay = new Date(year, month, 0).getDate();
  const mm = String(month).padStart(2, "0");
  return { start: `${year}-${mm}-01`, end: `${year}-${mm}-${String(lastDay).padStart(2, "0")}` };
}

export interface VehicleLedgerAction {
  mode: "income" | "expense";
  incomeType?: IncomeType;
  vehicleId: string;
}

/**
 * Vehicle finance (ADR-0047 §7): per bus, for a date range, the three income sources kept apart
 * — student income (payments received for students who rode this bus when they were billed),
 * daily income and other income — then attributed expenses and net. Opening a bus shows every
 * row behind those figures. Nothing is estimated: each figure is a sum of recorded rows.
 *
 * Organization-wide income and costs (no bus named) are in Profit & Loss, not here, and the
 * "Unassigned" row holds student money for invoices generated before the student had a bus.
 */
export function VehicleFinanceSection({
  vehicleNames,
  categoryNames,
  canManage,
  onRecord,
}: {
  vehicleNames: Map<string, string>;
  categoryNames: Map<string, string>;
  canManage: boolean;
  onRecord: (action: VehicleLedgerAction) => void;
}) {
  const initial = currentMonthRange();
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [selected, setSelected] = useState<string | null>(null);
  const validRange = start !== "" && end !== "" && start <= end;

  const overview = useQuery({
    queryKey: ["school-finance", "vehicles", "overview", start, end],
    queryFn: () => listVehicleFinance(start, end),
    enabled: validRange,
    staleTime: 30_000,
  });
  const report = useQuery({
    queryKey: ["school-finance", "vehicles", "report", selected, start, end],
    queryFn: () => getVehicleFinanceReport(selected!, start, end),
    enabled: selected !== null && validRange,
  });

  const rows = overview.data ?? [];
  const totals = useMemo(() => sumRows(rows), [rows]);
  const currency = rows[0]?.currency ?? "USD";
  const name = (id: string | null) => (id ? vehicleNames.get(id) ?? id : "Unassigned");

  return (
    <>
      <CardHeader
        icon={<Bus size={18} />}
        title="Vehicle finance"
        subtitle="Student, daily and other income, expenses and net — per bus"
      />
      <CardBody className={styles.filterRow}>
        <FormField label="From">
          <Input type="date" value={start} max={end || undefined} onChange={(e) => setStart(e.target.value)} aria-label="Vehicle finance from" />
        </FormField>
        <FormField label="To">
          <Input type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} aria-label="Vehicle finance to" />
        </FormField>
      </CardBody>
      {!validRange ? (
        <EmptyState icon={<Bus size={20} />} title="Choose a date range" description="The start date must not be after the end date." />
      ) : overview.isLoading ? (
        <CardBody>
          <Skeleton height={18} />
          <Skeleton height={18} />
        </CardBody>
      ) : overview.isError ? (
        <EmptyState
          icon={<Bus size={20} />}
          title="Could not load vehicle finance"
          description={overview.error instanceof ApiError ? overview.error.message : undefined}
        />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Bus size={20} />} title="No vehicle income or expenses in this period" />
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Vehicle</th>
                <th className={styles.alignRight}>Student income</th>
                <th className={styles.alignRight}>Daily income</th>
                <th className={styles.alignRight}>Other income</th>
                <th className={styles.alignRight}>Total income</th>
                <th className={styles.alignRight}>Expenses</th>
                <th className={styles.alignRight}>Net</th>
                <th className={styles.alignRight}>Still owed</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.vehicleId ?? "unassigned"}>
                  <td className={styles.strong}>{name(row.vehicleId)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.studentIncome, row.currency)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.dailyIncome, row.currency)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.otherIncome, row.currency)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.totalIncome, row.currency)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.expenseAmount, row.currency)}</td>
                  <td className={clsx(styles.alignRight, styles.strong)}>{formatAmount(row.netAmount, row.currency)}</td>
                  <td className={styles.alignRight}>{formatAmount(row.outstandingAmount, row.currency)}</td>
                  <td className={styles.rowAction}>
                    {row.vehicleId && (
                      <Button size="sm" variant="ghost" onClick={() => setSelected(row.vehicleId)}>
                        View
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              <tr className={styles.totalRow}>
                <td>Total</td>
                <td className={styles.alignRight}>{formatAmount(totals.studentIncome, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.dailyIncome, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.otherIncome, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.totalIncome, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.expenseAmount, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.netAmount, currency)}</td>
                <td className={styles.alignRight}>{formatAmount(totals.outstandingAmount, currency)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        icon={<Bus size={20} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selected ? name(selected) : undefined}
        subtitle={`${start} – ${end}`}
        stats={
          report.data
            ? [
                { key: "Total income", value: formatAmount(report.data.totalIncome, report.data.currency) },
                { key: "Expenses", value: formatAmount(report.data.totalExpenses, report.data.currency) },
                { key: "Net", value: formatAmount(report.data.netAmount, report.data.currency) },
              ]
            : undefined
        }
        mapSlot={
          report.isLoading ? (
            <Skeleton height={120} />
          ) : report.isError ? (
            <EmptyState
              icon={<Bus size={20} />}
              title="Could not load this bus's report"
              description={report.error instanceof ApiError ? report.error.message : undefined}
            />
          ) : report.data ? (
            <div className={styles.childLineItems}>
              <ReportBlock
                title="Student income"
                total={formatAmount(report.data.studentIncome, report.data.currency)}
                rows={report.data.incomeByStudent.map((r) => ({
                  key: r.studentId,
                  label: r.fullName,
                  meta: `Parent: ${r.parentName}`,
                  amount: formatAmount(r.amount, report.data!.currency),
                }))}
                empty="No student payments received in this period."
              />
              <ReportBlock
                title="By parent"
                rows={report.data.incomeByParent.map((r) => ({
                  key: r.parentId,
                  label: r.fullName,
                  amount: formatAmount(r.amount, report.data!.currency),
                }))}
                empty="—"
              />
              <ReportBlock
                title="Daily income"
                total={formatAmount(report.data.dailyIncome, report.data.currency)}
                rows={report.data.dailyEntries.map((e) => ({
                  key: e.id,
                  label: e.occurredOn,
                  meta: e.description ?? undefined,
                  amount: formatAmount(e.amount, e.currency),
                }))}
                empty="No daily income recorded in this period."
              />
              <ReportBlock
                title="Other income"
                total={formatAmount(report.data.otherIncome, report.data.currency)}
                rows={report.data.otherEntries.map((e) => ({
                  key: e.id,
                  label: `${e.occurredOn} · ${e.categoryId ? categoryNames.get(e.categoryId) ?? "—" : "Uncategorised"}`,
                  meta: e.description ?? undefined,
                  amount: formatAmount(e.amount, e.currency),
                }))}
                empty="No other income recorded in this period."
              />
              <ReportBlock
                title="Expenses by category"
                total={formatAmount(report.data.totalExpenses, report.data.currency)}
                rows={Object.entries(report.data.expensesByCategory).map(([categoryId, amount]) => ({
                  key: categoryId || "uncategorised",
                  label: categoryId ? categoryNames.get(categoryId) ?? "—" : "Uncategorised",
                  amount: formatAmount(amount, report.data!.currency),
                }))}
                empty="No expenses attributed to this bus in this period."
              />
              <p className={styles.muted}>
                Billed to this bus&apos;s students in the period:{" "}
                {formatAmount(report.data.billedAmount, report.data.currency)} · still owed{" "}
                {formatAmount(report.data.outstandingAmount, report.data.currency)}.
              </p>
            </div>
          ) : null
        }
        footer={
          selected &&
          canManage && (
            <div className={styles.rowActions}>
              <Button size="sm" leadingIcon={<Plus size={13} />} onClick={() => onRecord({ mode: "income", incomeType: "daily_vehicle", vehicleId: selected })}>
                Daily income
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onRecord({ mode: "income", incomeType: "other", vehicleId: selected })}>
                Other income
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onRecord({ mode: "expense", vehicleId: selected })}>
                Expense
              </Button>
            </div>
          )
        }
      />
    </>
  );
}

function ReportBlock({
  title,
  total,
  rows,
  empty,
}: {
  title: string;
  total?: string;
  rows: { key: string; label: string; meta?: string; amount: string }[];
  empty: string;
}) {
  return (
    <section>
      <div className={styles.childLineItemRow}>
        <span className={styles.childLineItemsTitle}>{title}</span>
        {total && <span className={styles.strong}>{total}</span>}
      </div>
      {rows.length === 0 ? (
        <div className={styles.muted}>{empty}</div>
      ) : (
        rows.map((row) => (
          <div key={row.key} className={styles.childLineItemRow}>
            <div>
              <div>{row.label}</div>
              {row.meta && <div className={styles.muted}>{row.meta}</div>}
            </div>
            <span>{row.amount}</span>
          </div>
        ))
      )}
    </section>
  );
}

/** Column totals in integer cents — never summed as floats. */
function sumRows(rows: VehicleFinance[]) {
  const fields = [
    "studentIncome",
    "dailyIncome",
    "otherIncome",
    "totalIncome",
    "expenseAmount",
    "netAmount",
    "outstandingAmount",
  ] as const;
  const result = {} as Record<(typeof fields)[number], string>;
  for (const field of fields) {
    const cents = rows.reduce((sum, row) => sum + Math.round(Number(row[field]) * 100), 0);
    const sign = cents < 0 ? "-" : "";
    const abs = Math.abs(cents);
    result[field] = `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
  }
  return result;
}
