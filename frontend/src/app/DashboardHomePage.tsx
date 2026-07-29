import { useQueries } from "@tanstack/react-query";
import { Building2, Contact, Cpu, Truck, UserRound, Users, type LucideIcon } from "lucide-react";
import { useAuthStore } from "../shared/stores/authStore";
import { getRoleDisplay } from "../shared/auth/roleDisplay";
import { getDashboardType } from "../shared/auth/dashboard";
import { usePageHeader } from "./layout/PageHeaderContext";
import { Card } from "../shared/components/Card/Card";
import { Skeleton } from "../shared/components/Skeleton/Skeleton";
import type { OffsetListParams } from "../shared/api/listParams";
import { listOrganizations } from "../features/organizations/api";
import { listVehicles } from "../features/fleet-devices/vehicles/api";
import { listDevices } from "../features/fleet-devices/devices/api";
import { listDrivers } from "../features/transport-ops/drivers/api";
import { countStudents } from "../features/transport-ops/students/api";
import { countParents } from "../features/transport-ops/parents/api";
import styles from "./DashboardHomePage.module.css";

/** `page_size=1` against organizations/vehicles/devices/drivers' own already-existing,
 * already-tested list endpoints, reading only `.page.total` — no new backend endpoint for
 * these four. `sort: null` deliberately (not a fixed field like `created_at`) since each
 * resource's own sortable-field whitelist differs and every list route already falls back to a
 * safe default ordering when `sort` is omitted.
 *
 * Students/parents are different: RAAD Platform roles no longer hold `transport_ops.students
 * .list`/`.parents.list` at all (migration `c4d9a2e6f813`) — reusing the list endpoint here
 * would 403. `countStudents`/`countParents` (`GET /students/count`/`GET /parents/count`) are
 * the new, narrower, count-only routes/permissions added specifically to satisfy this KPI tile
 * without exposing individual rows — see those functions' own docstrings. */
const COUNT_ONLY_PARAMS: OffsetListParams = {
  page: 1,
  pageSize: 1,
  sort: null,
  filters: {},
  search: "",
};

interface PlatformStatDef {
  key: string;
  label: string;
  icon: LucideIcon;
  fetcher: () => Promise<number>;
}

const PLATFORM_STATS: PlatformStatDef[] = [
  {
    key: "organizations",
    label: "Total organizations",
    icon: Building2,
    fetcher: async () => (await listOrganizations(COUNT_ONLY_PARAMS)).page.total,
  },
  {
    key: "vehicles",
    label: "Total vehicles",
    icon: Truck,
    fetcher: async () => (await listVehicles(COUNT_ONLY_PARAMS)).page.total,
  },
  {
    key: "devices",
    label: "Total devices",
    icon: Cpu,
    fetcher: async () => (await listDevices(COUNT_ONLY_PARAMS)).page.total,
  },
  {
    key: "drivers",
    label: "Total drivers",
    icon: UserRound,
    fetcher: async () => (await listDrivers(COUNT_ONLY_PARAMS)).page.total,
  },
  {
    key: "students",
    label: "Total students",
    icon: Users,
    fetcher: countStudents,
  },
  {
    key: "parents",
    label: "Total parents",
    icon: Contact,
    fetcher: countParents,
  },
];

const numberFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});

/**
 * Platform-only KPI strip (`dashboardType === "platform"`) — a deliberate stopgap, not
 * ADR-0020 (Platform Analytics). ADR-0020 is a dedicated, `platform_audit`-owned, event-driven
 * read-model (real MAU, a genuine `DeviceOnline`/`DeviceOffline`-derived "online now" count) —
 * still not built. This strip is the much smaller thing: six plain counts. Four (organizations/
 * vehicles/devices/drivers) reuse each resource's own already-existing list endpoint's
 * `.page.total` — no new backend surface. Students/parents needed one small new backend
 * addition (`GET /students/count`/`GET /parents/count`, `transport_ops.students.count`/
 * `.parents.count`): RAAD Platform roles hold no `.list` permission for either anymore
 * (migration `c4d9a2e6f813`), so the count had to come from a narrower, list-free route —
 * see `countStudents`/`countParents`'s own docstrings. **No MAU, no "Platform Analytics"
 * section** — inventing either without an approved data model is exactly what
 * `.claude/rules/workflow.md` #8 forbids. Superseded by ADR-0020 whenever that milestone
 * lands; not a substitute for it.
 */
function PlatformStatsRow() {
  const results = useQueries({
    queries: PLATFORM_STATS.map((stat) => ({
      queryKey: ["platform-stats", stat.key],
      queryFn: stat.fetcher,
      staleTime: 60_000,
    })),
  });

  return (
    <div className={styles.statsGrid}>
      {PLATFORM_STATS.map((stat, index) => {
        const result = results[index];
        const Icon = stat.icon;
        return (
          <Card key={stat.key} padded className={styles.statCard}>
            <span className={styles.statIcon}>
              <Icon size={18} />
            </span>
            <div className={styles.statText}>
              <span className={styles.statLabel}>{stat.label}</span>
              {result.isLoading ? (
                <Skeleton width={48} height={24} />
              ) : (
                <span className={styles.statValue}>
                  {result.isError ? "—" : numberFormatter.format(result.data ?? 0)}
                </span>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/**
 * Fleet/trip/rider KPI numbers beyond the platform stats row below still don't appear here —
 * the approved design's dashboard mockup shows fixed sample figures ("48 trips today", "18
 * live"), but no aggregate summary endpoint exists on the backend to back those specific ones
 * for real. Fabricating numbers here would violate this project's own "fail loudly, don't fake
 * it" posture; that fuller KPI grid lands once its own feature phase does.
 */
export function DashboardHomePage() {
  const principal = useAuthStore((s) => s.principal);
  const dashboardType = principal ? getDashboardType(principal.role) : "platform";
  const roleDisplay = principal ? getRoleDisplay(principal.role) : null;

  usePageHeader(
    "Dashboard",
    dashboardType === "platform" ? "RAAD platform overview" : "Your organization at a glance",
  );

  return (
    <div className={styles.grid}>
      <Card className={styles.welcomeCard}>
        <div className={styles.welcomeTitle}>Welcome{roleDisplay ? `, ${roleDisplay.label}` : ""}</div>
        <p className={styles.welcomeBody}>
          {dashboardType === "platform"
            ? "This is the RAAD platform console. Fleet, tracking, billing, and reporting summaries will appear here as each module comes online."
            : "This is your organization's console. Fleet, tracking, and rider summaries for your organization will appear here as each module comes online."}
        </p>
      </Card>

      {dashboardType === "platform" && <PlatformStatsRow />}
    </div>
  );
}
