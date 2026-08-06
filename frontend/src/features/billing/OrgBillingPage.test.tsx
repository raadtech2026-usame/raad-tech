import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../shared/stores/authStore";
import { OrgBillingPage } from "./OrgBillingPage";
import type { BillingProviderConfig, Invoice, Payment, Plan, Subscription } from "./api";

vi.mock("./api", () => ({
  listPlans: vi.fn(),
  listSubscriptions: vi.fn(),
  listInvoices: vi.fn(),
  listPayments: vi.fn(),
  getBillingProviderConfig: vi.fn(),
  initiatePayment: vi.fn(),
}));

vi.mock("../organizations/api", () => ({
  getOrganization: vi.fn(),
}));

vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn().mockResolvedValue({}),
}));

const mockCreatePaymentMethod = vi.fn();
// Stable references, matching real @stripe/react-stripe-js's own memoized context values —
// returning a fresh object identity per call (an earlier draft of this mock did) makes
// CardFields's `useEffect([stripe, elements, onReady])` re-run on every render, which calls
// `onReady` with a new object every time and re-triggers a render: an infinite loop that hung
// the whole test run rather than failing loudly.
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

import { getOrganization } from "../organizations/api";
import {
  getBillingProviderConfig,
  initiatePayment,
  listInvoices,
  listPayments,
  listPlans,
  listSubscriptions,
} from "./api";

function offsetPage<T>(data: T[]) {
  return { data, page: { total: data.length, page: 1, pageSize: 25 } };
}

const PLAN: Plan = {
  id: "p1",
  name: "Standard",
  billingScope: "organization",
  amount: 199.5,
  currency: "USD",
  billingCycle: "monthly",
  vehicleLimit: 10,
  status: "active",
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
};

const SUBSCRIPTION: Subscription = {
  id: "s1",
  organizationId: "org1",
  planId: "p1",
  status: "active",
  currentPeriodStart: "2026-08-01T00:00:00Z",
  currentPeriodEnd: "2026-09-01T00:00:00Z",
  autoRenew: true,
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
};

const INVOICE: Invoice = {
  id: "i1",
  organizationId: "org1",
  subscriptionId: "s1",
  number: "INV-0001",
  amount: 199.5,
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

const PAYMENT: Payment = {
  id: "pay1",
  organizationId: "org1",
  invoiceId: "i1",
  provider: "stripe",
  providerRef: "pi_123",
  amount: 199.5,
  currency: "USD",
  status: "paid",
  failureReason: null,
  createdAt: "2026-08-01T00:05:00Z",
  confirmedAt: "2026-08-01T00:05:30Z",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrgBillingPage />
    </QueryClientProvider>,
  );
}

function setOrgAdmin() {
  useAuthStore.setState({
    principal: { userId: "u1", role: "org_admin", organizationId: "org1", regionIds: [] },
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  });
}

function stripeAvailable(): BillingProviderConfig {
  return { provider: "stripe" };
}

describe("OrgBillingPage", () => {
  beforeEach(() => {
    vi.mocked(getOrganization).mockReset().mockResolvedValue({
      id: "org1",
      name: "Acme School",
      orgType: "school",
      parentOrgId: null,
      regionId: "r1",
      status: "active",
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-01T00:00:00Z",
    });
    vi.mocked(listPlans).mockReset().mockResolvedValue(offsetPage([PLAN]));
    vi.mocked(listSubscriptions).mockReset().mockResolvedValue(offsetPage([SUBSCRIPTION]));
    vi.mocked(listInvoices).mockReset().mockResolvedValue(offsetPage([INVOICE]));
    vi.mocked(listPayments).mockReset().mockResolvedValue(offsetPage([PAYMENT]));
    vi.mocked(getBillingProviderConfig).mockReset().mockResolvedValue(stripeAvailable());
    vi.mocked(initiatePayment).mockReset();
    mockCreatePaymentMethod.mockReset().mockResolvedValue({ paymentMethod: { id: "pm_123" }, error: undefined });
    setOrgAdmin();
  });

  it("shows the organization name, current plan, invoices, and payment history", async () => {
    renderPage();

    expect(await screen.findByText("Acme School")).toBeInTheDocument();
    expect(await screen.findByText("Standard")).toBeInTheDocument();
    expect(screen.getByText("INV-0001")).toBeInTheDocument();
    expect(screen.getAllByText("$199.50").length).toBeGreaterThan(0);
    await waitFor(() => expect(listPayments).toHaveBeenCalled());
  });

  it("scopes subscriptions/invoices/payments to the caller's own organization", async () => {
    renderPage();
    await screen.findByText("Acme School");

    await waitFor(() => {
      expect(listSubscriptions).toHaveBeenCalledWith(
        expect.objectContaining({ filters: { organization_id: "org1" } }),
      );
      expect(listInvoices).toHaveBeenCalledWith(
        expect.objectContaining({ filters: { subscription_id: "s1" } }),
      );
      expect(listPayments).toHaveBeenCalledWith(
        expect.objectContaining({ filters: { organization_id: "org1" } }),
      );
    });
  });

  it("shows a 'no subscription' state and never fetches invoices when none exists", async () => {
    vi.mocked(listSubscriptions).mockResolvedValue(offsetPage([]));
    renderPage();

    expect(await screen.findByText("No subscription on file yet.")).toBeInTheDocument();
    expect(listInvoices).not.toHaveBeenCalled();
  });

  it("shows 'online payment is not available yet' and disables Pay when no provider is configured", async () => {
    vi.mocked(getBillingProviderConfig).mockResolvedValue({ provider: null });
    renderPage();

    expect(await screen.findByText("Online payment is not available yet")).toBeInTheDocument();
    const payButton = await screen.findByRole("button", { name: "Pay" });
    expect(payButton).toBeDisabled();
  });

  it("completes a card payment through the Pay Invoice dialog", async () => {
    vi.mocked(initiatePayment).mockResolvedValue({ paymentId: "pay2", status: "paid" });
    const user = userEvent.setup();
    renderPage();

    const payButton = await screen.findByRole("button", { name: "Pay" });
    expect(payButton).toBeEnabled();
    await user.click(payButton);

    expect(screen.getByText("Pay invoice INV-0001")).toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: "Pay now" });
    expect(confirmButton).toBeDisabled();

    await user.type(screen.getByLabelText("Card details"), "4");
    await waitFor(() => expect(confirmButton).toBeEnabled());

    await user.click(confirmButton);

    await waitFor(() =>
      expect(initiatePayment).toHaveBeenCalledWith({
        invoiceId: "i1",
        method: "stripe",
        amount: 199.5,
        currency: "USD",
        paymentMethodToken: "pm_123",
      }),
    );
    await waitFor(() => expect(screen.queryByText("Pay invoice INV-0001")).not.toBeInTheDocument());
  });

  it("shows an empty state when the account has no organization", async () => {
    useAuthStore.setState({
      principal: { userId: "u2", role: "org_admin", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    renderPage();

    expect(await screen.findByText("No organization on this account")).toBeInTheDocument();
  });
});
