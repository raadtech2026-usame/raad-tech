import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "../../shared/components/Button/Button";
import { FormDrawer } from "../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  formatAmount,
  recordStudentPayment,
  type StudentInvoice,
  type StudentPaymentMethod,
} from "./api";
import styles from "./forms.module.css";

/**
 * Record a payment a family made against one student invoice.
 *
 * **This is the step that makes school revenue accounting automatic.** Recording the payment is
 * the *only* action a bursar performs: the backend advances the invoice
 * (`issued → partially_paid → paid`) in the same transaction, and every downstream figure —
 * the Collected KPI, per-bus revenue, Profit & Loss's `student_revenue` line, and every report
 * built on them — is derived from `erp_student_payments`. Nobody creates an `Income` row for
 * transport fees, and doing so would double-count against this payment. That separation is the
 * point; see `LedgerEntryForm`'s income mode for the notice that keeps it visible to the user.
 *
 * **Partial payments are first-class**, so the amount defaults to the remaining balance rather
 * than the invoice total — the common case is "the family paid what is left" and the uncommon
 * one is a part payment, but neither is assumed: the field is editable and the backend clamps
 * the resulting balance at zero either way.
 */

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

const METHODS: { value: StudentPaymentMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "mobile_money", label: "Mobile money (EVC Plus / Zaad)" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "cheque", label: "Cheque" },
  { value: "card", label: "Card" },
  { value: "other", label: "Other" },
];

const schema = z.object({
  amount: z
    .string()
    .min(1, "Amount is required")
    .refine((value) => AMOUNT_PATTERN.test(value), {
      message: "Use a decimal amount, e.g. 50.00",
    })
    .refine((value) => Number(value) > 0, { message: "Amount must be greater than zero" }),
  method: z.enum(["cash", "bank_transfer", "mobile_money", "cheque", "card", "other"]),
  receivedOn: z.string().min(1, "Date received is required"),
  reference: z.string().max(120).optional(),
  notes: z.string().max(500).optional(),
});

type FormValues = z.infer<typeof schema>;

export interface RecordPaymentFormProps {
  open: boolean;
  onClose: () => void;
  invoice: StudentInvoice | null;
  /** Display name for the invoice's student, already resolved by the page. */
  studentLabel: string;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function RecordPaymentForm({
  open,
  onClose,
  invoice,
  studentLabel,
}: RecordPaymentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { amount: "", method: "cash", receivedOn: today() },
  });

  // Re-seed whenever a different invoice is opened: the default amount is *that* invoice's
  // remaining balance, so carrying the previous one over would pre-fill a wrong figure into a
  // financial form.
  useEffect(() => {
    if (open && invoice) {
      reset({
        amount: invoice.balanceDue,
        method: "cash",
        receivedOn: today(),
        reference: "",
        notes: "",
      });
    }
  }, [open, invoice, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!invoice) return Promise.reject(new Error("No invoice selected."));
      return recordStudentPayment(invoice.id, {
        amount: values.amount,
        currency: invoice.currency,
        method: values.method,
        receivedOn: values.receivedOn,
        reference: values.reference || null,
        notes: values.notes || null,
      });
    },
    onSuccess: (payment) => {
      // Everything derived from payments moves at once — the KPI row, per-bus revenue, the
      // P&L and both ledgers — so the whole school-finance cache is invalidated rather than
      // one list, which would leave the page internally inconsistent.
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success(
        "Payment recorded",
        `${formatAmount(payment.amount, payment.currency)} received from ${studentLabel}. Revenue, reports and per-bus totals are updated.`,
      );
      onClose();
    },
    onError: (error) => {
      toast.error(
        "Could not record the payment",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  if (!invoice) return null;

  return (
    <FormDrawer
      open={open}
      onClose={handleClose}
      icon={<Wallet size={18} />}
      iconTint="var(--color-brand-primary-tint)"
      iconColor="var(--color-brand-primary)"
      title="Record payment"
      subtitle={`${studentLabel} · ${invoice.period}`}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="record-payment-form"
            loading={mutation.isPending}
          >
            Record payment
          </Button>
        </>
      }
    >
      <form
        id="record-payment-form"
        className={styles.form}
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
      >
        <dl className={styles.summary}>
          <div>
            <dt>Invoiced</dt>
            <dd>{formatAmount(invoice.netAmount, invoice.currency)}</dd>
          </div>
          <div>
            <dt>Already paid</dt>
            <dd>{formatAmount(invoice.amountPaid, invoice.currency)}</dd>
          </div>
          <div>
            <dt>Balance due</dt>
            <dd className={styles.emphasis}>
              {formatAmount(invoice.balanceDue, invoice.currency)}
            </dd>
          </div>
        </dl>

        <FormField
          label={`Amount received (${invoice.currency})`}
          hint="Defaults to the full remaining balance. Enter less for a part payment."
          error={errors.amount?.message}
        >
          <Input
            {...register("amount")}
            inputMode="decimal"
            placeholder="50.00"
            invalid={Boolean(errors.amount)}
            autoFocus
          />
        </FormField>

        <FormField label="Method" error={errors.method?.message}>
          <Select {...register("method")}>
            {METHODS.map((method) => (
              <option key={method.value} value={method.value}>
                {method.label}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Date received" error={errors.receivedOn?.message}>
          <Input type="date" {...register("receivedOn")} invalid={Boolean(errors.receivedOn)} />
        </FormField>

        <FormField
          label="Reference"
          hint="Receipt number or mobile-money transaction id. Optional."
          error={errors.reference?.message}
        >
          <Input {...register("reference")} placeholder="EVC-8842193" />
        </FormField>

        <FormField label="Notes" error={errors.notes?.message}>
          <Input {...register("notes")} placeholder="Optional" />
        </FormField>
      </form>
    </FormDrawer>
  );
}
