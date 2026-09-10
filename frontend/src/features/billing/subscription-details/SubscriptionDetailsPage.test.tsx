import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../../shared/stores/authStore";
import type { Organization } from "../../organizations/api";
import type { AuditEntry } from "../../platform-analytics/api";
import type { Invoice, Payment, Plan, Subscription } from "../api";
import { SubscriptionDetailsPage } from "./SubscriptionDetailsPage";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getSubscription: vi.fn(),
  listPlans: vi.fn(),
  listInvoices: vi.fn(),
  listPayments: vi.fn(),
}));
vi.mock("../../organizations/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../organizations/api")>()),
  getOrganization: vi.fn(),
}));
vi.mock("../../platform-analytics/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../platform-analytics/api")>()),
  listAuditEntries: vi.fn(),
}));

import { getOrganization } from "../../organizations/api";
import { listAuditEntries } from "../../platform-analytics/api";
import { getSubscription, listInvoices, listPayments, listPlans } from "../api";

const SUBSCRIPTION_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const ORG_ID = "org-1";

function offsetPage<T>(data: T[]) {
  return { data, page: { total: data.length, page: 1, pageSize: 100 } };
}

const SUBSCRIPTION: Subscription = {
  id: SUBSCRIPTION_ID,
  organizationId: ORG_ID,
  planId: "plan-1",
  status: "grace_period",
  currentPeriodStart: "2026-08-01T00:00:00Z",
  currentPeriodEnd: "2026-09-01T00:00:00Z",
  autoRenew: true,
  pastDueSince: "2026-09-01T00:00:00Z",
  gracePeriodEndsAt: "2026-09-15T00:00:00Z",
  suspendedAt: null,
  cancelledAt: null,
  expiredAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
};

const ORGANIZATION: Organization = {
  id: ORG_ID,
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: "region-1",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
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

const INVOICE: Invoice = {
  id: "inv-1",
  organizationId: ORG_ID,
  subscriptionId: SUBSCRIPTION_ID,
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
  id: "pay-1",
  organizationId: ORG_ID,
  invoiceId: "inv-1",
  provider: "stripe",
  providerRef: null,
  amount: 199.5,
  currency: "USD",
  status: "paid",
  failureReason: null,
  createdAt: "2026-08-05T00:00:00Z",
  confirmedAt: "2026-08-05T00:05:00Z",
};

const GRACE_EVENT: AuditEntry = {
  id: "audit-1",
  organizationId: ORG_ID,
  actorUserId: "user-1",
  action: "SubscriptionGracePeriodExtended",
  entityType: "Subscription",
  entityId: SUBSCRIPTION_ID,
  metadata: { grace_period_ends_at: "2026-09-15T00:00:00Z" },
  createdAt: "2026-09-02T00:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/platform/billing/subscriptions/${SUBSCRIPTION_ID}`]}>
        <Routes>
          <Route
            path="/platform/billing/subscriptions/:subscriptionId"
            element={<SubscriptionDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setRole(role: "founder" | "regional_manager") {
  useAuthStore.setState({
    principal: { userId: "u1", role, organizationId: null, regionIds: [] },
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  });
}

describe("SubscriptionDetailsPage", () => {
  beforeEach(() => {
    vi.mocked(getSubscription).mockReset().mockResolvedValue(SUBSCRIPTION);
    vi.mocked(getOrganization).mockReset().mockResolvedValue(ORGANIZATION);
    vi.mocked(listPlans).mockReset().mockResolvedValue(offsetPage([PLAN]));
    vi.mocked(listInvoices).mockReset().mockResolvedValue(offsetPage([INVOICE]));
    vi.mocked(listPayments).mockReset().mockResolvedValue(offsetPage([PAYMENT]));
    vi.mocked(listAuditEntries).mockReset().mockResolvedValue(offsetPage([GRACE_EVENT]));
  });

  it("shows the organization, plan and status, and explains why it is in grace period", async () => {
    setRole("founder");
    renderPage();

    expect(await screen.findByText("Green Valley School")).toBeInTheDocument();
    expect(screen.getAllByText("Grace period").length).toBeGreaterThan(0);
    expect(
      await screen.findByText(/platform admin explicitly extended access until/i),
    ).toBeInTheDocument();
  });

  it("shows the Overview facts by default, including the resolved plan and organization link", async () => {
    setRole("founder");
    renderPage();

    await screen.findByText("Green Valley School");
    // "Standard" and "Current plan" each appear twice — once in the stat row, once in the
    // Overview facts list — so this only asserts presence, not a single match.
    expect(screen.getAllByText(/Standard/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Current plan").length).toBeGreaterThan(0);
    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("switches to Invoices and shows the current invoice", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Green Valley School");
    await user.click(screen.getByRole("tab", { name: "Invoices" }));

    expect(await screen.findByText("Current invoice")).toBeInTheDocument();
    expect(screen.getByText("INV-0001")).toBeInTheDocument();
  });

  it("switches to Payments and shows the payment resolved from this subscription's invoices", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Green Valley School");
    await user.click(screen.getByRole("tab", { name: "Payments" }));

    await waitFor(() => expect(listPayments).toHaveBeenCalled());
    expect(await screen.findByText("stripe")).toBeInTheDocument();
  });

  it("switches to Timeline and shows the status timeline and audit timeline", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Green Valley School");
    await user.click(screen.getByRole("tab", { name: "Timeline & Events" }));

    expect(await screen.findByText("Status timeline")).toBeInTheDocument();
    expect(screen.getByText("Renewal history")).toBeInTheDocument();
    expect(screen.getByText("Audit timeline")).toBeInTheDocument();
    expect(await screen.findAllByText(/Grace Period Extended/i)).not.toHaveLength(0);
  });

  it("shows lifecycle actions for founder", async () => {
    setRole("founder");
    renderPage();

    await screen.findByText("Green Valley School");
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  it("hides lifecycle actions for a role without billing.subscriptions.manage", async () => {
    setRole("regional_manager");
    renderPage();

    await screen.findByText("Green Valley School");
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
  });

  it("shows a visible error when the subscription fails to load", async () => {
    setRole("founder");
    vi.mocked(getSubscription).mockReset().mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByText("Could not load this subscription")).toBeInTheDocument();
  });
});
