import { useQueries, useQuery } from "@tanstack/react-query";
import type { OffsetListParams } from "../../shared/api/listParams";
import { listVehicles, type VehicleStatus } from "../../features/fleet-devices/vehicles/api";
import { listTrips } from "../../features/transport-ops/trips/api";

const VEHICLE_STATUSES: VehicleStatus[] = ["active", "maintenance", "inactive"];

function countOnlyParams(filters: Record<string, string>): OffsetListParams {
  return { page: 1, pageSize: 1, sort: null, filters, search: "" };
}

export interface VehicleStatusCounts {
  active: number;
  maintenance: number;
  inactive: number;
  isLoading: boolean;
  isError: boolean;
}

/** Three `page_size=1` count-only reads against the already-existing, already-tested `GET
 * /vehicles` (`status` is a whitelisted filter field, confirmed against `fleet_device`'s own
 * repository) — the identical pattern `DashboardHomePage.tsx`'s own `PLATFORM_STATS` already
 * established for drivers, applied here since `PlatformStats` (ADR-0020) only carries a flat
 * vehicle total, no status breakdown. Shared by Live Operations' "vehicles active" stat and Fleet
 * Health's status bar — same `queryKey`s, so React Query serves both from one network call each. */
export function useVehicleStatusCounts(): VehicleStatusCounts {
  const results = useQueries({
    queries: VEHICLE_STATUSES.map((status) => ({
      queryKey: ["dashboard", "vehicle-status-count", status],
      queryFn: async () => (await listVehicles(countOnlyParams({ status }))).page.total,
      staleTime: 60_000,
    })),
  });

  const [active, maintenance, inactive] = results;
  return {
    active: active.data ?? 0,
    maintenance: maintenance.data ?? 0,
    inactive: inactive.data ?? 0,
    isLoading: results.some((r) => r.isLoading),
    isError: results.some((r) => r.isError),
  };
}

export interface TripsInProgress {
  total: number;
  /** The first in-progress trip's vehicle, if any — Live Operations' map preview subscribes to
   * this vehicle. `null` means "nothing to preview right now" (the common case outside active
   * service hours), not an error. */
  previewVehicleId: string | null;
  isLoading: boolean;
  isError: boolean;
}

/** One `GET /trips?filter[status]=in_progress&page_size=1` read serves both Live Operations'
 * "trips in progress" count (`page.total`) and its map preview's vehicle pick (`data[0]
 * .vehicleId`) — `status`/`vehicle_id` are both whitelisted filter/response fields already
 * (`transport-ops/trips/api.ts`'s own `listTrips` docstring). Not yet tenant-scoped server-side
 * (the same system-wide, already-flagged gap every list endpoint in this codebase carries), so
 * this picks the first in-progress trip across every organization — an honest reflection of what
 * the backend actually returns today, not a fabricated organization-scoped view. */
export function useTripsInProgress(): TripsInProgress {
  const query = useQuery({
    queryKey: ["dashboard", "trips-in-progress"],
    queryFn: () => listTrips(countOnlyParams({ status: "in_progress" })),
    staleTime: 30_000,
  });

  return {
    total: query.data?.page.total ?? 0,
    previewVehicleId: query.data?.data[0]?.vehicleId ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
