import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../shared/api/client")>()),
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { useAuthStore } from "../../../shared/stores/authStore";
import { DailyOperationsPage } from "./DailyOperationsPage";
import { cancelTrip, generateTrips, getDailyBoard, recordUnavailability } from "./api";
import { addDays, formatTime, weekdaysLabel } from "./labels";

const BUS = "01ARZ3NDEKTSV4RRFFQ69G5BUS";

const BOARD_WIRE = {
  date: "2026-10-01",
  closures: [],
  uncovered_trips: 1,
  vehicles: [
    {
      vehicle_id: BUS,
      crew_gaps: 1,
      trips: [
        {
          id: "trip-1",
          trip_type: "morning",
          route_id: "r1",
          route_name: "North loop",
          planned_departure: "06:45:00",
          driver_id: "d1",
          driver_name: "Amina",
          status: "scheduled",
          cancelled_reason: null,
          uncovered_reason: "driver_unavailable",
        },
      ],
      crew: [
        { staff_id: "s2", staff_name: "Fatima", role_name: "Attendant", is_substitute: false, is_unavailable: true, covered_by: null },
      ],
    },
  ],
};

function route(path: string): unknown {
  if (path.startsWith("/daily-operations")) return BOARD_WIRE;
  if (path.startsWith("/vehicles")) return { data: [{ id: BUS, plate_no: "KB-12", label: null }], page: { total: 1, page: 1, page_size: 100 } };
  return [];
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DailyOperationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("operations api", () => {
  beforeEach(() => vi.mocked(apiRequest).mockReset());

  it("maps the daily board", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(BOARD_WIRE);
    const board = await getDailyBoard("2026-10-01");
    expect(apiRequest).toHaveBeenCalledWith("/daily-operations?date=2026-10-01");
    expect(board.vehicles[0].trips[0]).toMatchObject({ uncoveredReason: "driver_unavailable", plannedDeparture: "06:45:00" });
    expect(board.vehicles[0].crew[0]).toMatchObject({ isUnavailable: true, coveredBy: null });
  });

  it("sends a dry run for the preview", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({ start: "2026-10-01", days: 7, dry_run: true, to_create: [], skipped: [], closed_days: [], created: 0 });
    await generateTrips(7, true);
    expect(apiRequest).toHaveBeenCalledWith("/trips/generate", { method: "POST", body: { days: 7, dry_run: true } });
  });

  it("posts cancellation and unavailability in snake_case", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ id: "u1", staff_id: "s1", staff_name: "A", starts_on: "2026-10-01", ends_on: "2026-10-02", reason: "sick", note: null, withdrawn_at: null, covers: [], private_fields_visible: true });
    await cancelTrip("t1", "Breakdown");
    expect(apiRequest).toHaveBeenCalledWith("/trips/t1/cancel", { method: "POST", body: { reason: "Breakdown" } });
    await recordUnavailability({ staffId: "s1", startsOn: "2026-10-01", endsOn: "2026-10-02", reason: "sick", note: null });
    expect(vi.mocked(apiRequest).mock.calls[1][1]).toMatchObject({ body: { staff_id: "s1", reason: "sick" } });
  });
});

describe("labels", () => {
  it("summarises weekdays, days and times", () => {
    expect(weekdaysLabel([1, 2, 3, 4, 5])).toBe("Mon–Fri");
    expect(weekdaysLabel([1, 2, 3, 4, 5, 6, 7])).toBe("Every day");
    expect(weekdaysLabel([6, 7])).toBe("Sat, Sun");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(formatTime("06:45:00")).toBe("06:45");
  });
});

describe("DailyOperationsPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
    vi.mocked(apiRequest).mockImplementation(async (path: string) => route(path) as never);
    useAuthStore.setState({ principal: { userId: "u1", role: "org_admin", organizationId: "org", regionIds: [] } });
  });

  it("shows uncovered trips, crew gaps and the bus plate", async () => {
    renderPage();
    const bus = await screen.findByRole("region", { name: "KB-12" });
    expect(within(bus).getByText("Driver unavailable")).toBeInTheDocument();
    expect(within(bus).getByText("Away · not covered")).toBeInTheDocument();
    expect(screen.getByText("1 uncovered trip")).toBeInTheDocument();
  });

  it("will not cancel without a reason, and says parents will read it", async () => {
    renderPage();
    const bus = await screen.findByRole("region", { name: "KB-12" });
    await userEvent.click(within(bus).getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Parents will read this exactly as written.")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Cancel trip" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Cancellation reason"), "Breakdown");
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith("/trips/trip-1/cancel", { method: "POST", body: { reason: "Breakdown" } }),
    );
  });

  it("flags the day's alerts and incidents on the bus, leaving false alarms out", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path: string) => {
      if (path.startsWith("/safety-alerts")) return [{ vehicle_id: BUS, status: "open" }, { vehicle_id: BUS, status: "false_alarm" }] as never;
      if (path.startsWith("/incidents")) return [{ vehicle_id: BUS }, { vehicle_id: null }] as never;
      return route(path) as never;
    });
    renderPage();
    const bus = await screen.findByRole("region", { name: "KB-12" });
    expect(await within(bus).findByText("1 alert")).toBeInTheDocument();
    expect(within(bus).getByText("1 incident")).toBeInTheDocument();
    expect(screen.getByText("1 safety alert")).toBeInTheDocument();
    expect(screen.getByText("2 incidents")).toBeInTheDocument();
  });

  it("gives read-only roles no actions", async () => {
    useAuthStore.setState({ principal: { userId: "u2", role: "support_staff", organizationId: null, regionIds: [] } });
    renderPage();
    const bus = await screen.findByRole("region", { name: "KB-12" });
    expect(within(bus).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
  });
});
