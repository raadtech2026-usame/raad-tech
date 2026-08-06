import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PayInvoiceDialog } from "./PayInvoiceDialog";
import type { Invoice } from "./api";

vi.mock("./api", () => ({
  initiatePayment: vi.fn(),
}));

vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn().mockResolvedValue({}),
}));

const mockCreatePaymentMethod = vi.fn();
// Stable references — see OrgBillingPage.test.tsx's identical comment for why an unstable mock
// here causes an infinite render loop instead of a clean test failure.
const mockStripe = { createPaymentMethod: mockCreatePaymentMethod };
const mockElements = { getElement: () => ({}) };
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardElement: ({ onChange }: { onChange?: (event: { complete: boolean }) => void }) => (
    <input aria-label="Card details" onChange={() => onChange?.({ complete: true })} />
  ),
  useStripe: () => mockStripe,
  useElements: () => mockElements,
}));

import { initiatePayment } from "./api";

const INVOICE: Invoice = {
  id: "i1",
  organizationId: "org1",
  subscriptionId: "s1",
  number: "INV-0001",
  amount: 49,
  currency: "USD",
  periodStart: "2026-08-01",
  periodEnd: "2026-08-31",
  status: "issued",
  issuedAt: "2026-08-01T00:00:00Z",
  dueAt: "2026-08-15T00:00:00Z",
  paidAt: null,
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
};

function renderDialog(onClose = vi.fn(), onPaid = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onClose,
    onPaid,
    ...render(
      <QueryClientProvider client={queryClient}>
        <PayInvoiceDialog invoice={INVOICE} onClose={onClose} onPaid={onPaid} />
      </QueryClientProvider>,
    ),
  };
}

describe("PayInvoiceDialog", () => {
  beforeEach(() => {
    mockCreatePaymentMethod.mockReset().mockResolvedValue({ paymentMethod: { id: "pm_1" }, error: undefined });
    vi.mocked(initiatePayment).mockReset();
  });

  it("shows the invoice number/amount and keeps Pay now disabled until the card is complete", () => {
    renderDialog();

    expect(screen.getByText("Pay invoice INV-0001")).toBeInTheDocument();
    expect(screen.getByText("Charge $49.00 to a card.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay now" })).toBeDisabled();
  });

  it("tokenizes the card and calls initiatePayment with the resulting token", async () => {
    vi.mocked(initiatePayment).mockResolvedValue({ paymentId: "pay1", status: "paid" });
    const user = userEvent.setup();
    const { onPaid } = renderDialog();

    await user.type(screen.getByLabelText("Card details"), "4");
    const confirmButton = screen.getByRole("button", { name: "Pay now" });
    await waitFor(() => expect(confirmButton).toBeEnabled());

    await user.click(confirmButton);

    await waitFor(() =>
      expect(initiatePayment).toHaveBeenCalledWith({
        invoiceId: "i1",
        method: "stripe",
        amount: 49,
        currency: "USD",
        paymentMethodToken: "pm_1",
      }),
    );
    await waitFor(() => expect(onPaid).toHaveBeenCalledTimes(1));
  });

  it("surfaces a Stripe tokenization error without calling initiatePayment", async () => {
    mockCreatePaymentMethod.mockResolvedValue({ paymentMethod: undefined, error: { message: "Your card was declined." } });
    const user = userEvent.setup();
    const { onPaid } = renderDialog();

    await user.type(screen.getByLabelText("Card details"), "4");
    const confirmButton = await screen.findByRole("button", { name: "Pay now" });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    await user.click(confirmButton);

    await waitFor(() => expect(mockCreatePaymentMethod).toHaveBeenCalled());
    expect(initiatePayment).not.toHaveBeenCalled();
    expect(onPaid).not.toHaveBeenCalled();
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
