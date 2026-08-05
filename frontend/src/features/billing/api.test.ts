import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { listInvoices, listOrganizationsForPicker, listPlans, listSubscriptions } from "./api";

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

  it("listOrganizationsForPicker returns a minimal id/name list", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      data: [{ id: "org1", name: "Acme School" }],
      page: { total: 1, page: 1, page_size: 100 },
    });

    const options = await listOrganizationsForPicker();

    expect(options).toEqual([{ id: "org1", name: "Acme School" }]);
  });
});
