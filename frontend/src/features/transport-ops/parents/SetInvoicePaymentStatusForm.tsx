import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleDollarSign } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  formatParentAmount,
  setParentInvoicePaymentStatus,
  type ParentInvoiceStatus,
  type ParentInvoiceSummary,
} from "./api";
import styles from "./forms.module.css";

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

const STATUS_OPTIONS: { value: "unpaid" | "partial" | "paid"; label: string }[] = [
  { value: "unpaid", label: "Unpaid" },
  { value: "partial", label: "Partial" },
  { value: "paid", label: "Paid" },
];

export interface SetInvoicePaymentStatusFormProps {
  open: boolean;
  onClose: () => void;
  invoice: ParentInvoiceSummary | null;
}

/**
 * `PATCH /school-finance/parent-invoices/{id}/payment-status` — the directive's Part 9 payment
 * workflow, and the *only* payment surface this app has: a status control directly on the Parent
 * Invoice (Unpaid / Partial / Paid), an amount field that appears only for Partial, and a
 * confirmation step before saving a change. No payment method, reference, or history — the
 * backend recalculates amount paid, balance, Receivables and Collected on save.
 */
export function SetInvoicePaymentStatusForm({ open, onClose, invoice }: SetInvoicePaymentStatusFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"unpaid" | "partial" | "paid">("unpaid");
  const [amountPaid, setAmountPaid] = useState("");
  const [amountError, setAmountError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (open && invoice) {
      const initial = invoice.status === "cancelled" ? "unpaid" : (invoice.status as "unpaid" | "partial" | "paid");
      setStatus(initial);
      setAmountPaid(invoice.status === "partial" ? invoice.amountPaid : "");
      setAmountError(null);
      setConfirming(false);
    }
  }, [open, invoice]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!invoice) return Promise.reject(new Error("No invoice selected."));
      return setParentInvoicePaymentStatus(invoice.id, {
        status: status as ParentInvoiceStatus,
        amountPaid: status === "partial" ? amountPaid : null,
      });
    },
    onSuccess: (updated) => {
      // Everything derived from an invoice's payment status moves at once: this family's own
      // views, and every org-wide school-finance view (Financial Overview, Receivables,
      // Vehicle Financial Overview, P&L, reports) — invalidate both.
      queryClient.invalidateQueries({ queryKey: ["parents", "financial-summary", invoice?.parentId] });
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      toast.success(
        "Payment status updated",
        `${invoice?.parentName ?? "This family"}'s ${invoice?.period ?? ""} invoice is now ${statusLabel(
          updated.status,
        )}.`,
      );
      setConfirming(false);
      onClose();
    },
    onError: (error) => {
      toast.error(
        "Could not update payment status",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
      setConfirming(false);
    },
  });

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    if (!invoice) return;
    if (status === "partial") {
      if (!AMOUNT_PATTERN.test(amountPaid) || Number(amountPaid) <= 0) {
        setAmountError("Enter a decimal amount greater than zero, e.g. 30.00");
        return;
      }
      if (Number(amountPaid) >= Number(invoice.amount)) {
        setAmountError(`Must be less than the invoice total (${formatParentAmount(invoice.amount, invoice.currency)}). Use "Paid" instead.`);
        return;
      }
    }
    setAmountError(null);
    // The directive's own confirmation requirement: before changing a previously unpaid/partial
    // invoice to Paid, or recording a partial amount, show a simple confirmation. A no-op save
    // (status unchanged) skips it — nothing to confirm.
    if (status !== invoice.status) {
      setConfirming(true);
      return;
    }
    mutation.mutate();
  }

  if (!open || !invoice) return null;

  const resolvedAmount = status === "paid" ? invoice.amount : status === "unpaid" ? "0.00" : amountPaid || "0.00";

  return (
    <>
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<CircleDollarSign size={18} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title="Payment status"
        subtitle={`${invoice.parentName} — ${invoice.period}`}
        footer={
          <>
            <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" form="set-invoice-payment-status-form" loading={mutation.isPending && !confirming}>
              Save
            </Button>
          </>
        }
      >
        <form id="set-invoice-payment-status-form" className={styles.form} onSubmit={handleSubmit}>
          <dl className={styles.summary}>
            <div>
              <dt>Invoice</dt>
              <dd>{formatParentAmount(invoice.amount, invoice.currency)}</dd>
            </div>
          </dl>

          <FormField label="Status">
            <div role="radiogroup" aria-label="Payment status" className={styles.statusRadioGroup}>
              {STATUS_OPTIONS.map((option) => (
                <label key={option.value} className={styles.statusRadioOption}>
                  <input
                    type="radio"
                    name="payment-status"
                    value={option.value}
                    checked={status === option.value}
                    onChange={() => setStatus(option.value)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </FormField>

          {status === "partial" ? (
            <FormField label={`Amount paid (${invoice.currency})`} error={amountError ?? undefined}>
              <Input
                inputMode="decimal"
                placeholder="30.00"
                value={amountPaid}
                onChange={(event) => setAmountPaid(event.target.value)}
                invalid={Boolean(amountError)}
                autoFocus
              />
            </FormField>
          ) : null}

          <dl className={styles.summary}>
            <div>
              <dt>Amount paid</dt>
              <dd>{formatParentAmount(resolvedAmount, invoice.currency)}</dd>
            </div>
            <div>
              <dt>Balance</dt>
              <dd className={styles.emphasis}>
                {formatParentAmount(
                  (Number(invoice.amount) - Number(resolvedAmount)).toFixed(2),
                  invoice.currency,
                )}
              </dd>
            </div>
          </dl>
        </form>
      </FormDrawer>

      <ConfirmDialog
        open={confirming}
        title="Confirm payment status"
        description={`Set ${invoice.parentName}'s ${invoice.period} invoice to "${statusLabel(status)}"${
          status === "partial" ? ` with ${formatParentAmount(amountPaid, invoice.currency)} paid` : ""
        }?`}
        confirmLabel="Confirm & Save"
        tone="primary"
        loading={mutation.isPending}
        onConfirm={() => mutation.mutate()}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}

function statusLabel(status: string): string {
  switch (status) {
    case "unpaid":
      return "Unpaid";
    case "partial":
      return "Partial";
    case "paid":
      return "Paid";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}
