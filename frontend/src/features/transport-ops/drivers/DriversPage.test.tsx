import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listDrivers: vi.fn(),
  getDriver: vi.fn(),
  registerDriver: vi.fn(),
  updateDriverStatus: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listDriverUsersForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { DriversPage } from "./DriversPage";

const DRIVER_SUMMARY: api.DriverSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  licenseNo: "DL-00231",
  status: "active",
};

const DRIVER_DETAIL: api.Driver = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  userId: "01ARZ3NDEKTSV4RRFFQ69G5FGA",
  licenseNo: "DL-00231",
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
      <DriversPage />
    </QueryClientProvider>,
  );
}

describe("DriversPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listDrivers).mockReset();
    vi.mocked(api.getDriver).mockReset().mockResolvedValue(DRIVER_DETAIL);
    vi.mocked(api.updateDriverStatus).mockReset();
    vi.mocked(api.listDriverUsersForPicker).mockReset().mockResolvedValue([]);
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("renders skeleton state while loading, then the fetched drivers (license no + status only)", async () => {
    let resolvePage!: (value: OffsetPage<api.DriverSummary>) => void;
    vi.mocked(api.listDrivers).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("DL-00231")).not.toBeInTheDocument();

    resolvePage(pageOf([DRIVER_SUMMARY], 1));

    await waitFor(() => expect(screen.getByText("DL-00231")).toBeInTheDocument());
    expect(within(screen.getByRole("table")).getByText("Active")).toBeInTheDocument();
  });

  it("shows an empty state when there are no drivers", async () => {
    vi.mocked(api.listDrivers).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No drivers yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listDrivers).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load drivers")).toBeInTheDocument());
  });

  it("opens the detail drawer and fetches the full driver record for the richer fields", async () => {
    vi.mocked(api.listDrivers).mockResolvedValue(pageOf([DRIVER_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("DL-00231")).toBeInTheDocument());
    await userEvent.click(screen.getByText("DL-00231"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getDriver).toHaveBeenCalledWith(DRIVER_SUMMARY.id));
    expect(await within(dialog).findByText("Green Valley School")).toBeInTheDocument();
  });

  it("lets a founder deactivate an active driver from the detail drawer", async () => {
    vi.mocked(api.listDrivers).mockResolvedValue(pageOf([DRIVER_SUMMARY], 1));
    vi.mocked(api.updateDriverStatus).mockResolvedValue({ ...DRIVER_DETAIL, status: "inactive" });

    renderPage();
    await waitFor(() => expect(screen.getByText("DL-00231")).toBeInTheDocument());
    await userEvent.click(screen.getByText("DL-00231"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(api.updateDriverStatus).toHaveBeenCalledWith(DRIVER_SUMMARY.id, "inactive"));
  });

  it("hides the New Driver action and drawer management actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listDrivers).mockResolvedValue(pageOf([DRIVER_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("DL-00231")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Driver/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("DL-00231"));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Green Valley School");

    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });
});
