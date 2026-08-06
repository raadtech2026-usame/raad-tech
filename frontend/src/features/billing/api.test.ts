import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import {
  getBillingProviderConfig,
  initiatePayment,
  listInvoices,
  listOrganizationsForPicker,
  listPayments,
  listPlans,
  listSubscriptions,
} from "./api";

const PLAN_WIRE = {
  id: "p1",
  name: "Standard",
  billing_scope: "organization",
  amount: 199.5,
  currency: "USD",
  billing_cycle: "monthly",
  vehicle_limit: 10,
  status: "active",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const SUBSCRIPTION_WIRE = {
  id: "s1",
  organization_id: "org1",
  plan_id: "p1",
  status: "active",
  current_period_start: "2026-08-01T00:00:00Z",
  current_period_end: "2026-09-01T00:00:00Z",
  auto_renew: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const PAYMENT_WIRE = {
  id: "pay1",
  organization_id: "org1",
  invoice_id: "i1",
  provider: "stripe",
  provider_ref: "pi_123",
  amount: 199.5,
  currency: "USD",
  status: "paid",
  failure_reason: null,
  created_at: "2026-08-01T00:00:00Z",
  confirmed_at: "2026-08-01T00:05:00Z",
};

const INVOICE_WIRE = {
  id: "i1",
  organization_id: "org1",
  subscription_id: "s1",
  number: "INV-0001",
  amount: 199.5,
  currency: "USD",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  status: "issued",
  issued_at: "2026-08-01T00:00:00Z",
  due_at: "2026-08-15T00:00:00Z",
  paid_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("billing api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listPlans maps the snake_case wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [PLAN_WIRE], page: { total: 1, page: 1, page_size: 25 } });

    const page = await listPlans({ page: 1, pageSize: 25, sort: null, filters: {}, search: "" });

    expect(apiRequest).toHaveBeenCalledWith("/billing/plans?page=1&page_size=25");
    expect(page.data[0]).toEqual({
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
    });
  });

  it("listSubscriptions maps the wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [SUBSCRIPTION_WIRE], page: { total: 1, page: 1, page_size: 25 } });

    const page = await listSubscriptions({ page: 1, pageSize: 25, sort: null, filters: {}, search: "" });

    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions?page=1&page_size=25");
    expect(page.data[0]).toEqual({
      id: "s1",
      organizationId: "org1",
      planId: "p1",
      status: "active",
      currentPeriodStart: "2026-08-01T00:00:00Z",
      currentPeriodEnd: "2026-09-01T00:00:00Z",
      autoRenew: true,
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-01T00:00:00Z",
    });
  });

  it("listInvoices maps the wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [INVOICE_WIRE], page: { total: 1, page: 1, page_size: 25 } });

    const page = await listInvoices({ page: 1, pageSize: 25, sort: null, filters: { status: "issued" }, search: "" });

    expect(apiRequest).toHaveBeenCalledWith("/billing/invoices?page=1&page_size=25&filter%5Bstatus%5D=issued");
    expect(page.data[0]).toEqual({
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
    });
  });

  it("listPayments maps the wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [PAYMENT_WIRE], page: { total: 1, page: 1, page_size: 25 } });

    const page = await listPayments({ page: 1, pageSize: 25, sort: null, filters: { organization_id: "org1" }, search: "" });

    expect(apiRequest).toHaveBeenCalledWith("/billing/payments?page=1&page_size=25&filter%5Borganization_id%5D=org1");
    expect(page.data[0]).toEqual({
      id: "pay1",
      organizationId: "org1",
      invoiceId: "i1",
      provider: "stripe",
      providerRef: "pi_123",
      amount: 199.5,
      currency: "USD",
      status: "paid",
      failureReason: null,
      createdAt: "2026-08-01T00:00:00Z",
      confirmedAt: "2026-08-01T00:05:00Z",
    });
  });

  it("initiatePayment sends a fresh Idempotency-Key header and maps the response", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
    vi.mocked(apiRequest).mockResolvedValue({ payment_id: "pay1", status: "processing" });

    const result = await initiatePayment({
      invoiceId: "i1",
      method: "stripe",
      amount: 199.5,
      currency: "USD",
      paymentMethodToken: "pm_123",
    });

    expect(apiRequest).toHaveBeenCalledWith("/billing/payments", {
      method: "POST",
      headers: { "Idempotency-Key": "11111111-1111-4111-8111-111111111111" },
      body: {
        invoice_id: "i1",
        method: "stripe",
        amount: 199.5,
        currency: "USD",
        payment_method_token: "pm_123",
        msisdn: undefined,
      },
    });
    expect(result).toEqual({ paymentId: "pay1", status: "processing" });

    vi.restoreAllMocks();
  });

  it("getBillingProviderConfig finds the billing_payment_provider row among platform settings", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      data: [
        { key: "some_other_setting", value: { x: 1 }, scope: "platform" },
        { key: "billing_payment_provider", value: { provider: "stripe" }, scope: "platform" },
      ],
      page: { total: 2, page: 1, page_size: 50 },
    });

    const config = await getBillingProviderConfig();

    expect(apiRequest).toHaveBeenCalledWith(
      "/admin/settings?page=1&page_size=50&sort=key&filter%5Bscope%5D=platform",
    );
    expect(config).toEqual({ provider: "stripe" });
  });

  it("getBillingProviderConfig returns a null provider when no row exists yet", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [], page: { total: 0, page: 1, page_size: 50 } });

    const config = await getBillingProviderConfig();

    expect(config).toEqual({ provider: null });
  });

  it("listOrganizationsForPicker returns a minimal id/name list", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      data: [{ id: "org1", name: "Acme School" }],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const options = await listOrganizationsForPicker();

    expect(options).toEqual([{ id: "org1", name: "Acme School" }]);
  });
});
