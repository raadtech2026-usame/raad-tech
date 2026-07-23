import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listRegions: vi.fn(),
  createRegion: vi.fn(),
  updateRegionStatus: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { RegionsPage } from "./RegionsPage";

const REGION: api.Region = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "East Africa",
  geographicScope: "Kenya, Somalia, Ethiopia",
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
      <RegionsPage />
    </QueryClientProvider>,
  );
}

describe("RegionsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listRegions).mockReset();
    vi.mocked(api.updateRegionStatus).mockReset();
  });

  it("renders the fetched regions", async () => {
    vi.mocked(api.listRegions).mockResolvedValue(pageOf([REGION], 1));

    renderPage();

    await waitFor(() => expect(screen.getByText("East Africa")).toBeInTheDocument());
    expect(screen.getByText("Kenya, Somalia, Ethiopia")).toBeInTheDocument();
  });

  it("shows an empty state when there are no regions", async () => {
    vi.mocked(api.listRegions).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No regions yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listRegions).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load regions")).toBeInTheDocument());
  });

  it("lets a founder deactivate a region from the detail drawer", async () => {
    vi.mocked(api.listRegions).mockResolvedValue(pageOf([REGION], 1));
    vi.mocked(api.updateRegionStatus).mockResolvedValue({ ...REGION, status: "inactive" });

    renderPage();
    await waitFor(() => expect(screen.getByText("East Africa")).toBeInTheDocument());
    await userEvent.click(screen.getByText("East Africa"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() =>
      expect(api.updateRegionStatus).toHaveBeenCalledWith("01ARZ3NDEKTSV4RRFFQ69G5FBW", "inactive"),
    );
  });

  it("hides the New Region action and drawer management actions for a non-founder role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listRegions).mockResolvedValue(pageOf([REGION], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("East Africa")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Region/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("East Africa"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });
});
