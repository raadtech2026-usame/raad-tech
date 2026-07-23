import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listRoutes: vi.fn(),
  getRoute: vi.fn(),
  createRoute: vi.fn(),
  updateRouteStatus: vi.fn(),
  addStopToRoute: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { RoutesPage } from "./RoutesPage";

const ROUTE_SUMMARY: api.RouteSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  name: "Morning Route A",
  status: "active",
};

const STOP: api.Stop = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FST",
  name: "Main Street & 5th Ave",
  latitude: 2.0469,
  longitude: 45.3182,
  sequenceNo: 1,
  geofenceRadiusM: 100,
};

const ROUTE_DETAIL: api.Route = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  name: "Morning Route A",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  stops: [STOP],
};

function pageOf<T>(data: T[], total: number): OffsetPage<T> {
  return { data, page: { total, page: 1, pageSize: 25 } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RoutesPage />
    </QueryClientProvider>,
  );
}

describe("RoutesPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listRoutes).mockReset();
    vi.mocked(api.getRoute).mockReset().mockResolvedValue(ROUTE_DETAIL);
    vi.mocked(api.updateRouteStatus).mockReset();
    vi.mocked(api.addStopToRoute).mockReset();
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
  });

  it("renders skeleton state while loading, then the fetched routes (name + status only)", async () => {
    let resolvePage!: (value: OffsetPage<api.RouteSummary>) => void;
    vi.mocked(api.listRoutes).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Morning Route A")).not.toBeInTheDocument();

    resolvePage(pageOf([ROUTE_SUMMARY], 1));

    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    expect(within(screen.getByRole("table")).getByText("Active")).toBeInTheDocument();
  });

  it("shows an empty state when there are no routes", async () => {
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No routes yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listRoutes).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load routes")).toBeInTheDocument());
  });

  it("opens the detail drawer and shows the ordered stops with the reorder-limitation caption", async () => {
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([ROUTE_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getRoute).toHaveBeenCalledWith(ROUTE_SUMMARY.id));
    expect(await within(dialog).findByText("1. Main Street & 5th Ave")).toBeInTheDocument();
    expect(within(dialog).getByText(/Reordering and removing individual stops isn't available yet/)).toBeInTheDocument();
    expect(within(dialog).getByText("Green Valley School")).toBeInTheDocument();
  });

  it("shows 'No stops added yet' for a route with no stops", async () => {
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([ROUTE_SUMMARY], 1));
    vi.mocked(api.getRoute).mockResolvedValue({ ...ROUTE_DETAIL, stops: [] });

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("No stops added yet.")).toBeInTheDocument();
  });

  it("opens AddStopForm pre-filled with the next unused sequence number", async () => {
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([ROUTE_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("1. Main Street & 5th Ave");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add stop" }));

    expect(await screen.findByPlaceholderText("e.g. 1")).toHaveValue("2");
  });

  it("lets a founder deactivate an active route from the detail drawer", async () => {
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([ROUTE_SUMMARY], 1));
    vi.mocked(api.updateRouteStatus).mockResolvedValue({ ...ROUTE_DETAIL, status: "inactive" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(api.updateRouteStatus).toHaveBeenCalledWith(ROUTE_SUMMARY.id, "inactive"));
  });

  it("hides the New Route/Add stop actions and drawer management actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listRoutes).mockResolvedValue(pageOf([ROUTE_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Route/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Morning Route A"));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("1. Main Street & 5th Ave");

    expect(within(dialog).queryByRole("button", { name: "Add stop" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });
});
