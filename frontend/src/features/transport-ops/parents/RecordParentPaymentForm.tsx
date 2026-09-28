import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleDollarSign } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormDrawer } from "../../../shared/components/Drawer/FormDrawer";
import { FormField } from "../../../shared/components/FormField/FormField";
import { Input } from "../../../shared/components/Input/Input";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { allocateProRata, fromCents, toCents } from "./allocation";
import {
  formatParentAmount,
  getParentInvoiceDetail,
  recordParentPayment,
  type PaymentMethod,
} from "./api";
import { PAYMENT_METHOD_OPTIONS } from "./labels";
import styles from "./forms.module.css";

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

export interface RecordParentPaymentFormProps {
  open: boolean;
  onClose: () => void;
  invoiceId: string | null;
  /** When set, the payment is for this one student only — the Student finance page's action. */
  onlyStudentId?: string | null;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Records a payment against one Parent Invoice (ADR-0047) — the only way money reaches an
 * invoice. The bursar enters what was received (amount, method, date, reference) and where it
 * goes: split across the students in proportion to what each still owes (the default, previewed
 * here with the server's own rounding rule), or amounts typed per student. Paying for one child
 * from their own finance page fixes the split to that child.
 *
 * A fresh idempotency key is minted every time the drawer opens, so a double-clicked Save — or
 * a retry after a timeout — records one payment, not two. The server re-validates everything:
 * a cancelled or fully paid invoice, a currency mismatch, or an allocation above a student's
 * balance is refused with the reason shown in the toast.
 */
export function RecordParentPaymentForm({ open, onClose, invoiceId, onlyStudentId }: RecordParentPaymentFormProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [receivedOn, setReceivedOn] = useState(today());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [splitMode, setSplitMode] = useState<"auto" | "manual">("auto");
  const [manual, setManual] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState("");

  const detail = useQuery({
    queryKey: ["school-finance", "parent-invoice-detail", invoiceId],
    queryFn: () => getParentInvoiceDetail(invoiceId!),
    enabled: open && invoiceId !== null,
  });
  const invoice = detail.data;
  const lines = useMemo(
    () => (invoice?.lines ?? []).filter((line) => !onlyStudentId || line.studentId === onlyStudentId),
    [invoice, onlyStudentId],
  );

  useEffect(() => {
    if (!open) return;
    setIdempotencyKey(crypto.randomUUID());
    setMethod("cash");
    setReceivedOn(today());
    setReference("");
    setNotes("");
    setSplitMode(onlyStudentId ? "manual" : "auto");
    setError(null);
    setConfirming(false);
  }, [open, invoiceId, onlyStudentId]);

  useEffect(() => {
    if (!open || !invoice) return;
    const owed = onlyStudentId ? lines[0]?.balanceDue ?? "0.00" : invoice.balanceDue;
    setAmount(owed);
    setManual(Object.fromEntries(lines.map((line) => [line.lineId, onlyStudentId ? owed : ""])));
  }, [open, invoice, lines, onlyStudentId]);

  const preview = useMemo(
    () => (AMOUNT_PATTERN.test(amount) ? allocateProRata(amount, lines) : null),
    [amount, lines],
  );

  const mutation = useMutation({
    mutationFn: () => {
      if (!invoice) return Promise.reject(new Error("No invoice selected."));
      const allocations =
        splitMode === "manual"
          ? lines
              .filter((line) => (manual[line.lineId] ?? "") !== "" && toCents(manual[line.lineId]) > 0)
              .map((line) => ({ studentId: line.studentId, amount: manual[line.lineId] }))
          : null;
      return recordParentPayment(invoice.id, {
        amount: onlyStudentId ? manual[lines[0].lineId] : amount,
        currency: invoice.currency,
        method,
        receivedOn,
        reference: reference.trim() || null,
        notes: notes.trim() || null,
        allocations,
        idempotencyKey,
      });
    },
    onSuccess: (payment) => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      queryClient.invalidateQueries({ queryKey: ["parents"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      toast.success(
        "Payment recorded",
        `${formatParentAmount(payment.amount, payment.currency)} for ${payment.period}, split: ${payment.allocations
          .map((a) => `${a.fullName} ${a.amount}`)
          .join(", ")}.`,
      );
      setConfirming(false);
      onClose();
    },
    onError: (err) => {
      toast.error(
        "Could not record the payment",
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
      setConfirming(false);
    },
  });

  function validate(): string | null {
    if (!invoice) return "The invoice is still loading.";
    if (splitMode === "manual") {
      let total = 0;
      for (const line of lines) {
        const value = manual[line.lineId] ?? "";
        if (value === "") continue;
        if (!AMOUNT_PATTERN.test(value)) return `Enter a decimal amount for ${line.fullName}, e.g. 40.00`;
        if (toCents(value) > toCents(line.balanceDue)) {
          return `${line.fullName} owes ${formatParentAmount(line.balanceDue, invoice.currency)} on this invoice — the amount cannot be higher.`;
        }
        total += toCents(value);
      }
      if (total <= 0) return "Enter an amount for at least one student.";
      if (!onlyStudentId && total !== toCents(amount)) {
        return `The student amounts add up to ${fromCents(total)} but the payment is ${amount}.`;
      }
      return null;
    }
    if (!AMOUNT_PATTERN.test(amount) || toCents(amount) <= 0) return "Enter a decimal amount greater than zero, e.g. 30.00";
    if (toCents(amount) > toCents(invoice.balanceDue)) {
      return `Only ${formatParentAmount(invoice.balanceDue, invoice.currency)} is still owed on this invoice.`;
    }
    return null;
  }

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    const problem = validate();
    setError(problem);
    if (!problem) setConfirming(true);
  }

  function handleClose(): void {
    if (mutation.isPending) return;
    onClose();
  }

  if (!open) return null;

  const payingAmount = onlyStudentId && lines[0] ? manual[lines[0].lineId] ?? "" : amount;
  const onlyStudent = onlyStudentId ? lines[0] : null;

  return (
    <>
      <FormDrawer
        open={open}
        onClose={handleClose}
        icon={<CircleDollarSign size={18} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={onlyStudent ? `Record payment for ${onlyStudent.fullName}` : "Record payment"}
        subtitle={invoice ? `${invoice.parentName} — ${invoice.period} · ${invoice.invoiceNumber}` : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={handleClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" form="record-parent-payment-form" disabled={!invoice}>
              Save payment
            </Button>
          </>
        }
      >
        {detail.isLoading || !invoice ? (
          <Skeleton height={120} />
        ) : (
          <form id="record-parent-payment-form" className={styles.form} onSubmit={handleSubmit}>
            <dl className={styles.summary}>
              <div>
                <dt>Invoice</dt>
                <dd>{formatParentAmount(invoice.amount, invoice.currency)}</dd>
              </div>
              <div>
                <dt>Paid so far</dt>
                <dd>{formatParentAmount(invoice.amountPaid, invoice.currency)}</dd>
              </div>
              <div>
                <dt>{onlyStudent ? `${onlyStudent.fullName} owes` : "Still owed"}</dt>
                <dd className={styles.emphasis}>
                  {formatParentAmount(onlyStudent ? onlyStudent.balanceDue : invoice.balanceDue, invoice.currency)}
                </dd>
              </div>
            </dl>

            {onlyStudent ? (
              <FormField label={`Amount (${invoice.currency})`} error={error ?? undefined}>
                <Input
                  inputMode="decimal"
                  value={manual[onlyStudent.lineId] ?? ""}
                  onChange={(e) => setManual({ [onlyStudent.lineId]: e.target.value })}
                  invalid={Boolean(error)}
                  aria-label={`Amount paid for ${onlyStudent.fullName}`}
                  autoFocus
                />
              </FormField>
            ) : (
              <>
                <FormField label={`Amount received (${invoice.currency})`} error={splitMode === "auto" ? error ?? undefined : undefined}>
                  <Input
                    inputMode="decimal"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    invalid={Boolean(error) && splitMode === "auto"}
                    aria-label="Amount received"
                    autoFocus
                  />
                </FormField>
                <FormField label="Split across students">
                  <div role="radiogroup" aria-label="How to split the payment" className={styles.statusRadioGroup}>
                    <label className={styles.statusRadioOption}>
                      <input
                        type="radio"
                        name="split-mode"
                        checked={splitMode === "auto"}
                        onChange={() => setSplitMode("auto")}
                      />
                      In proportion to what each owes
                    </label>
                    <label className={styles.statusRadioOption}>
                      <input
                        type="radio"
                        name="split-mode"
                        checked={splitMode === "manual"}
                        onChange={() => setSplitMode("manual")}
                      />
                      Enter per student
                    </label>
                  </div>
                </FormField>
                <div className={styles.allocationList} aria-label="Allocation per student">
                  {lines.map((line) => (
                    <div key={line.lineId} className={styles.allocationRow}>
                      <div>
                        <div className={styles.allocationName}>{line.fullName}</div>
                        <div className={styles.allocationMeta}>
                          Owes {formatParentAmount(line.balanceDue, invoice.currency)} of{" "}
                          {formatParentAmount(line.amount, invoice.currency)}
                        </div>
                      </div>
                      {splitMode === "auto" ? (
                        <span className={styles.allocationAmount}>
                          {preview?.get(line.lineId) ? formatParentAmount(preview.get(line.lineId)!, invoice.currency) : "—"}
                        </span>
                      ) : (
                        <Input
                          inputMode="decimal"
                          className={styles.allocationInput}
                          value={manual[line.lineId] ?? ""}
                          placeholder="0.00"
                          onChange={(e) => setManual({ ...manual, [line.lineId]: e.target.value })}
                          aria-label={`Amount for ${line.fullName}`}
                        />
                      )}
                    </div>
                  ))}
                </div>
                {splitMode === "manual" && error && <p className={styles.errorText} role="alert">{error}</p>}
              </>
            )}

            <div className={styles.twoColumn}>
              <FormField label="Method">
                <Select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)} aria-label="Payment method">
                  {PAYMENT_METHOD_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="Received on">
                <Input type="date" value={receivedOn} max={today()} onChange={(e) => setReceivedOn(e.target.value)} />
              </FormField>
            </div>
            <FormField label="Reference" hint="Receipt, transaction or cheque number. Optional.">
              <Input value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} />
            </FormField>
            <FormField label="Notes" hint="Optional.">
              <Input value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />
            </FormField>
          </form>
        )}
      </FormDrawer>

      <ConfirmDialog
        open={confirming}
        title="Record this payment?"
        description={
          invoice
            ? `${formatParentAmount(payingAmount || "0.00", invoice.currency)} received on ${receivedOn} will be applied to ${invoice.parentName}'s ${invoice.period} invoice.`
            : undefined
        }
        confirmLabel="Record payment"
        tone="primary"
        loading={mutation.isPending}
        onConfirm={() => mutation.mutate()}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
