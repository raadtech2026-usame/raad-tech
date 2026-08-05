import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../shared/stores/authStore";
import { BillingPage } from "./BillingPage";
import type { Invoice, Plan, Subscription } from "./api";

vi.mock("./api", () => ({
  listPlans: vi.fn(),
  listSubscriptions: vi.fn(),
  listInvoices: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import { listInvoices, listOrganizationsForPicker, listPlans, listSubscriptions } from "./api";

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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BillingPage />
    </QueryClientProvider>,
  );
}

function setRole(role: "founder" | "regional_manager" | "org_admin") {
  useAuthStore.setState({
    principal: { userId: "u1", role, organizationId: role === "org_admin" ? "org1" : null, regionIds: [] },
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  });
}

describe("BillingPage", () => {
  beforeEach(() => {
    vi.mocked(listPlans).mockReset().mockResolvedValue(offsetPage([PLAN]));
    vi.mocked(listSubscriptions).mockReset().mockResolvedValue(offsetPage([SUBSCRIPTION]));
    vi.mocked(listInvoices).mockReset().mockResolvedValue(offsetPage([INVOICE]));
    vi.mocked(listOrganizationsForPicker).mockReset().mockResolvedValue([{ id: "org1", name: "Acme School" }]);
  });

  it("shows the Plans tab by default with tabs for Subscriptions/Invoices", async () => {
    setRole("founder");
    renderPage();

    expect(await screen.findByText("Standard")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Plans" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Invoices" })).toBeInTheDocument();
  });

  it("switches to Subscriptions and resolves organization/plan names", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Standard");
    await user.click(screen.getByRole("tab", { name: "Subscriptions" }));

    expect(await screen.findByText("Acme School")).toBeInTheDocument();
    await waitFor(() => expect(listSubscriptions).toHaveBeenCalled());
  });

  it("switches to Invoices and shows the invoice number and amount", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Standard");
    await user.click(screen.getByRole("tab", { name: "Invoices" }));

    expect(await screen.findByText("INV-0001")).toBeInTheDocument();
    expect(screen.getByText("$199.50")).toBeInTheDocument();
  });

  it("opens the plan detail drawer on row click", async () => {
    setRole("founder");
    const user = userEvent.setup();
    renderPage();

    const row = await screen.findByText("Standard");
    await user.click(row);

    expect(await screen.findByText("Plan ID")).toBeInTheDocument();
  });

  it("shows a visible error when plans fail to load", async () => {
    setRole("founder");
    vi.mocked(listPlans).mockReset().mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByText("Could not load plans")).toBeInTheDocument();
  });

  it("hides the tab switcher and other tabs for Regional Manager (plans-only RBAC)", async () => {
    setRole("regional_manager");
    renderPage();

    expect(await screen.findByText("Standard")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Plans" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Subscriptions" })).not.toBeInTheDocument();
    expect(listSubscriptions).not.toHaveBeenCalled();
    expect(listInvoices).not.toHaveBeenCalled();
  });

  it("shows all three tabs for Org Admin", async () => {
    setRole("org_admin");
    renderPage();

    expect(await screen.findByText("Standard")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Invoices" })).toBeInTheDocument();
  });
});
