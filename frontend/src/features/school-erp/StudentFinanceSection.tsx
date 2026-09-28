import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { RecordParentPaymentForm } from "../transport-ops/parents/RecordParentPaymentForm";
import { setStudentBillingFee } from "../transport-ops/parents/api";
import { invoiceStatusLabel, invoiceStatusTone, paymentMethodLabel } from "../transport-ops/parents/labels";
import { formatAmount, getStudentFinance, voidStudentPayment, type StudentCharge, type StudentPayment } from "./api";
import styles from "./StudentFinanceSection.module.css";

/**
 * A student's own financial history (ADR-0047 §2), shown in the Students page's detail drawer:
 * what they were charged each period (their line on the family's Parent Invoice), the part of
 * each family payment that paid for them, and their balance. "Record payment" pays for this
 * student only; the family's Parent Invoice and the parent's totals move by the same amount,
 * because they are the same record read at the family's grain.
 *
 * Invoices from before Parent billing (2026-09-11) are listed read-only under "Earlier
 * per-student invoices". Their money is already inside the Parent Invoices copied from them, so
 * they never add to this student's totals; a mistaken payment on one can still be voided.
 *
 * The student's own **monthly fee** (ADR-0048) is shown first: it is what this student's line
 * on the family's next invoice will charge. `canSetFee` gates changing it — the server grant is
 * `school_erp.parent_billing_profiles.manage`, which only the Org Admin holds.
 */
const FEE_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;

export function StudentFinanceSection({
  studentId,
  canManage,
  canSetFee = canManage,
}: {
  studentId: string;
  canManage: boolean;
  canSetFee?: boolean;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [paying, setPaying] = useState<StudentCharge | null>(null);
  const [voidingLegacy, setVoidingLegacy] = useState<StudentPayment | null>(null);
  const [reason, setReason] = useState("");
  const [editingFee, setEditingFee] = useState(false);
  const [feeAmount, setFeeAmount] = useState("");
  const [feeCurrency, setFeeCurrency] = useState("USD");

  const finance = useQuery({
    queryKey: ["school-finance", "student-finance", studentId],
    queryFn: () => getStudentFinance(studentId),
  });

  const voidLegacy = useMutation({
    mutationFn: () => voidStudentPayment(voidingLegacy!.id, reason.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance"] });
      toast.success("Payment voided", "The earlier per-student payment stays on record as voided.");
      setVoidingLegacy(null);
      setReason("");
    },
    onError: (error) =>
      toast.error("Could not void the payment", error instanceof ApiError ? error.message : "Please try again."),
  });

  const saveFee = useMutation({
    mutationFn: () => setStudentBillingFee(studentId, { monthlyFee: feeAmount.trim(), currency: feeCurrency }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["school-finance", "student-finance", studentId] });
      queryClient.invalidateQueries({ queryKey: ["parents", "family-fees"] });
      toast.success("Monthly fee saved", "The next generated invoice uses it. Invoices already generated are unchanged.");
      setEditingFee(false);
    },
    onError: (error) =>
      toast.error("Could not save the fee", error instanceof ApiError ? error.message : "Please try again."),
  });

  const data = finance.data;

  function openFeeEditor(): void {
    setFeeAmount(data?.monthlyFee ?? "");
    setFeeCurrency(data?.monthlyFeeCurrency ?? data?.currency ?? "USD");
    setEditingFee(true);
  }

  return (
    <div className={styles.section}>
      <span className={styles.title}>Finance</span>
      {finance.isLoading && <Skeleton height={60} />}
      {finance.isError && (
        <span className={styles.muted}>
          {finance.error instanceof ApiError ? finance.error.message : "Could not load this student's finance."}
        </span>
      )}
      {data && (
        <>
          <dl className={styles.totals}>
            <div>
              <dt>Charged</dt>
              <dd>{formatAmount(data.totalCharged, data.currency)}</dd>
            </div>
            <div>
              <dt>Paid</dt>
              <dd>{formatAmount(data.totalPaid, data.currency)}</dd>
            </div>
            <div>
              <dt>Balance</dt>
              <dd className={data.balanceDue !== "0.00" ? styles.owes : undefined}>
                {formatAmount(data.balanceDue, data.currency)}
              </dd>
            </div>
          </dl>
          {data.parents.length > 0 && (
            <span className={styles.muted}>Billed to {data.parents.map((p) => p.fullName).join(", ")}</span>
          )}

          <div className={styles.feeRow}>
            <div>
              <div className={styles.strong}>
                Monthly fee:{" "}
                {data.monthlyFee == null
                  ? "not set"
                  : formatAmount(data.monthlyFee, data.monthlyFeeCurrency ?? data.currency)}
              </div>
              <div className={styles.muted}>
                {data.monthlyFee == null
                  ? "Not invoiced until a fee is set."
                  : data.monthlyFee === "0.00"
                    ? "Rides free — no line on the family's invoice."
                    : "This student's own line on each monthly family invoice."}
              </div>
            </div>
            {canSetFee && (
              <Button size="sm" variant="ghost" onClick={openFeeEditor}>
                {data.monthlyFee == null ? "Set fee" : "Change fee"}
              </Button>
            )}
          </div>

          <span className={styles.subtitle}>Charges</span>
          {data.charges.length === 0 ? (
            <span className={styles.muted}>No charges yet — this student has not been on a Parent Invoice.</span>
          ) : (
            <ul className={styles.list} aria-label="Charges">
              {data.charges.map((charge) => (
                <li key={charge.lineId}>
                  <div>
                    <div className={styles.strong}>
                      {charge.period} · {formatAmount(charge.amount, charge.currency)}
                    </div>
                    <div className={styles.muted}>
                      Paid {formatAmount(charge.amountPaid, charge.currency)} · Owes{" "}
                      {formatAmount(charge.balanceDue, charge.currency)} · {charge.invoiceNumber}
                    </div>
                  </div>
                  <div className={styles.side}>
                    <Badge variant={invoiceStatusTone(charge.invoiceStatus)} dot>
                      {invoiceStatusLabel(charge.invoiceStatus)}
                    </Badge>
                    {canManage && charge.invoiceStatus !== "cancelled" && charge.balanceDue !== "0.00" && (
                      <Button size="sm" variant="ghost" leadingIcon={<Wallet size={13} />} onClick={() => setPaying(charge)}>
                        Record payment
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <span className={styles.subtitle}>Payments</span>
          {data.payments.length === 0 ? (
            <span className={styles.muted}>No payments recorded for this student.</span>
          ) : (
            <ul className={styles.list} aria-label="Student payments">
              {data.payments.map((payment) => (
                <li key={payment.paymentId} className={payment.isVoided ? styles.voided : undefined}>
                  <div>
                    <div className={styles.strong}>
                      {formatAmount(payment.amount, payment.currency)} · {paymentMethodLabel(payment.method)}
                    </div>
                    <div className={styles.muted}>
                      Received {payment.receivedOn} · {payment.period}
                      {payment.reference ? ` · Ref ${payment.reference}` : ""}
                      {payment.amount !== payment.paymentTotal
                        ? ` · part of a ${formatAmount(payment.paymentTotal, payment.currency)} family payment`
                        : ""}
                    </div>
                    {payment.isVoided && <div className={styles.muted}>Voided — {payment.voidedReason}</div>}
                  </div>
                  <Badge variant={payment.isVoided ? "danger" : "success"} dot>
                    {payment.isVoided ? "Voided" : "Recorded"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}

          {(data.legacyInvoices.length > 0 || data.legacyPayments.length > 0) && (
            <>
              <span className={styles.subtitle}>Earlier per-student invoices (before 2026-09-11)</span>
              <span className={styles.muted}>
                Read-only history. Already included in the Parent Invoices created from them — not added to the
                totals above.
              </span>
              <ul className={styles.list} aria-label="Earlier per-student invoices">
                {data.legacyInvoices.map((invoice) => (
                  <li key={invoice.id}>
                    <div>
                      <div className={styles.strong}>
                        {invoice.period} · {formatAmount(invoice.netAmount, invoice.currency)}
                      </div>
                      <div className={styles.muted}>
                        Paid {formatAmount(invoice.amountPaid, invoice.currency)} · {invoice.status.replace(/_/g, " ")}
                      </div>
                    </div>
                  </li>
                ))}
                {data.legacyPayments.map((payment) => (
                  <li key={payment.id} className={payment.isVoided ? styles.voided : undefined}>
                    <div>
                      <div className={styles.strong}>
                        Payment {formatAmount(payment.amount, payment.currency)} · {payment.receivedOn}
                      </div>
                      {payment.isVoided && <div className={styles.muted}>Voided — {payment.voidedReason}</div>}
                    </div>
                    {canManage && !payment.isVoided && (
                      <Button size="sm" variant="ghost" onClick={() => setVoidingLegacy(payment)}>
                        Void
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      <RecordParentPaymentForm
        open={paying !== null}
        onClose={() => setPaying(null)}
        invoiceId={paying?.invoiceId ?? null}
        onlyStudentId={studentId}
      />
      <ConfirmDialog
        open={editingFee}
        title={`Monthly fee for ${data?.fullName ?? "this student"}`}
        description="Applies from the next generated invoice. Invoices already generated keep their amounts."
        confirmLabel="Save fee"
        loading={saveFee.isPending}
        confirmDisabled={!FEE_PATTERN.test(feeAmount.trim())}
        onConfirm={() => saveFee.mutate()}
        onCancel={() => setEditingFee(false)}
      >
        <FormField label="Monthly fee" hint="0.00 if the student rides free.">
          <Input
            value={feeAmount}
            inputMode="decimal"
            placeholder="20.00"
            onChange={(e) => setFeeAmount(e.target.value)}
            aria-label="Monthly fee amount"
          />
        </FormField>
        <FormField label="Currency" hint="Must match the family's billing currency.">
          <Select value={feeCurrency} onChange={(e) => setFeeCurrency(e.target.value)} aria-label="Fee currency">
            <option value="USD">USD</option>
            <option value="SOS">SOS</option>
            <option value="KES">KES</option>
          </Select>
        </FormField>
      </ConfirmDialog>
      <ConfirmDialog
        open={voidingLegacy !== null}
        title="Void this earlier payment?"
        description="It stays on record as voided."
        confirmLabel="Void payment"
        tone="danger"
        loading={voidLegacy.isPending}
        confirmDisabled={reason.trim() === ""}
        onConfirm={() => voidLegacy.mutate()}
        onCancel={() => {
          setVoidingLegacy(null);
          setReason("");
        }}
      >
        <FormField label="Reason" hint="Required. Kept on the voided payment for the audit record.">
          <Input value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} aria-label="Reason for voiding" />
        </FormField>
      </ConfirmDialog>
    </div>
  );
}
