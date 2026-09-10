import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReceiptText } from "lucide-react";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { currentPeriod, formatAmount, issueStudentInvoice, listFeePlans } from "./api";
import styles from "./forms.module.css";

/**
 * The financial-setup half of registration: bill the student against an existing fee plan (the
 * ordinary case — amount and standard discount come from the plan, per
 * `_resolve_invoice_amounts`'s own "explicit amount always wins, a fee plan fills in what was
 * not supplied" rule), or an ad-hoc amount when the school has no fee plan yet.
 *
 * Optional and non-blocking by the same design `AssignStudentForm` already established for the
 * transport half of registration: closing this drawer leaves the student enrolled with no
 * invoice, exactly as billing them next month instead would.
 *
 * `issueStudentInvoice` already existed (`api.ts`) with no caller anywhere in this frontend —
 * every other invoice-issuing surface is the bulk monthly run (`GenerateInvoicesForm`). This is
 * its first single-student use.
 */

const LIST_PARAMS = { page: 1, pageSize: 100, sort: null, filters: {}, search: "" };
const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

function defaultDueDate(period: string): string {
  const [year, month] = period.split("-").map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export interface IssueInvoiceFormProps {
  open: boolean;
  onClose: () => void;
  studentId: string | null;
  studentName?: string;
}

export function IssueInvoiceForm({ open, onClose, studentId, studentName }: IssueInvoiceFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [feePlanId, setFeePlanId] = useState("");
  const [period, setPeriod] = useState(currentPeriod());
  const [dueDate, setDueDate] = useState(() => defaultDueDate(currentPeriod()));
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [error, setError] = useState<string | null>(null);

  const feePlans = useQuery({
    queryKey: ["school-finance", "fee-plans", "picker"],
    queryFn: () => listFeePlans(LIST_PARAMS),
    enabled: open,
    staleTime: 60_000,
  });
  const activePlans = (feePlans.data?.data ?? []).filter((plan) => plan.status === "active");
  const selectedPlan = activePlans.find((plan) => plan.id === feePlanId);
  const usingFeePlan = feePlanId !== "";

  useEffect(() => {
    if (open) {
      const initialPeriod = currentPeriod();
      setPeriod(initialPeriod);
      setDueDate(defaultDueDate(initialPeriod));
      setAmount("");
      setCurrency("USD");
      setError(null);
      // Preselect the only active plan — with one plan there is nothing to choose.
      setFeePlanId("");
    }
  }, [open]);

  useEffect(() => {
    if (open && !feePlanId && activePlans.length === 1) {
      setFeePlanId(activePlans[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activePlans.length]);

  const mutation = useMutation({
    mutationFn: () =>
      issueStudentInvoice({
        studentId: studentId!,
        period,
        dueDate,
        feePlanId: feePlanId || null,
        amount: usingFeePlan ? null : amount,
        currency: usingFeePlan ? null : currency.toUpperCase(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success("Invoice issued", `${studentName ?? "The student"} has been billed for ${period}.`);
      onClose();
    },
    onError: (err) => {
      toast.error(
        "Could not issue the invoice",
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    },
  });

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    if (!usingFeePlan) {
      if (!amount || !AMOUNT_PATTERN.test(amount) || Number(amount) <= 0) {
        setError("Enter a valid amount, e.g. 50.00.");
        return;
      }
      if (currency.trim().length !== 3) {
        setError("Use a 3-letter currency code.");
        return;
      }
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
      title="Set up billing"
      subtitle={studentName ? `Issue the first invoice for ${studentName}` : "Issue the first invoice"}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="issue-invoice-form" loading={mutation.isPending}>
            Issue invoice
          </Button>
        </>
      }
    >
      <form id="issue-invoice-form" className={styles.form} onSubmit={handleSubmit}>
        <FormField
          label="Fee plan"
          hint={
            selectedPlan
              ? `Bills ${formatAmount(selectedPlan.amount, selectedPlan.currency)}${
                  Number(selectedPlan.defaultDiscountAmount) > 0
                    ? `, less a ${formatAmount(selectedPlan.defaultDiscountAmount, selectedPlan.currency)} standard discount`
                    : ""
                }.`
              : "Leave unset to bill an ad-hoc amount instead."
          }
        >
          <Select value={feePlanId} onChange={(event) => setFeePlanId(event.target.value)}>
            <option value="">No fee plan — ad-hoc amount</option>
            {activePlans.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name} — {formatAmount(plan.amount, plan.currency)}
              </option>
            ))}
          </Select>
        </FormField>

        {!usingFeePlan && (
          <div className={styles.row}>
            <FormField label="Amount" error={error && !amount ? error : undefined}>
              <Input
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                inputMode="decimal"
                placeholder="50.00"
                autoFocus
              />
            </FormField>
            <FormField label="Currency">
              <Input
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
                maxLength={3}
              />
            </FormField>
          </div>
        )}

        <div className={styles.row}>
          <FormField label="Period" hint="The month being billed.">
            <Input
              type="month"
              value={period}
              onChange={(event) => {
                setPeriod(event.target.value);
                if (event.target.value) setDueDate(defaultDueDate(event.target.value));
              }}
            />
          </FormField>
          <FormField label="Due date">
            <Input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
          </FormField>
        </div>
      </form>
    </FormDrawer>
  );
}
