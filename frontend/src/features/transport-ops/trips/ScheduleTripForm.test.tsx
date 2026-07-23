import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  scheduleTrip: vi.fn(),
  listOrganizationsForPicker: vi.fn(),
  listVehiclesForPicker: vi.fn(),
  listDriversForPicker: vi.fn(),
  listRoutesForPicker: vi.fn(),
}));

import * as api from "./api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { ScheduleTripForm } from "./ScheduleTripForm";

const ORG = { id: "01ARZ3NDEKTSV4RRFFQ69G5FBW", name: "Green Valley School" };
const VEHICLE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FVH", plateNo: "KAA 123B", label: null };
const DRIVER = { id: "01ARZ3NDEKTSV4RRFFQ69G5FDR", licenseNo: "DL-00231" };
const ROUTE = { id: "01ARZ3NDEKTSV4RRFFQ69G5FRT", name: "Morning Route A" };

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ScheduleTripForm open onClose={() => {}} />
    </QueryClientProvider>,
  );
}

describe("ScheduleTripForm", () => {
  beforeEach(() => {
    vi.mocked(api.scheduleTrip).mockReset();
    vi.mocked(api.listOrganizationsForPicker).mockReset().mockResolvedValue([ORG]);
    vi.mocked(api.listVehiclesForPicker).mockReset().mockResolvedValue([VEHICLE]);
    vi.mocked(api.listDriversForPicker).mockReset().mockResolvedValue([DRIVER]);
    vi.mocked(api.listRoutesForPicker).mockReset().mockResolvedValue([ROUTE]);
  });

  it("shows an organization picker for a founder (no organization of their own)", async () => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
    });

    renderForm();

    expect(await screen.findByLabelText("Organization")).toBeInTheDocument();
    expect(screen.getByLabelText("Vehicle")).toBeDisabled();
  });

  it("skips the organization picker and enables the vehicle picker immediately for an Org Admin", async () => {
    useAuthStore.setState({
      principal: {
        userId: "u1",
        role: "org_admin",
        organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        regionIds: [],
      },
    });

    renderForm();

    expect(screen.queryByLabelText("Organization")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Vehicle")).not.toBeDisabled());
  });

  it("submits the exact ScheduleTripInput shape for an Org Admin", async () => {
    useAuthStore.setState({
      principal: {
        userId: "u1",
        role: "org_admin",
        organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        regionIds: [],
      },
    });
    vi.mocked(api.scheduleTrip).mockResolvedValue({
      id: "01ARZ3NDEKTSV4RRFFQ69G5FTP",
      organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
      vehicleId: VEHICLE.id,
      driverId: DRIVER.id,
      routeId: ROUTE.id,
      tripType: "morning",
      status: "scheduled",
      scheduledDate: "2026-07-24",
      startedAt: null,
      endedAt: null,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
    });

    renderForm();

    await waitFor(() => expect(screen.getByLabelText("Vehicle")).not.toBeDisabled());
    await waitFor(() => expect(screen.getByLabelText("Driver")).not.toBeDisabled());
    await waitFor(() => expect(screen.getByLabelText("Route")).not.toBeDisabled());
    await userEvent.selectOptions(screen.getByLabelText("Vehicle"), VEHICLE.id);
    await userEvent.selectOptions(screen.getByLabelText("Driver"), DRIVER.id);
    await userEvent.selectOptions(screen.getByLabelText("Route"), ROUTE.id);
    // `userEvent.type` sends one keystroke at a time, and jsdom's `type="date"` value sanitizer
    // rejects every intermediate partial string — `fireEvent.change` with the final value is the
    // correct way to fill a native date input in this test environment.
    fireEvent.change(screen.getByLabelText("Scheduled date"), { target: { value: "2026-07-24" } });
    await userEvent.click(screen.getByRole("button", { name: "Schedule trip" }));

    await waitFor(() =>
      expect(api.scheduleTrip).toHaveBeenCalledWith({
        organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        vehicleId: VEHICLE.id,
        driverId: DRIVER.id,
        routeId: ROUTE.id,
        tripType: "morning",
        scheduledDate: "2026-07-24",
      }),
    );
  });

  it("shows a validation error and does not submit when required fields are missing", async () => {
    useAuthStore.setState({
      principal: {
        userId: "u1",
        role: "org_admin",
        organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
        regionIds: [],
      },
    });

    renderForm();
    await userEvent.click(screen.getByRole("button", { name: "Schedule trip" }));

    expect(await screen.findByText("Vehicle is required")).toBeInTheDocument();
    expect(api.scheduleTrip).not.toHaveBeenCalled();
  });
});
