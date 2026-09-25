import { useQuery } from "@tanstack/react-query";
import { Bus, Cpu, Radio, UserRound, Users, Contact, Navigation } from "lucide-react";
import { StatCard } from "../../shared/components/StatCard/StatCard";
import type { OffsetListParams } from "../../shared/api/listParams";
import { listVehicles } from "../../features/fleet-devices/vehicles/api";
import { listDevices } from "../../features/fleet-devices/devices/api";
import { listDrivers } from "../../features/transport-ops/drivers/api";
import { listRoutes } from "../../features/transport-ops/routes/api";
import { listTrips } from "../../features/transport-ops/trips/api";
import { listStudents } from "../../features/transport-ops/students/api";
import { listParents } from "../../features/transport-ops/parents/api";
import styles from "./OrganizationOverviewSection.module.css";

const COUNT_ONLY_PARAMS: OffsetListParams = { page: 1, pageSize: 1, sort: null, filters: {}, search: "" };
const ACTIVE_VEHICLES_PARAMS: OffsetListParams = {
  page: 1,
  pageSize: 1,
  sort: null,
  filters: { status: "active" },
  search: "",
};
const ACTIVE_TRIPS_PARAMS: OffsetListParams = {
  page: 1,
  pageSize: 1,
  sort: null,
  filters: { status: "in_progress" },
  search: "",
};

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/** A card's badge and footnote describe its count, so they are shown only once that count is
 * actually known — on a failed request "No drivers registered" would contradict the "—" value,
 * and a failed active-vehicles count must never read as "All Active". */
function isKnown(query: { isError: boolean; data: number | undefined }): boolean {
  return !query.isError && query.data !== undefined;
}

/** `whenSome`/`whenNone` for a known count, nothing while it is loading or failed. */
function describe(
  query: { isError: boolean; data: number | undefined },
  whenSome: string,
  whenNone: string,
): string | undefined {
  if (!isKnown(query)) return undefined;
  return (query.data ?? 0) > 0 ? whenSome : whenNone;
}

function formatVal(isError: boolean, data: number | undefined): string {
  if (isError) return "—";
  if (data === undefined) return "—";
  return numberFormatter.format(data);
}

export function OrganizationOverviewSection() {
  const vehiclesTotal = useQuery({
    queryKey: ["org-dashboard", "vehicles"],
    queryFn: async () => (await listVehicles(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const vehiclesActive = useQuery({
    queryKey: ["org-dashboard", "vehicles-active"],
    queryFn: async () => (await listVehicles(ACTIVE_VEHICLES_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const devicesTotal = useQuery({
    queryKey: ["org-dashboard", "devices"],
    queryFn: async () => (await listDevices(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const driversTotal = useQuery({
    queryKey: ["org-dashboard", "drivers"],
    queryFn: async () => (await listDrivers(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const tripsActive = useQuery({
    queryKey: ["org-dashboard", "active-trips"],
    queryFn: async () => (await listTrips(ACTIVE_TRIPS_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const studentsTotal = useQuery({
    queryKey: ["org-dashboard", "students"],
    queryFn: async () => (await listStudents(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const parentsTotal = useQuery({
    queryKey: ["org-dashboard", "parents"],
    queryFn: async () => (await listParents(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const routesTotal = useQuery({
    queryKey: ["org-dashboard", "routes"],
    queryFn: async () => (await listRoutes(COUNT_ONLY_PARAMS)).page.total,
    staleTime: 60_000,
  });

  const totalVehiclesCount = vehiclesTotal.data ?? 0;
  const activeVehiclesCount = vehiclesActive.data ?? 0;
  const standbyVehiclesCount = Math.max(0, totalVehiclesCount - activeVehiclesCount);

  const totalDevicesCount = devicesTotal.data ?? 0;
  const totalDriversCount = driversTotal.data ?? 0;
  const activeTripsCount = tripsActive.data ?? 0;

  const totalStudentsCount = studentsTotal.data ?? 0;
  const totalParentsCount = parentsTotal.data ?? 0;
  const totalRoutesCount = routesTotal.data ?? 0;

  return (
    <div className={styles.container}>
      {/* Row 1: Core Fleet Operations (4 cards) */}
      <div className={styles.group}>
        <div className={styles.groupHeader}>
          <span className={styles.groupLabel}>Core Fleet Operations</span>
        </div>
        <div className={styles.fleetGrid}>
          <StatCard
            icon={<Bus size={18} />}
            tone="brand"
            label="Vehicles"
            isLoading={vehiclesTotal.isLoading}
            value={formatVal(vehiclesTotal.isError, vehiclesTotal.data)}
            meta={
              isKnown(vehiclesTotal) && isKnown(vehiclesActive) && totalVehiclesCount > 0
                ? activeVehiclesCount === totalVehiclesCount
                  ? "All Active"
                  : `${activeVehiclesCount} Active`
                : undefined
            }
            metaTone={activeVehiclesCount > 0 ? "success" : "neutral"}
            footnote={
              !isKnown(vehiclesTotal)
                ? undefined
                : totalVehiclesCount === 0
                  ? "No fleet vehicles registered"
                  : isKnown(vehiclesActive)
                    ? `${activeVehiclesCount} active · ${standbyVehiclesCount} standby`
                    : `${totalVehiclesCount} registered`
            }
          />

          <StatCard
            icon={<Cpu size={18} />}
            tone="brand"
            label="Devices"
            isLoading={devicesTotal.isLoading}
            value={formatVal(devicesTotal.isError, devicesTotal.data)}
            meta={describe(devicesTotal, "Hardware", "None")}
            metaTone={totalDevicesCount > 0 ? "brand" : "neutral"}
            footnote={describe(devicesTotal, "MDVR & GPS telematics terminals", "No devices connected")}
          />

          <StatCard
            icon={<UserRound size={18} />}
            tone="brand"
            label="Drivers"
            isLoading={driversTotal.isLoading}
            value={formatVal(driversTotal.isError, driversTotal.data)}
            meta={describe(driversTotal, "Certified", "None")}
            metaTone={totalDriversCount > 0 ? "brand" : "neutral"}
            footnote={describe(driversTotal, "School bus operators assigned", "No drivers registered")}
          />

          <StatCard
            icon={<Radio size={18} />}
            tone={activeTripsCount > 0 ? "success" : "brand"}
            label="Active Trips"
            isLoading={tripsActive.isLoading}
            value={formatVal(tripsActive.isError, tripsActive.data)}
            meta={describe(tripsActive, "On Route", "Standby")}
            metaTone={activeTripsCount > 0 ? "success" : "neutral"}
            footnote={describe(
              tripsActive,
              `${activeTripsCount} buses currently on route`,
              "No active trips right now",
            )}
          />
        </div>
      </div>

      {/* Row 2: Transportation Overview (3 cards) */}
      <div className={styles.group}>
        <div className={styles.groupHeader}>
          <span className={styles.groupLabel}>Transportation Overview</span>
        </div>
        <div className={styles.transportGrid}>
          <StatCard
            icon={<Users size={18} />}
            tone="purple"
            label="Students"
            isLoading={studentsTotal.isLoading}
            value={formatVal(studentsTotal.isError, studentsTotal.data)}
            meta={describe(studentsTotal, "Riders", "None")}
            metaTone={totalStudentsCount > 0 ? "purple" : "neutral"}
            footnote={describe(studentsTotal, "Transportation enrolled riders", "No students registered")}
          />

          <StatCard
            icon={<Contact size={18} />}
            tone="brand"
            label="Parents"
            isLoading={parentsTotal.isLoading}
            value={formatVal(parentsTotal.isError, parentsTotal.data)}
            meta={describe(parentsTotal, "Linked", "None")}
            metaTone={totalParentsCount > 0 ? "brand" : "neutral"}
            footnote={describe(parentsTotal, "Linked parent & guardian accounts", "No guardian accounts")}
          />

          <StatCard
            icon={<Navigation size={18} />}
            tone="brand"
            label="Routes"
            isLoading={routesTotal.isLoading}
            value={formatVal(routesTotal.isError, routesTotal.data)}
            meta={describe(routesTotal, "Corridors", "None")}
            metaTone={totalRoutesCount > 0 ? "brand" : "neutral"}
            footnote={describe(routesTotal, "Configured transit routes & stops", "No routes configured")}
          />
        </div>
      </div>
    </div>
  );
}
