import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OffsetPage } from "../../../shared/api/types";

vi.mock("./api", () => ({
  listTrips: vi.fn(),
  getTrip: vi.fn(),
  scheduleTrip: vi.fn(),
  startTrip: vi.fn(),
  endTrip: vi.fn(),
  changeTripDriver: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  listDriversForPicker: vi.fn(),
  listRoutesForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { TripsPage } from "./TripsPage";

const TRIP_SUMMARY: api.TripSummary = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
  vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  driverId: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  tripType: "morning",
  status: "scheduled",
  scheduledDate: "2026-07-24",
};

const TRIP_DETAIL: api.Trip = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
  organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  vehicleId: "01ARZ3NDEKTSV4RRFFQ69G5FVH",
  driverId: "01ARZ3NDEKTSV4RRFFQ69G5FDR",
  routeId: "01ARZ3NDEKTSV4RRFFQ69G5FRT",
  tripType: "morning",
  status: "scheduled",
  scheduledDate: "2026-07-24",
  startedAt: null,
  endedAt: null,
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
      <TripsPage />
    </QueryClientProvider>,
  );
}

describe("TripsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    vi.mocked(api.listTrips).mockReset();
    vi.mocked(api.getTrip).mockReset().mockResolvedValue(TRIP_DETAIL);
    vi.mocked(api.startTrip).mockReset();
    vi.mocked(api.endTrip).mockReset();
    vi.mocked(api.changeTripDriver).mockReset();
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" },
    ]);
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FVH", plateNo: "KAA 123B", label: null },
    ]);
    vi.mocked(api.listDriversForPicker).mockReset().mockResolvedValue([
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FDR", licenseNo: "DL-00231" },
    ]);
    vi.mocked(api.listRoutesForPicker).mockReset().mockResolvedValue([
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FRT", name: "Morning Route A" },
    ]);
  });

  it("renders skeleton state while loading, then the fetched trips with resolved vehicle/driver/route names", async () => {
    let resolvePage!: (value: OffsetPage<api.TripSummary>) => void;
    vi.mocked(api.listTrips).mockReturnValue(
      new Promise((resolve) => {
        resolvePage = resolve;
      }),
    );

    renderPage();

    expect(document.querySelector("table")).toBeInTheDocument();
    expect(screen.queryByText("Morning Route A")).not.toBeInTheDocument();

    resolvePage(pageOf([TRIP_SUMMARY], 1));

    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    const table = screen.getByRole("table");
    expect(within(table).getByText("DL-00231")).toBeInTheDocument();
    expect(within(table).getByText("KAA 123B")).toBeInTheDocument();
    expect(within(table).getByText("Scheduled")).toBeInTheDocument();
  });

  it("shows an empty state when there are no trips", async () => {
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([], 0));

    renderPage();

    await waitFor(() => expect(screen.getByText("No trips yet")).toBeInTheDocument());
  });

  it("shows an honest error state when the request fails", async () => {
    vi.mocked(api.listTrips).mockRejectedValue(new Error("network down"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Could not load trips")).toBeInTheDocument());
  });

  it("opens the detail drawer and shows organization/vehicle/driver/route names", async () => {
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([TRIP_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(api.getTrip).toHaveBeenCalledWith(TRIP_SUMMARY.id));
    expect(await within(dialog).findByText("Green Valley School")).toBeInTheDocument();
    expect(within(dialog).getByText("Not started")).toBeInTheDocument();
    expect(within(dialog).getByText("Not ended")).toBeInTheDocument();
  });

  it("lets a founder start a scheduled trip from the detail drawer", async () => {
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([TRIP_SUMMARY], 1));
    vi.mocked(api.startTrip).mockResolvedValue({ ...TRIP_DETAIL, status: "in_progress" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start trip" }));

    await waitFor(() => expect(api.startTrip).toHaveBeenCalledWith(TRIP_SUMMARY.id));
    expect(within(dialog).queryByRole("button", { name: "Start trip" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "End trip" })).toBeInTheDocument();
  });

  it("lets a founder end an in-progress trip from the detail drawer", async () => {
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([{ ...TRIP_SUMMARY, status: "in_progress" }], 1));
    vi.mocked(api.getTrip).mockResolvedValue({ ...TRIP_DETAIL, status: "in_progress" });
    vi.mocked(api.endTrip).mockResolvedValue({ ...TRIP_DETAIL, status: "completed" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "End trip" }));

    await waitFor(() => expect(api.endTrip).toHaveBeenCalledWith(TRIP_SUMMARY.id));
  });

  it("lets a founder change a trip's driver", async () => {
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([TRIP_SUMMARY], 1));
    vi.mocked(api.listDriversForPicker).mockResolvedValue([
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FDR", licenseNo: "DL-00231" },
      { id: "01ARZ3NDEKTSV4RRFFQ69G5FD2", licenseNo: "DL-00999" },
    ]);
    vi.mocked(api.changeTripDriver).mockResolvedValue({ ...TRIP_DETAIL, driverId: "01ARZ3NDEKTSV4RRFFQ69G5FD2" });

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Morning Route A"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Change driver" }));

    const driverSelect = await screen.findByLabelText("Driver");
    await waitFor(() => expect(driverSelect).not.toBeDisabled());
    await userEvent.selectOptions(driverSelect, "01ARZ3NDEKTSV4RRFFQ69G5FD2");
    // Both the drawer's own footer action and the just-opened form's submit button share the
    // "Change driver" label (`DetailDrawer` and `FormDrawer` stay mounted simultaneously, the
    // same nested-dialog precedent `RoutesPage.test.tsx`'s "Add stop" flow already establishes)
    // — the form's submit button renders last in DOM order.
    const changeDriverButtons = screen.getAllByRole("button", { name: "Change driver" });
    await userEvent.click(changeDriverButtons[changeDriverButtons.length - 1]);

    await waitFor(() =>
      expect(api.changeTripDriver).toHaveBeenCalledWith(TRIP_SUMMARY.id, "01ARZ3NDEKTSV4RRFFQ69G5FD2"),
    );
  });

  it("hides the Schedule Trip action and drawer management actions for a read-only role", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "support_staff", organizationId: null, regionIds: [] },
    });
    vi.mocked(api.listTrips).mockResolvedValue(pageOf([TRIP_SUMMARY], 1));

    renderPage();
    await waitFor(() => expect(screen.getByText("Morning Route A")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /Schedule Trip/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Morning Route A"));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Green Valley School");

    expect(within(dialog).queryByRole("button", { name: "Start trip" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Change driver" })).not.toBeInTheDocument();
  });
});
