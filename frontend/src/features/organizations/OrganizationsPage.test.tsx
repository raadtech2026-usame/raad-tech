import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../shared/api/types";

vi.mock("./api", () => ({
  listOrganizations: vi.fn(),
  listRegions: vi.fn(),
  updateOrganizationStatus: vi.fn(),
  createOrganization: vi.fn(),
}));

import * as api from "./api";
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
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrganizationsPage />
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

  it("opens the detail drawer with the organization's details on row click", async () => {
    vi.mocked(api.listOrganizations).mockResolvedValue(pageOf([ORG], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Green Valley School")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Green Valley School"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Region")).toBeInTheDocument();
    expect(within(dialog).getByText("Northern Region")).toBeInTheDocument();
    expect(within(dialog).getByText(ORG.id)).toBeInTheDocument();
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
