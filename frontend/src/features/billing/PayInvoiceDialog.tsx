import { useCallback, useEffect, useState } from "react";
import { CardElement, Elements, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { env } from "../../config/env";
import { ApiError } from "../../shared/api/types";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { useToast } from "../../shared/components/Toast/toastStore";
import { initiatePayment, type Invoice } from "./api";
import { formatAmount } from "./format";
import styles from "./OrgBillingPage.module.css";

/** Stripe's own documented guidance: call `loadStripe` once, outside any component render, not
 * on every mount — module-level, lazily created on first use (a page that never opens the "Pay
 * Invoice" dialog never loads Stripe.js at all). */
let stripePromise: Promise<Stripe | null> | null = null;
function getStripe(): Promise<Stripe | null> {
  if (!stripePromise) {
    stripePromise = loadStripe(env.stripePublishableKey);
  }
  return stripePromise;
}

const CARD_ELEMENT_OPTIONS = {
  style: {
    base: {
      fontFamily: '"Manrope", system-ui, -apple-system, sans-serif',
      fontSize: "14px",
      color: "#0e1524",
      "::placeholder": { color: "#94a3b8" },
    },
    invalid: {
      color: "#b42318",
    },
  },
};

interface CardTokenizer {
  /** Tokenizes the currently-entered card via `stripe.createPaymentMethod` and returns the
   * resulting `PaymentMethod` id — the only thing that ever reaches this app's backend (ADR-0022,
   * PCI DSS SAQ A scope: the raw card number/CVC never leave Stripe's own iframe). */
  run: () => Promise<string>;
}

interface CardFieldsProps {
  onCardChange: (complete: boolean) => void;
  onReady: (tokenizer: CardTokenizer | null) => void;
}

/** Must render inside `<Elements>` — `useStripe`/`useElements` return `null` until Stripe.js has
 * finished loading, which is why `onReady(null)` while either is unready is load-bearing, not
 * defensive filler: it's what keeps `PayInvoiceDialog`'s confirm button disabled until a real
 * tokenizer exists. */
function CardFields({ onCardChange, onReady }: CardFieldsProps) {
  const stripe = useStripe();
  const elements = useElements();

  useEffect(() => {
    if (!stripe || !elements) {
      onReady(null);
      return;
    }
    onReady({
      run: async () => {
        const cardElement = elements.getElement(CardElement);
        if (!cardElement) {
          throw new Error("Card details are required.");
        }
        const { paymentMethod, error } = await stripe.createPaymentMethod({
          type: "card",
          card: cardElement,
        });
        if (error || !paymentMethod) {
          throw new Error(error?.message ?? "Could not process card details.");
        }
        return paymentMethod.id;
      },
    });
  }, [stripe, elements, onReady]);

  return (
    <div className={styles.cardElementWrap}>
      <CardElement options={CARD_ELEMENT_OPTIONS} onChange={(event) => onCardChange(event.complete)} />
    </div>
  );
}

export interface PayInvoiceDialogProps {
  invoice: Invoice;
  onClose: () => void;
  onPaid: () => void;
}

/** ADR-0022's "Pay Invoice" flow — the one genuinely new interactive control `OrgBillingPage`
 * adds beyond read-only display. Wraps `ConfirmDialog` (a real confirm step, since charging a
 * card is this frontend's first genuinely consequential/hard-to-reverse action) around a Stripe
 * Elements card form; the dialog's own footer "Pay now" button is wired to the tokenizer
 * `CardFields` hands up via `onReady`, not `ConfirmDialog`'s `onConfirm` calling into Stripe
 * directly — `useStripe`/`useElements` only work inside the `<Elements>` tree, one level below
 * where the confirm button itself lives.
 *
 * Only ever mounted by `OrgBillingPage` after it has confirmed `billing_payment_provider` reads
 * `"stripe"` — this component assumes a bound provider and does not itself render the "not
 * available yet" fallback. */
export function PayInvoiceDialog({ invoice, onClose, onPaid }: PayInvoiceDialogProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [cardComplete, setCardComplete] = useState(false);
  const [tokenizer, setTokenizer] = useState<CardTokenizer | null>(null);

  const handleReady = useCallback((next: CardTokenizer | null) => {
    setTokenizer(next);
  }, []);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!tokenizer) {
        throw new Error("Card form is not ready yet.");
      }
      const paymentMethodToken = await tokenizer.run();
      return initiatePayment({
        invoiceId: invoice.id,
        method: "stripe",
        amount: invoice.amount,
        currency: invoice.currency,
        paymentMethodToken,
      });
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["billing", "invoices", "self"] });
      queryClient.invalidateQueries({ queryKey: ["billing", "subscriptions", "self"] });
      queryClient.invalidateQueries({ queryKey: ["billing", "payments", "self"] });
      const succeeded = result.status === "succeeded" || result.status === "paid";
      toast.success(
        succeeded ? "Payment successful" : "Payment submitted",
        succeeded
          ? `Invoice ${invoice.number} has been paid.`
          : `Invoice ${invoice.number} — payment is ${result.status}.`,
      );
      onPaid();
    },
    onError: (error) => {
      const message =
        error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Payment failed.";
      toast.error("Payment failed", message);
    },
  });

  return (
    <ConfirmDialog
      open
      title={`Pay invoice ${invoice.number}`}
      description={`Charge ${formatAmount(invoice.amount, invoice.currency)} to a card.`}
      confirmLabel="Pay now"
      loading={mutation.isPending}
      confirmDisabled={!cardComplete || !tokenizer}
      onConfirm={() => mutation.mutate()}
      onCancel={onClose}
    >
      <Elements stripe={getStripe()}>
        <CardFields onCardChange={setCardComplete} onReady={handleReady} />
      </Elements>
    </ConfirmDialog>
  );
}
