import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { cancelParentInvoice, formatParentAmount, voidParentPayment, type ParentPayment } from "./api";
import { paymentMethodLabel } from "./labels";
import styles from "./ledger.module.css";

/**
 * The ADR-0047 payment ledger's shared pieces — a payment history list, the void dialog and the
 * cancel-invoice dialog — used by the Parents page, the Finance page's invoice drawer and the
 * Student finance section, so all three show and correct payments identically.
 *
 * Voiding and cancelling both remove money from the books, so both require a reason (the P0.4
 * rule), which the server stores and the list shows on the voided row.
 */

function invalidateFinance(queryClient: ReturnType<typeof useQueryClient>): void {
  queryClient.invalidateQueries({ queryKey: ["school-finance"] });
  queryClient.invalidateQueries({ queryKey: ["parents"] });
  queryClient.invalidateQueries({ queryKey: ["reports"] });
}

export function PaymentHistoryList({
  payments,
  canManage,
  onVoid,
  showInvoice = true,
  emptyLabel = "No payments recorded yet.",
}: {
  payments: ParentPayment[];
  canManage: boolean;
  onVoid: (payment: ParentPayment) => void;
  showInvoice?: boolean;
  emptyLabel?: string;
}) {
  if (payments.length === 0) {
    return <span className={styles.empty}>{emptyLabel}</span>;
  }
  return (
    <ul className={styles.list} aria-label="Payments">
      {payments.map((payment) => (
        <li key={payment.id} className={payment.isVoided ? styles.voided : undefined}>
          <div className={styles.main}>
            <div className={styles.title}>
              {formatParentAmount(payment.amount, payment.currency)} · {paymentMethodLabel(payment.method)}
            </div>
            <div className={styles.meta}>
              Received {payment.receivedOn}
              {showInvoice ? ` · ${payment.period} (${payment.invoiceNumber})` : ""}
              {payment.reference ? ` · Ref ${payment.reference}` : ""}
            </div>
            <div className={styles.meta}>
              {payment.allocations.map((a) => `${a.fullName} ${a.amount}`).join(" · ")}
            </div>
            {payment.isVoided && (
              <div className={styles.meta}>Voided — {payment.voidedReason ?? "no reason recorded"}</div>
            )}
          </div>
          <div className={styles.side}>
            <Badge variant={payment.isVoided ? "danger" : "success"} dot>
              {payment.isVoided ? "Voided" : "Recorded"}
            </Badge>
            {canManage && !payment.isVoided && (
              <Button size="sm" variant="ghost" onClick={() => onVoid(payment)}>
                Void
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function VoidPaymentDialog({ payment, onClose }: { payment: ParentPayment | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (payment) setReason("");
  }, [payment]);

  const mutation = useMutation({
    mutationFn: () => voidParentPayment(payment!.id, reason.trim()),
    onSuccess: () => {
      invalidateFinance(queryClient);
      toast.success("Payment voided", "It stays on record as voided and its amount is back on the students' balances.");
      onClose();
    },
    onError: (error) => {
      toast.error("Could not void the payment", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  return (
    <ConfirmDialog
      open={payment !== null}
      title="Void this payment?"
      description={
        payment
          ? `${formatParentAmount(payment.amount, payment.currency)} received on ${payment.receivedOn} will be reversed on the ${payment.period} invoice. The payment stays on record as voided.`
          : undefined
      }
      confirmLabel="Void payment"
      tone="danger"
      loading={mutation.isPending}
      confirmDisabled={reason.trim() === ""}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <FormField label="Reason" hint="Required. Kept on the voided payment for the audit record.">
        <Input
          value={reason}
          maxLength={255}
          placeholder="e.g. Cheque bounced"
          onChange={(event) => setReason(event.target.value)}
          aria-label="Reason for voiding"
        />
      </FormField>
    </ConfirmDialog>
  );
}

export interface CancellableInvoice {
  id: string;
  invoiceNumber: string;
  parentName: string;
  period: string;
}

export function CancelInvoiceDialog({ invoice, onClose }: { invoice: CancellableInvoice | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (invoice) setReason("");
  }, [invoice]);

  const mutation = useMutation({
    mutationFn: () => cancelParentInvoice(invoice!.id, reason.trim()),
    onSuccess: () => {
      invalidateFinance(queryClient);
      toast.success("Invoice cancelled", "It no longer counts toward billing or receivables. The period can be billed again.");
      onClose();
    },
    onError: (error) => {
      toast.error("Could not cancel the invoice", error instanceof ApiError ? error.message : "Please try again.");
    },
  });

  return (
    <ConfirmDialog
      open={invoice !== null}
      title="Cancel this invoice?"
      description={
        invoice
          ? `${invoice.parentName}'s ${invoice.period} invoice (${invoice.invoiceNumber}) will stop counting toward billing and receivables. An invoice with live payments cannot be cancelled — void them first.`
          : undefined
      }
      confirmLabel="Cancel invoice"
      tone="danger"
      loading={mutation.isPending}
      confirmDisabled={reason.trim() === ""}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <FormField label="Reason" hint="Required. Kept on the invoice's audit record.">
        <Input
          value={reason}
          maxLength={255}
          placeholder="e.g. Family withdrew before the month started"
          onChange={(event) => setReason(event.target.value)}
          aria-label="Reason for cancelling"
        />
      </FormField>
    </ConfirmDialog>
  );
}
