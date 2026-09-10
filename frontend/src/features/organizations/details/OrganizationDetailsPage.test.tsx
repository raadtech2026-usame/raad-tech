import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Organization } from "../api";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getOrganization: vi.fn(),
  listRegions: vi.fn(),
}));
vi.mock("./api", () => ({
  orgScopedParams: vi.fn(),
  orgUsers: vi.fn(),
  orgVehicles: vi.fn(),
  orgDevices: vi.fn(),
  orgDrivers: vi.fn(),
  orgRoutes: vi.fn(),
  orgSubscriptions: vi.fn(),
  orgInvoices: vi.fn(),
  orgPayments: vi.fn(),
  orgAudit: vi.fn(),
  orgStudentInvoices: vi.fn(),
  orgStudentPayments: vi.fn(),
  orgIncome: vi.fn(),
  orgExpenses: vi.fn(),
  orgStudentCount: vi.fn(),
  orgParentCount: vi.fn(),
}));

import { getOrganization, listRegions } from "../api";
import * as detailApi from "./api";
import { OrganizationDetailsPage } from "./OrganizationDetailsPage";

const ORG_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

const ORGANIZATION: Organization = {
  id: ORG_ID,
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: "region-1",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-02-01T00:00:00Z",
};

function emptyPage() {
  return { data: [], page: { total: 0, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/platform/organizations/${ORG_ID}`]}>
        <Routes>
          <Route
            path="/platform/organizations/:organizationId"
            element={<OrganizationDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The Founder's per-organization view.
 *
 * Two properties are worth pinning. First, every tab reads through the *organization-scoped*
 * client, so a tab can never quietly render another tenant's rows. Second, the Students and
 * Parents tabs show a count and say why there is no roster — RAAD holds `.count` but
 * deliberately not `.list` for those, and an empty table there would read as a bug rather than
 * as the product boundary it is.
 */
describe("OrganizationDetailsPage", () => {
  beforeEach(() => {
    vi.mocked(getOrganization).mockReset().mockResolvedValue(ORGANIZATION);
    vi.mocked(listRegions)
      .mockReset()
      .mockResolvedValue({
        data: [
          {
            id: "region-1",
            name: "Northern Region",
            geographicScope: null,
            status: "active",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
          },
        ],
        page: { total: 1, page: 1, pageSize: 100 },
      } as never);
    for (const key of [
      "orgUsers", "orgVehicles", "orgDevices", "orgDrivers", "orgRoutes",
      "orgSubscriptions", "orgInvoices", "orgPayments", "orgAudit",
      "orgStudentInvoices", "orgStudentPayments", "orgIncome", "orgExpenses",
    ] as const) {
      vi.mocked(detailApi[key]).mockReset().mockResolvedValue(emptyPage() as never);
    }
    vi.mocked(detailApi.orgStudentCount).mockReset().mockResolvedValue(42);
    vi.mocked(detailApi.orgParentCount).mockReset().mockResolvedValue(17);
  });

  it("opens on Overview with the organization's real identity fields", async () => {
    renderPage();

    expect(await screen.findByText("Green Valley School")).toBeInTheDocument();
    expect(screen.getByText("Northern Region")).toBeInTheDocument();
    expect(screen.getByText(ORG_ID)).toBeInTheDocument();
    expect(screen.getByText("None — top level")).toBeInTheDocument();
  });

  it("loads a tab's data only once that tab is opened", async () => {
    // Fifteen tabs firing on mount would be fifteen requests for a page where a Founder
    // usually wants one.
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Green Valley School");

    expect(detailApi.orgVehicles).not.toHaveBeenCalled();

    await user.click(screen.getByRole("tab", { name: "Vehicles" }));
    await waitFor(() => expect(detailApi.orgVehicles).toHaveBeenCalledWith(ORG_ID));
  });

  it("scopes every tab's read to this organization", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Green Valley School");

    for (const [tab, fn] of [
      ["Users", detailApi.orgUsers],
      ["Devices", detailApi.orgDevices],
      ["Invoices", detailApi.orgInvoices],
      ["Audit", detailApi.orgAudit],
    ] as const) {
      await user.click(screen.getByRole("tab", { name: tab }));
      await waitFor(() => expect(fn).toHaveBeenCalledWith(ORG_ID));
    }
  });

  it("shows a real count and explains the missing roster on the Students tab", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Green Valley School");

    await user.click(screen.getByRole("tab", { name: "Students" }));

    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(
      screen.getByText(/RAAD deliberately cannot list individual students/i),
    ).toBeInTheDocument();
  });

  it("keeps school finance visibly separate from the RAAD subscription", async () => {
    // ADR-0038 §2: Organization→Student money and RAAD→Organization money are different
    // domains and must never read as one balance.
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Green Valley School");

    await user.click(screen.getByRole("tab", { name: "Finance" }));

    expect(
      await screen.findByText(/different financial domain from the RAAD subscription/i),
    ).toBeInTheDocument();
  });

  it("surfaces a failed organization load instead of rendering an empty shell", async () => {
    vi.mocked(getOrganization).mockRejectedValue(new Error("boom"));
    renderPage();

    expect(
      await screen.findByText("Could not load this organization"),
    ).toBeInTheDocument();
  });
});
