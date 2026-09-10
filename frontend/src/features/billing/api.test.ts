import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import {
  extendGracePeriod,
  getBillingProviderConfig,
  getCurrentSubscription,
  initiatePayment,
  listInvoices,
  listOrganizationsForPicker,
  listPayments,
  listPlans,
  listSubscriptions,
  reactivateSubscription,
  suspendSubscription,
} from "./api";
import { ApiError } from "../../shared/api/types";

const PLAN_WIRE = {
  id: "p1",
  name: "Standard",
  billing_scope: "organization",
  amount: 199.5,
  currency: "USD",
  billing_cycle: "monthly",
  vehicle_limit: 10,
  device_limit: 20,
  user_limit: null,
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
      deviceLimit: 20,
      userLimit: null,
      status: "active",
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-01T00:00:00Z",
    });
  });

  it("maps a plan response that predates the device/user limit columns", async () => {
    // ADR-0040 §4's migration is additive; a cached or older response omits both keys, and
    // `undefined` would break the `number | null` contract every consumer reads.
    const { device_limit: _d, user_limit: _u, ...legacy } = PLAN_WIRE;
    vi.mocked(apiRequest).mockResolvedValue({
      data: [legacy],
      page: { total: 1, page: 1, page_size: 25 },
    });

    const page = await listPlans({ page: 1, pageSize: 25, sort: null, filters: {}, search: "" });

    expect(page.data[0].deviceLimit).toBeNull();
    expect(page.data[0].userLimit).toBeNull();
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
      // ADR-0039 lifecycle timestamps: absent on this wire fixture, so they map to null rather
      // than undefined - the mapper normalises, so consumers never have to check for both.
      pastDueSince: null,
      gracePeriodEndsAt: null,
      suspendedAt: null,
      cancelledAt: null,
      expiredAt: null,
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

describe("ADR-0039 subscription lifecycle", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("getCurrentSubscription calls the self-scoped route with no id", async () => {
    vi.mocked(apiRequest).mockResolvedValue(SUBSCRIPTION_WIRE);

    const subscription = await getCurrentSubscription();

    // No path or query id at all - the route is self-scoped by construction, so there is nothing
    // a caller could substitute to read another organization's subscription.
    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions/current");
    expect(subscription?.id).toBe("s1");
  });

  it("getCurrentSubscription returns null on 404 rather than throwing", async () => {
    // An organization that has never had a subscription is a normal state, not a failure the UI
    // should render as an error.
    vi.mocked(apiRequest).mockRejectedValue(new ApiError(404, { code: "not_found", message: "x", correlationId: null }));

    await expect(getCurrentSubscription()).resolves.toBeNull();
  });

  it("getCurrentSubscription still propagates non-404 failures", async () => {
    vi.mocked(apiRequest).mockRejectedValue(new ApiError(403, { code: "forbidden", message: "x", correlationId: null }));

    await expect(getCurrentSubscription()).rejects.toBeInstanceOf(ApiError);
  });

  it("suspendSubscription POSTs to the suspend route", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ ...SUBSCRIPTION_WIRE, status: "suspended" });

    const subscription = await suspendSubscription("s1");

    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions/s1/suspend", { method: "POST" });
    expect(subscription.status).toBe("suspended");
  });

  it("reactivateSubscription POSTs to the reactivate route", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ ...SUBSCRIPTION_WIRE, status: "active" });

    const subscription = await reactivateSubscription("s1");

    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions/s1/reactivate", { method: "POST" });
    expect(subscription.status).toBe("active");
  });

  it("extendGracePeriod sends an absolute instant, not a day count", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      ...SUBSCRIPTION_WIRE,
      status: "grace_period",
      grace_period_ends_at: "2026-10-01T00:00:00Z",
    });

    const subscription = await extendGracePeriod("s1", "2026-10-01T00:00:00Z");

    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions/s1/extend-grace", {
      method: "POST",
      body: { grace_period_ends_at: "2026-10-01T00:00:00Z" },
    });
    expect(subscription.status).toBe("grace_period");
    expect(subscription.gracePeriodEndsAt).toBe("2026-10-01T00:00:00Z");
  });

  it("encodes the subscription id into the path", async () => {
    vi.mocked(apiRequest).mockResolvedValue(SUBSCRIPTION_WIRE);

    await suspendSubscription("a/b");

    expect(apiRequest).toHaveBeenCalledWith("/billing/subscriptions/a%2Fb/suspend", { method: "POST" });
  });
});
