import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../../shared/stores/authStore";
import type { Organization } from "../api";
import type { Invoice, Plan, Subscription } from "../../billing/api";

vi.mock("../../billing/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../billing/api")>()),
  openOrCreateNextInvoice: vi.fn(),
  activateSubscription: vi.fn(),
  changeSubscriptionPlan: vi.fn(),
  cancelSubscription: vi.fn(),
  recordManualSubscriptionPayment: vi.fn(),
  suspendSubscription: vi.fn(),
  reactivateSubscription: vi.fn(),
  extendGracePeriod: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  orgSubscriptions: vi.fn(),
  orgSubscriptionInvoices: vi.fn(),
  orgPlanCatalog: vi.fn(),
}));

import {
  activateSubscription,
  cancelSubscription,
  changeSubscriptionPlan,
  openOrCreateNextInvoice,
  recordManualSubscriptionPayment,
} from "../../billing/api";
import { orgPlanCatalog, orgSubscriptionInvoices, orgSubscriptions } from "./api";
import { OrganizationSubscriptionPanel } from "./OrganizationSubscriptionPanel";

const ORG_ID = "org-1";
const SUBSCRIPTION_ID = "sub-1";

function offsetPage<T>(data: T[]) {
  return { data, page: { total: data.length, page: 1, pageSize: 100 } };
}

const ORGANIZATION: Organization = {
  id: ORG_ID,
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: "region-1",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  trialStartedAt: "2026-01-01T00:00:00Z",
  trialEndsAt: "2026-01-15T00:00:00Z",
  trialState: "expired",
};

const PLAN: Plan = {
  id: "plan-1",
  name: "Standard",
  billingScope: "organization",
  amount: 199.5,
  currency: "USD",
  billingCycle: "monthly",
  vehicleLimit: 10,
  deviceLimit: 20,
  userLimit: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

const OTHER_PLAN: Plan = { ...PLAN, id: "plan-2", name: "Premium", amount: 399 };

const ACTIVE_SUBSCRIPTION: Subscription = {
  id: SUBSCRIPTION_ID,
  organizationId: ORG_ID,
  planId: "plan-1",
  status: "active",
  currentPeriodStart: "2026-08-01T00:00:00Z",
  currentPeriodEnd: "2026-09-01T00:00:00Z",
  autoRenew: true,
  pastDueSince: null,
  gracePeriodEndsAt: null,
  suspendedAt: null,
  cancelledAt: null,
  expiredAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
};

const PAID_INVOICE: Invoice = {
  id: "inv-1",
  organizationId: ORG_ID,
  subscriptionId: SUBSCRIPTION_ID,
  number: "INV-0001",
  amount: 199.5,
  currency: "USD",
  periodStart: "2026-08-01",
  periodEnd: "2026-08-31",
  status: "paid",
  issuedAt: "2026-08-01T00:00:00Z",
  dueAt: "2026-08-05T00:00:00Z",
  paidAt: "2026-08-02T00:00:00Z",
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-02T00:00:00Z",
};

const UNPAID_INVOICE: Invoice = { ...PAID_INVOICE, status: "issued", paidAt: null };

function setRole(role: "founder" | "org_admin") {
  useAuthStore.setState({
    principal: { userId: "u1", role, organizationId: null, regionIds: [] } as never,
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  } as never);
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OrganizationSubscriptionPanel organizationId={ORG_ID} organization={ORGANIZATION} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The Subscription Control Center on Organization → Subscription. Every action here calls a real
 * backend endpoint (`../../billing/api.ts`) — these tests pin that the right endpoint is called
 * with the right arguments for each state-gated action, and that a caller without
 * `billing.subscriptions.manage` (an org_admin session) sees no action controls at all.
 */
describe("OrganizationSubscriptionPanel", () => {
  beforeEach(() => {
    setRole("founder");
    vi.mocked(orgPlanCatalog).mockReset().mockResolvedValue(offsetPage([PLAN, OTHER_PLAN]));
    vi.mocked(orgSubscriptions).mockReset().mockResolvedValue(offsetPage([]));
    vi.mocked(orgSubscriptionInvoices).mockReset().mockResolvedValue(offsetPage([]));
    vi.mocked(openOrCreateNextInvoice).mockReset();
    vi.mocked(activateSubscription).mockReset();
    vi.mocked(changeSubscriptionPlan).mockReset();
    vi.mocked(cancelSubscription).mockReset();
    vi.mocked(recordManualSubscriptionPayment).mockReset();
  });

  it("shows an empty state and a Create subscription action when the organization has none", async () => {
    renderPanel();

    expect(await screen.findByText("No subscription")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create subscription" })).toBeInTheDocument();
  });

  it("opens a subscription against the selected plan", async () => {
    const user = userEvent.setup();
    vi.mocked(openOrCreateNextInvoice).mockResolvedValue({ ...PAID_INVOICE, id: "inv-new" });
    renderPanel();
    await screen.findByRole("button", { name: "Create subscription" });

    await user.click(screen.getByRole("button", { name: "Create subscription" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(screen.getByLabelText("Plan"), "plan-2");
    await user.click(within(dialog).getByRole("button", { name: "Create subscription" }));

    await waitFor(() =>
      expect(openOrCreateNextInvoice).toHaveBeenCalledWith(ORG_ID, "plan-2"),
    );
  });

  it("shows the current subscription's status, plan and amount", async () => {
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    renderPanel();

    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Standard")).toBeInTheDocument();
    expect(screen.getByText("$199.50")).toBeInTheDocument();
  });

  it("offers Create invoice once a subscription exists with no unpaid invoice", async () => {
    const user = userEvent.setup();
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    vi.mocked(openOrCreateNextInvoice).mockResolvedValue({ ...PAID_INVOICE, id: "inv-new", status: "issued" });
    renderPanel();

    const button = await screen.findByRole("button", { name: "Create invoice" });
    await user.click(button);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Create invoice" }));

    await waitFor(() => expect(openOrCreateNextInvoice).toHaveBeenCalledWith(ORG_ID, "plan-1"));
  });

  it("does not offer Create invoice while an invoice is still unpaid", async () => {
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([UNPAID_INVOICE]));
    renderPanel();

    // Wait for the invoices query itself to settle (not just the always-present "Actions"
    // header) before asserting the button's absence — otherwise this passes only because the
    // gating query hasn't resolved yet, not because the gate is actually working.
    await screen.findByRole("button", { name: "Record manual payment" });
    expect(screen.queryByRole("button", { name: "Create invoice" })).not.toBeInTheDocument();
  });

  it("records a manual payment against the unpaid current invoice", async () => {
    const user = userEvent.setup();
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([UNPAID_INVOICE]));
    vi.mocked(recordManualSubscriptionPayment).mockResolvedValue({ paymentId: "pay-1", status: "paid" });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Record manual payment" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Reference/), "TXN-123");
    await user.click(within(dialog).getByRole("button", { name: "Record payment" }));

    await waitFor(() =>
      expect(recordManualSubscriptionPayment).toHaveBeenCalledWith(UNPAID_INVOICE.id, "TXN-123"),
    );
  });

  it("activates the subscription", async () => {
    const user = userEvent.setup();
    const trialSub: Subscription = { ...ACTIVE_SUBSCRIPTION, status: "trial" };
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([trialSub]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    vi.mocked(activateSubscription).mockResolvedValue({ ...trialSub, status: "active" });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Activate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(activateSubscription).toHaveBeenCalledWith(SUBSCRIPTION_ID));
  });

  it("changes the plan without affecting the current period", async () => {
    const user = userEvent.setup();
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    vi.mocked(changeSubscriptionPlan).mockResolvedValue({ ...ACTIVE_SUBSCRIPTION, planId: "plan-2" });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Change plan" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("New plan"), "plan-2");
    await user.click(within(dialog).getByRole("button", { name: "Change plan" }));

    await waitFor(() =>
      expect(changeSubscriptionPlan).toHaveBeenCalledWith(SUBSCRIPTION_ID, "plan-2"),
    );
  });

  it("cancels the subscription after confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    vi.mocked(cancelSubscription).mockResolvedValue({ ...ACTIVE_SUBSCRIPTION, status: "cancelled" });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel subscription" }));

    await waitFor(() => expect(cancelSubscription).toHaveBeenCalledWith(SUBSCRIPTION_ID));
  });

  it("hides every action from a caller without billing.subscriptions.manage", async () => {
    setRole("org_admin");
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    renderPanel();

    await screen.findByText("Active");
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows the organization's own permanent trial state, distinct from the subscription's", async () => {
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    vi.mocked(orgSubscriptionInvoices).mockResolvedValue(offsetPage([PAID_INVOICE]));
    renderPanel();

    expect(await screen.findByText("Trial expired")).toBeInTheDocument();
  });
});
