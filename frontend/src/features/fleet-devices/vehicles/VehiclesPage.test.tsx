import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listVehicles: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  updateVehicleStatus: vi.fn(),
  registerVehicle: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { VehiclesPage } from "./VehiclesPage";

const VEHICLE: api.Vehicle = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  plateNo: "ABC-1234",
  label: "Bus 12",
  capacity: 32,
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
      <VehiclesPage />
    </QueryClientProvider>,
  );
}

describe("VehiclesPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listVehicles).mockReset();
    vi.mocked(api.listOrganizationsForPicker)
      .mockReset()
      .mockResolvedValue([{ id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" }]);
    vi.mocked(api.updateVehicleStatus).mockReset();
  });

  it("renders skeleton state while loading, then the fetched vehicles", async () => {
    let resolvePage!: (value: OffsetPage<api.Vehicle>) => void;
    vi.mocked(api.listVehicles).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("ABC-1234")).not.toBeInTheDocument();

    resolvePage(pageOf([VEHICLE], 1));

    await waitFor(() => expect(screen.getByText("ABC-1234")).toBeInTheDocument());
    expect(screen.getByText("Green Valley School")).toBeInTheDocument();
    expect(screen.getByText("Bus 12")).toBeInTheDocument();
  });

  it("shows an empty state when there are no vehicles", async () => {
    vi.mocked(api.listVehicles).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No vehicles yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listVehicles).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load vehicles")).toBeInTheDocument());
  });

  it("opens the detail drawer with the vehicle's details on row click", async () => {
    vi.mocked(api.listVehicles).mockResolvedValue(pageOf([VEHICLE], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("ABC-1234")).toBeInTheDocument());

    await userEvent.click(screen.getByText("ABC-1234"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Capacity")).toBeInTheDocument();
    expect(within(dialog).getByText("32")).toBeInTheDocument();
    expect(within(dialog).getByText(VEHICLE.id)).toBeInTheDocument();
  });

  it("lets a founder mark an active vehicle under maintenance from the detail drawer", async () => {
    vi.mocked(api.listVehicles).mockResolvedValue(pageOf([VEHICLE], 1));
    vi.mocked(api.updateVehicleStatus).mockResolvedValue({ ...VEHICLE, status: "maintenance" });

    renderPage();
    await waitFor(() => expect(screen.getByText("ABC-1234")).toBeInTheDocument());
    await userEvent.click(screen.getByText("ABC-1234"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark under maintenance" }));

    await waitFor(() =>
      expect(api.updateVehicleStatus).toHaveBeenCalledWith("01ARZ3NDEKTSV4RRFFQ69G5FAV", "maintenance"),
    );
  });

  it("hides the New Vehicle action and drawer management actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "regional_manager", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listVehicles).mockResolvedValue(pageOf([VEHICLE], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("ABC-1234")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /New Vehicle/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("ABC-1234"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });
});
