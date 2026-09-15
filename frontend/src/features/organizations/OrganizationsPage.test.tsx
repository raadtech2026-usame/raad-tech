import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../shared/api/types";

vi.mock("./api", () => ({
  listOrganizations: vi.fn(),
  listRegions: vi.fn(),
  updateOrganizationStatus: vi.fn(),
  createOrganization: vi.fn(),
}));
// The list now shows each organization's plan, subscription state and renewal date, joined in
// memory from two capped lookups — never one request per row.
vi.mock("../billing/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../billing/api")>()),
  listSubscriptions: vi.fn(),
  listPlans: vi.fn(),
}));

import * as api from "./api";
import { listPlans, listSubscriptions } from "../billing/api";
import { useAuthStore } from "../../shared/stores/authStore";
import { OrganizationsPage } from "./OrganizationsPage";

const REGION: api.Region = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Northern Region",
  geographicScope: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

const ORG: api.Organization = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: REGION.id,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  trialStartedAt: null,
  trialEndsAt: null,
  trialState: "not_started",
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      {/* The page navigates to Organization Details on row click, so it needs a router. */}
      <MemoryRouter initialEntries={["/platform/organizations"]}>
        <Routes>
          <Route path="/platform/organizations" element={<OrganizationsPage />} />
          <Route
            path="/platform/organizations/:organizationId"
            element={<div>ORGANIZATION DETAILS</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OrganizationsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listOrganizations).mockReset();
    vi.mocked(api.listRegions).mockReset().mockResolvedValue(pageOf([REGION], 1));
    vi.mocked(api.updateOrganizationStatus).mockReset();
    vi.mocked(listSubscriptions)
      .mockReset()
      .mockResolvedValue({ data: [], page: { total: 0, page: 1, pageSize: 100 } });
    vi.mocked(listPlans)
      .mockReset()
      .mockResolvedValue({ data: [], page: { total: 0, page: 1, pageSize: 100 } });
  });

  it("renders skeleton state while loading, then the fetched organizations", async () => {
    let resolvePage!: (value: OffsetPage<api.Organization>) => void;
    vi.mocked(api.listOrganizations).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    // Loading: the table shell is present, but no real row data has rendered yet.
    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Green Valley School")).not.toBeInTheDocument();

    resolvePage(pageOf([ORG], 1));

    await waitFor(() => expect(screen.getByText("Green Valley School")).toBeInTheDocument());
    expect(screen.getByText("Northern Region")).toBeInTheDocument();
  });

  it("shows an empty state when there are no organizations", async () => {
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No organizations yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listOrganizations).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Could not load organizations")).toBeInTheDocument(),
    );
  });

  it("navigates to Organization Details on row click", async () => {
    // Replaced a detail drawer on 2026-09-09. Everything the drawer showed — region, parent, id,
    // timestamps, and the three status actions — now lives on the Details page's Overview and
    // Settings tabs, so keeping both would have been two surfaces to drift apart.
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([ORG], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Green Valley School")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Green Valley School"));

    expect(await screen.findByText("ORGANIZATION DETAILS")).toBeInTheDocument();
  });

  it("shows each organization's plan, subscription state and renewal date", async () => {
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([ORG], 1));
    vi.mocked(listPlans).mockResolvedValue({
      data: [
        {
          id: "plan-1",
          name: "Basic Plane",
          billingScope: "organization",
          amount: 30,
          currency: "USD",
          billingCycle: "monthly",
          vehicleLimit: 10,
          deviceLimit: 20,
          userLimit: null,
          status: "active",
          createdAt: "2026-08-01T00:00:00Z",
          updatedAt: "2026-08-01T00:00:00Z",
        },
      ],
      page: { total: 1, page: 1, pageSize: 100 },
    });
    vi.mocked(listSubscriptions).mockResolvedValue({
      data: [
        {
          id: "sub-1",
          organizationId: ORG.id,
          planId: "plan-1",
          status: "active",
          currentPeriodStart: "2026-09-01T00:00:00Z",
          currentPeriodEnd: "2026-10-01T00:00:00Z",
          autoRenew: true,
          createdAt: "2026-09-01T00:00:00Z",
          updatedAt: "2026-09-01T00:00:00Z",
          pastDueSince: null,
          gracePeriodEndsAt: null,
          suspendedAt: null,
          cancelledAt: null,
          expiredAt: null,
        },
      ],
      page: { total: 1, page: 1, pageSize: 100 },
    });

    renderPage();

    expect(await screen.findByText("Basic Plane")).toBeInTheDocument();
    // "Active" is also the organization's own status and a filter chip, so scope to the row.
    const row = screen.getByText("Basic Plane").closest("tr");
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("Active");
  });

  it("calls out an organization that has no subscription at all", async () => {
    // Every organization on this platform ran without a subscription for the entire life of the
    // feature and no surface said so. This column is the cheapest detection of a recurrence, so
    // "no subscription" must read as a problem, not as an empty cell.
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([ORG], 1));

    renderPage();

    expect(await screen.findByText("No subscription")).toBeInTheDocument();
  });

  it("joins subscriptions in memory rather than one request per row", async () => {
    const many = Array.from({ length: 5 }, (_, index) => ({
      ...ORG,
      id: `org-${index}`,
      name: `School ${index}`,
    }));
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf(many, many.length));

    renderPage();
    await waitFor(() => expect(screen.getByText("School 4")).toBeInTheDocument());

    // Two capped lookups for the whole page, regardless of row count — never N.
    expect(listSubscriptions).toHaveBeenCalledTimes(1);
    expect(listPlans).toHaveBeenCalledTimes(1);
  });

  it("hides the New Organization action for finance_staff", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "finance_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([ORG], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Green Valley School")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Organization/i })).not.toBeInTheDocument();
  });
});
