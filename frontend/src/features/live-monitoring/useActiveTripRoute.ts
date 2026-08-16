import { useQuery } from "@tanstack/react-query";
import { getActiveTripRouteId, getRouteWithStops, type RouteStop } from "./api";

export interface UseActiveTripRouteResult {
  routeStops: RouteStop[] | null;
}

/** ADR-0028 §G: the route/stop overlay half of `LiveTrackingPage`, extracted unchanged in
 * behavior — resolves the vehicle's current in-progress trip's route, if any, for
 * `VehicleMapPanel`'s own line/point layers. Context only, never live geofence *events* (the
 * original page's own note: geofence-crossing generation is dead code anywhere in this platform
 * today, so there is nothing live to show). */
export function useActiveTripRoute(vehicleId: string): UseActiveTripRouteResult {
  const activeTripQuery = useQuery({
    queryKey: ["tracking", "active-trip", vehicleId],
    queryFn: () => getActiveTripRouteId(vehicleId),
    enabled: vehicleId !== "",
  });

  const routeQuery = useQuery({
    queryKey: ["tracking", "route", activeTripQuery.data],
    queryFn: () => getRouteWithStops(activeTripQuery.data as string),
    enabled: !!activeTripQuery.data,
  });

  return { routeStops: routeQuery.data?.stops ?? null };
}
