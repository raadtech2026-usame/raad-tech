import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReceiptText, Search } from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  currentPeriod,
  formatAmount,
  generateStudentInvoices,
  listFeePlans,
  listStudentsForPicker,
} from "./api";
import styles from "./forms.module.css";

/**
 * The monthly billing run: issue one invoice per selected student, against one fee plan, for one
 * period.
 *
 * **Re-running the same period is safe.** The backend skips any student who already has an
 * invoice for that period — enforced twice, by an existence check and by
 * `ux_erp_student_invoices__student_period`, because a check alone loses a race. So a partially
 * failed batch is simply re-run, and the success toast reports how many were *actually* issued
 * rather than how many were selected, which is what makes the skip visible instead of silent.
 *
 * **The cohort is chosen explicitly, never inferred.** There is no "bill everyone" shortcut: a
 * school with students who pay termly, students on scholarship and students who joined mid-month
 * would be mis-billed by one, and an invoice is hard to unsend. The transportation context each
 * invoice captures (route, bus, driver) is resolved server-side at issue time for the whole
 * cohort in one call.
 */

const LIST_PARAMS = { page: 1, pageSize: 100, sort: null, filters: {}, search: "" };

function defaultDueDate(period: string): string {
  // Last day of the billed month — the convention a monthly transport fee is due by.
  const [year, month] = period.split("-").map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export interface GenerateInvoicesFormProps {
  open: boolean;
  onClose: () => void;
  /** Period the page is showing, so the run defaults to what the operator is looking at. */
  period: string;
}

export function GenerateInvoicesForm({ open, onClose, period }: GenerateInvoicesFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [feePlanId, setFeePlanId] = useState("");
  const [billingPeriod, setBillingPeriod] = useState(period || currentPeriod());
  const [dueDate, setDueDate] = useState(() => defaultDueDate(period || currentPeriod()));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const feePlans = useQuery({
    queryKey: ["school-finance", "fee-plans", "picker"],
    queryFn: () => listFeePlans(LIST_PARAMS),
    enabled: open,
    staleTime: 60_000,
  });

  const students = useQuery({
    queryKey: ["school-finance", "students", "picker"],
    queryFn: () => listStudentsForPicker(),
    enabled: open,
    staleTime: 60_000,
  });

  const activePlans = useMemo(
    () => (feePlans.data?.data ?? []).filter((plan) => plan.status === "active"),
    [feePlans.data],
  );

  // Preselect the only active plan — with one plan there is no choice to make, and forcing the
  // operator to make it anyway is friction without a decision behind it.
  useEffect(() => {
    if (open && !feePlanId && activePlans.length === 1) {
      setFeePlanId(activePlans[0].id);
    }
  }, [open, feePlanId, activePlans]);

  useEffect(() => {
    if (open) {
      setBillingPeriod(period || currentPeriod());
      setDueDate(defaultDueDate(period || currentPeriod()));
      setSelected(new Set());
      setSearch("");
      setError(null);
    }
  }, [open, period]);

  const visibleStudents = useMemo(() => {
    const all = students.data ?? [];
    const needle = search.trim().toLowerCase();
    return needle ? all.filter((s) => s.label.toLowerCase().includes(needle)) : all;
  }, [students.data, search]);

  const selectedPlan = activePlans.find((plan) => plan.id === feePlanId);

  const mutation = useMutation({
    mutationFn: () =>
      generateStudentInvoices({
        period: billingPeriod,
        dueDate,
        feePlanId,
        studentIds: [...selected],
      }),
    onSuccess: (issued) => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      const skipped = selected.size - issued.length;
      toast.success(
        issued.length ? `${issued.length} invoice${issued.length === 1 ? "" : "s"} issued` : "Nothing to issue",
        skipped > 0
          ? `${skipped} student${skipped === 1 ? " already had" : "s already had"} an invoice for ${billingPeriod} and ${skipped === 1 ? "was" : "were"} skipped.`
          : `Billed for ${billingPeriod}. Families can now be recorded as paying.`,
      );
      onClose();
    },
    onError: (err) => {
      toast.error(
        "Could not issue invoices",
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    },
  });

  function toggle(id: string): void {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll(): void {
    setSelected((current) =>
      current.size === visibleStudents.length
        ? new Set()
        : new Set(visibleStudents.map((s) => s.id)),
    );
  }

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    if (!feePlanId) {
      setError("Choose a fee plan to bill against.");
      return;
    }
    if (selected.size === 0) {
      setError("Select at least one student.");
      return;
    }
    setError(null);
    mutation.mutate();
  }

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<ReceiptText size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Generate monthly invoices"
      subtitle="One invoice per student, for one period"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="generate-invoices-form" loading={mutation.isPending}>
            {selected.size > 0 ? `Issue ${selected.size} invoice${selected.size === 1 ? "" : "s"}` : "Issue invoices"}
          </Button>
        </>
      }
    >
      <form id="generate-invoices-form" className={styles.form} onSubmit={handleSubmit}>
        <FormField
          label="Fee plan"
          hint={
            selectedPlan
              ? `Each student is billed ${formatAmount(selectedPlan.amount, selectedPlan.currency)}${
                  Number(selectedPlan.defaultDiscountAmount) > 0
                    ? `, less a ${formatAmount(selectedPlan.defaultDiscountAmount, selectedPlan.currency)} standard discount`
                    : ""
                }.`
              : "The amount and standard discount come from the plan."
          }
          error={!feePlanId && error ? error : undefined}
        >
          <Select value={feePlanId} onChange={(event) => setFeePlanId(event.target.value)}>
            <option value="">Select a fee plan…</option>
            {activePlans.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name} — {formatAmount(plan.amount, plan.currency)}
              </option>
            ))}
          </Select>
        </FormField>

        {feePlans.isSuccess && activePlans.length === 0 && (
          <p className={styles.noticeText}>
            No active fee plan yet. Create one on the Fee plans tab first — an invoice needs an
            amount to bill.
          </p>
        )}

        <div className={styles.row}>
          <FormField label="Period" hint="The month being billed.">
            <Input
              type="month"
              value={billingPeriod}
              onChange={(event) => {
                setBillingPeriod(event.target.value);
                if (event.target.value) setDueDate(defaultDueDate(event.target.value));
              }}
            />
          </FormField>
          <FormField label="Due date">
            <Input
              type="date"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
            />
          </FormField>
        </div>

        <FormField
          label="Students"
          hint="Anyone already invoiced for this period is skipped automatically."
          error={selected.size === 0 && error ? error : undefined}
        >
          <Input
            icon={<Search size={14} />}
            placeholder="Search students…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </FormField>

        <div className={styles.pickerToolbar}>
          <Button type="button" variant="ghost" size="sm" onClick={toggleAll}>
            {selected.size === visibleStudents.length && visibleStudents.length > 0
              ? "Clear selection"
              : "Select all shown"}
          </Button>
          <span className={styles.pickerCount}>
            {selected.size} of {visibleStudents.length} selected
          </span>
        </div>

        <div className={styles.pickerList}>
          {students.isLoading ? (
            <>
              <Skeleton height={16} />
              <Skeleton height={16} />
              <Skeleton height={16} />
            </>
          ) : visibleStudents.length === 0 ? (
            <p className={styles.pickerEmpty}>
              {search ? "No student matches that search." : "No active students to bill yet."}
            </p>
          ) : (
            visibleStudents.map((student) => (
              <label key={student.id} className={styles.pickerRow}>
                <input
                  type="checkbox"
                  checked={selected.has(student.id)}
                  onChange={() => toggle(student.id)}
                />
                {student.label}
              </label>
            ))
          )}
        </div>
      </form>
    </FormDrawer>
  );
}
