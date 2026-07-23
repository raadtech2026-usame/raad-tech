import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  changeTripDriver: vi.fn(),
  listDriversForPicker: vi.fn(),
}));

import * as api from "./api";
import { ChangeTripDriverForm } from "./ChangeTripDriverForm";
import type { Trip } from "./api";

const TRIP: Trip = {
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
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderForm(trip: Trip | null = TRIP) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChangeTripDriverForm open onClose={() => {}} trip={trip} />
    </QueryClientProvider>,
  );
}

describe("ChangeTripDriverForm", () => {
  beforeEach(() => {
    vi.mocked(api.changeTripDriver).mockReset();
    vi.mocked(api.listDriversForPicker)
      .mockReset()
      .mockResolvedValue([
        { id: "01ARZ3NDEKTSV4RRFFQ69G5FDR", licenseNo: "DL-00231" },
        { id: "01ARZ3NDEKTSV4RRFFQ69G5FD2", licenseNo: "DL-00999" },
      ]);
  });

  it("renders nothing when no trip is selected", () => {
    renderForm(null);
    expect(screen.queryByText("Change driver")).not.toBeInTheDocument();
  });

  it("submits the new driver id for the selected trip", async () => {
    vi.mocked(api.changeTripDriver).mockResolvedValue({ ...TRIP, driverId: "01ARZ3NDEKTSV4RRFFQ69G5FD2" });

    renderForm();

    const driverSelect = await screen.findByLabelText("Driver");
    await waitFor(() => expect(driverSelect).not.toBeDisabled());
    await userEvent.selectOptions(driverSelect, "01ARZ3NDEKTSV4RRFFQ69G5FD2");
    await userEvent.click(screen.getByRole("button", { name: "Change driver" }));

    await waitFor(() =>
      expect(api.changeTripDriver).toHaveBeenCalledWith(TRIP.id, "01ARZ3NDEKTSV4RRFFQ69G5FD2"),
    );
  });

  it("shows a validation error and does not submit when no driver is selected", async () => {
    renderForm();

    await screen.findByLabelText("Driver");
    await userEvent.click(screen.getByRole("button", { name: "Change driver" }));

    expect(await screen.findByText("Driver is required")).toBeInTheDocument();
    expect(api.changeTripDriver).not.toHaveBeenCalled();
  });
});
