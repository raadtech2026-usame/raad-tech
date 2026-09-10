import { useQueries } from "@tanstack/react-query";
import { Bus, Cpu, Navigation, UserRound, Users, Contact, type LucideIcon } from "lucide-react";
import { StatCard } from "../../shared/components/StatCard/StatCard";
import type { OffsetListParams } from "../../shared/api/listParams";
import { listVehicles } from "../../features/fleet-devices/vehicles/api";
import { listDevices } from "../../features/fleet-devices/devices/api";
import { listDrivers } from "../../features/transport-ops/drivers/api";
import { listRoutes } from "../../features/transport-ops/routes/api";
import { listTrips } from "../../features/transport-ops/trips/api";
import { listStudents } from "../../features/transport-ops/students/api";
import { listParents } from "../../features/transport-ops/parents/api";
import styles from "./KpiSection.module.css";

/**
 * The Organization Dashboard's own KPI row (Org Admin's `/org` home — distinct from the platform
 * `KpiSection` above, which reads `GET /admin/platform-stats` and is cross-organization by
 * design). No such platform-wide endpoint is reachable here — `platform_stats` requires
 * `admin.platform_stats.read`, which Org Admin does not hold — so every figure below is
 * `page_size=1` against that resource's own already-existing, already-tenant-scoped list
 * endpoint, reading only `.page.total`, the identical pattern `PeopleSection` already
 * established for the platform dashboard's own People row. All seven confirmed live (2026-09-10)
 * against a real Org Admin token: `/vehicles`, `/devices`, `/drivers`, `/routes`, `/trips`,
 * `/students`, `/parents` all return 200 for this role (unlike the platform-only `GET /students/
 * count`/`GET /parents/count`, which 403 for Org Admin — `listStudents`/`listParents` are used
 * here instead, not `countStudents`/`countParents`).
 *
 * **"Active Trips" filters `status=in_progress`** — the one figure here that is a count of a
 * subset rather than everything, since "how many buses are on the road right now" is a
 * materially different question from "how many trips have ever been scheduled."
 */
const COUNT_ONLY_PARAMS: OffsetListParams = { page: 1, pageSize: 1, sort: null, filters: {}, search: "" };
const ACTIVE_TRIPS_PARAMS: OffsetListParams = {
  page: 1,
  pageSize: 1,
  sort: null,
  filters: { status: "in_progress" },
  search: "",
};

interface OrgStatDef {
  key: string;
  label: string;
  icon: LucideIcon;
  fetcher: () => Promise<number>;
}

const ORG_STATS: OrgStatDef[] = [
  { key: "vehicles", label: "Vehicles", icon: Bus, fetcher: async () => (await listVehicles(COUNT_ONLY_PARAMS)).page.total },
  { key: "devices", label: "Devices", icon: Cpu, fetcher: async () => (await listDevices(COUNT_ONLY_PARAMS)).page.total },
  { key: "drivers", label: "Drivers", icon: UserRound, fetcher: async () => (await listDrivers(COUNT_ONLY_PARAMS)).page.total },
  { key: "routes", label: "Routes", icon: Navigation, fetcher: async () => (await listRoutes(COUNT_ONLY_PARAMS)).page.total },
  { key: "active-trips", label: "Active trips", icon: Navigation, fetcher: async () => (await listTrips(ACTIVE_TRIPS_PARAMS)).page.total },
  { key: "students", label: "Students", icon: Users, fetcher: async () => (await listStudents(COUNT_ONLY_PARAMS)).page.total },
  { key: "parents", label: "Parents", icon: Contact, fetcher: async () => (await listParents(COUNT_ONLY_PARAMS)).page.total },
];

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function OrganizationOverviewSection() {
  const results = useQueries({
    queries: ORG_STATS.map((stat) => ({
      queryKey: ["org-dashboard", stat.key],
      queryFn: stat.fetcher,
      staleTime: 60_000,
    })),
  });

  return (
    <div className={styles.grid}>
      {ORG_STATS.map((stat, index) => {
        const result = results[index];
        const Icon = stat.icon;
        return (
          <StatCard
            key={stat.key}
            icon={<Icon size={18} />}
            tone="brand"
            label={stat.label}
            isLoading={result.isLoading}
            // An em dash on error, never a zero — a permission/network failure and "genuinely
            // zero" must not render identically.
            value={result.isError ? "—" : numberFormatter.format(result.data ?? 0)}
          />
        );
      })}
    </div>
  );
}
