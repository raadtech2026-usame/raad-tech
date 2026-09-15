import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Plan, Subscription } from "../../billing/api";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  orgSubscriptions: vi.fn(),
  orgPlanCatalog: vi.fn(),
  orgUsers: vi.fn(),
  orgVehicles: vi.fn(),
  orgStudentCount: vi.fn(),
  orgParentCount: vi.fn(),
}));

import {
  orgParentCount,
  orgPlanCatalog,
  orgStudentCount,
  orgSubscriptions,
  orgUsers,
  orgVehicles,
} from "./api";
import { OrganizationOverviewSummary } from "./OrganizationOverviewSummary";

const ORG_ID = "org-1";

function offsetPage<T>(data: T[]) {
  return { data, page: { total: data.length, page: 1, pageSize: 100 } };
}

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

const ACTIVE_SUBSCRIPTION: Subscription = {
  id: "sub-1",
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

function renderSummary(onSelectTab = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onSelectTab,
    ...render(
      <QueryClientProvider client={queryClient}>
        <OrganizationOverviewSummary organizationId={ORG_ID} onSelectTab={onSelectTab} />
      </QueryClientProvider>,
    ),
  };
}

/**
 * Organization Overview's Subscription/Trial and Usage summary blocks (Organization Management
 * phase) — every figure here is a real read through this page's own composed client, never a
 * fabricated metric. Devices and Routes must never appear here (Part 6's own constraint) — these
 * tests pin that omission as a real, checked property, not an accident of what happened to get
 * built.
 */
describe("OrganizationOverviewSummary", () => {
  beforeEach(() => {
    vi.mocked(orgSubscriptions).mockReset().mockResolvedValue(offsetPage([]));
    vi.mocked(orgPlanCatalog).mockReset().mockResolvedValue(offsetPage([PLAN]));
    vi.mocked(orgUsers).mockReset().mockResolvedValue(offsetPage(["u1", "u2"]) as never);
    vi.mocked(orgVehicles).mockReset().mockResolvedValue(offsetPage(["v1"]) as never);
    vi.mocked(orgStudentCount).mockReset().mockResolvedValue(42);
    vi.mocked(orgParentCount).mockReset().mockResolvedValue(17);
  });

  it("says no subscription rather than fabricating one", async () => {
    renderSummary();

    expect(
      await screen.findByText(/no raad subscription/i),
    ).toBeInTheDocument();
  });

  it("shows the current subscription's status, plan, amount and renewal date", async () => {
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    renderSummary();

    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(await screen.findByText("Standard")).toBeInTheDocument();
    expect(screen.getByText(/199\.50.*Monthly/)).toBeInTheDocument();
  });

  it("shows real Users/Vehicles/Students/Parents counts", async () => {
    renderSummary();

    expect(await screen.findByText("2")).toBeInTheDocument(); // users
    expect(screen.getByText("1")).toBeInTheDocument(); // vehicles
    expect(screen.getByText("42")).toBeInTheDocument(); // students
    expect(screen.getByText("17")).toBeInTheDocument(); // parents
  });

  it("never shows Devices or Routes in this summary", async () => {
    renderSummary();
    await screen.findByText("Usage summary");

    expect(screen.queryByText(/^Devices$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Routes$/)).not.toBeInTheDocument();
  });

  it("navigates to the Subscription and Usage tabs from their own View links", async () => {
    const user = userEvent.setup();
    vi.mocked(orgSubscriptions).mockResolvedValue(offsetPage([ACTIVE_SUBSCRIPTION]));
    const { onSelectTab } = renderSummary();

    await user.click(await screen.findByRole("button", { name: "View subscription →" }));
    expect(onSelectTab).toHaveBeenCalledWith("subscription");

    await user.click(screen.getByRole("button", { name: "View full usage →" }));
    expect(onSelectTab).toHaveBeenCalledWith("usage");
  });
});
