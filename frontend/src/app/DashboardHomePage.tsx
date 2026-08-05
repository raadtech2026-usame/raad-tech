import { useQueries, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity,
  Building2,
  Contact,
  Cpu,
  DollarSign,
  Truck,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useAuthStore } from "../shared/stores/authStore";
import { getRoleDisplay } from "../shared/auth/roleDisplay";
import { getDashboardType } from "../shared/auth/dashboard";
import { usePageHeader } from "./layout/PageHeaderContext";
import { Avatar } from "../shared/components/Avatar/Avatar";
import { Badge } from "../shared/components/Badge/Badge";
import { Card } from "../shared/components/Card/Card";
import { EmptyState } from "../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../shared/components/Skeleton/Skeleton";
import { ApiError } from "../shared/api/types";
import type { OffsetListParams } from "../shared/api/listParams";
import { listDrivers } from "../features/transport-ops/drivers/api";
import { countStudents } from "../features/transport-ops/students/api";
import { countParents } from "../features/transport-ops/parents/api";
import { getPlatformStats, type PlatformStats } from "../features/platform-analytics/api";
import styles from "./DashboardHomePage.module.css";

/** `page_size=1` against drivers' own already-existing, already-tested list endpoint, reading
 * only `.page.total` — no new backend endpoint needed. `sort: null` deliberately (not a fixed
 * field like `created_at`) since each resource's own sortable-field whitelist differs and every
 * list route already falls back to a safe default ordering when `sort` is omitted.
 *
 * Students/parents are different: RAAD Platform roles no longer hold `transport_ops.students
 * .list`/`.parents.list` at all (migration `c4d9a2e6f813`) — reusing the list endpoint here
 * would 403. `countStudents`/`countParents` (`GET /students/count`/`GET /parents/count`) are
 * the new, narrower, count-only routes/permissions added specifically to satisfy this KPI tile
 * without exposing individual rows — see those functions' own docstrings.
 *
 * Organizations/vehicles/devices previously lived in this same stopgap row (their own list
 * endpoint's `.page.total`) — **superseded by ADR-0020** (`PlatformAnalyticsSection` below),
 * which gets richer data (status breakdowns, online/offline) this flat-total approach never
 * could. Drivers/students/parents stay here — outside ADR-0020's own four-module scope
 * (`platform_audit.application.queries.PlatformStatsDTO`'s own docstring flags "Active Drivers"
 * as a deliberate, named scope cut), so this remains the correct, only source for them. */
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

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

const HEALTH_BADGE_VARIANT: Record<string, "success" | "danger" | "neutral"> = {
  ok: "success",
  down: "danger",
  not_configured: "neutral",
};

/** Human labels for `PlatformStats.systemHealth.{database,broker}` — the raw wire values
 * (`"ok"|"down"|"not_configured"`) used to be the badge's own visible text, which meant a viewer
 * could only tell a dependency's actual status from the dot color, never from what the badge
 * said (the badge read "Database"/"Broker", the *row* label, not the *status*). Fixed so status
 * is legible without relying on color alone. */
const HEALTH_STATUS_LABEL: Record<string, string> = {
  ok: "Operational",
  down: "Down",
  not_configured: "Not configured",
};

/**
 * ADR-0020 platform-wide KPI grid — `GET /admin/platform-stats`, one query backing every tile
 * here (unlike the six-separate-fetcher stopgap `PlatformStatsRow` above). Two KPIs the ADR's
 * own Context names ("Live Vehicle Locations", "Active Drivers") are a real, flagged scope cut —
 * see `PlatformStats`'s own docstring — and simply don't appear here, not represented as a
 * fabricated zero.
 *
 * On failure, shows the same `EmptyState` "Could not load X" pattern every other feature page's
 * list view already uses (`OrganizationsPage.tsx` etc.) — silently rendering `null` here would
 * make any real failure (a permission change, the backend being briefly unreachable) look
 * identical to "not built yet," with no way to tell the two apart from the UI alone.
 */
function PlatformAnalyticsSection() {
  const { data, isLoading, isError, error } = useQuery<PlatformStats>({
    queryKey: ["platform-analytics-stats"],
    queryFn: getPlatformStats,
    staleTime: 60_000,
  });

  if (isError) {
    return (
      <Card padded>
        <EmptyState
          icon={<Activity size={22} />}
          title="Could not load platform analytics"
          description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
        />
      </Card>
    );
  }

  // "down" (a real dependency failure) gets the alert treatment; "not_configured" (an expected,
  // disclosed state in this dev/sandbox environment — see CLAUDE.md's Redis/broker notes) does
  // not, so an optional, intentionally-unbound dependency never reads as an incident.
  const health = data?.systemHealth;
  const hasHealthIssue = !!health && (health.database === "down" || health.broker === "down");

  return (
    <div className={styles.section}>
      <span className={styles.sectionLabel}>Platform overview</span>
      <div className={styles.statsGrid}>
        <Card padded className={clsx(styles.statCard, styles.tileWide)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <Building2 size={18} />
            </span>
            <span className={styles.statLabel}>Organizations</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <span className={styles.statValue}>{numberFormatter.format(data.organizations.total)}</span>
          )}
          {isLoading || !data ? (
            <Skeleton width={130} height={13} />
          ) : (
            <span className={styles.statSubtext}>
              {data.organizations.byStatus.active ?? 0} active · {data.organizations.createdToday}{" "}
              new today
            </span>
          )}
        </Card>

        <Card padded className={clsx(styles.statCard, styles.tileWide)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <Cpu size={18} />
            </span>
            <span className={styles.statLabel}>Devices</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <span className={styles.statValue}>{numberFormatter.format(data.devices.total)}</span>
          )}
          {isLoading || !data ? (
            <Skeleton width={130} height={13} />
          ) : (
            <span className={styles.statSubtext}>
              {data.devices.online} online · {data.devices.offline} offline
            </span>
          )}
        </Card>

        <Card padded className={clsx(styles.statCard, styles.tileWide)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <Truck size={18} />
            </span>
            <span className={styles.statLabel}>Vehicles</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <span className={styles.statValue}>{numberFormatter.format(data.vehicles.total)}</span>
          )}
          <span className={styles.statSubtext}>&nbsp;</span>
        </Card>

        <Card padded className={clsx(styles.statCard, styles.tileWide)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <Users size={18} />
            </span>
            <span className={styles.statLabel}>Users</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <span className={styles.statValue}>{numberFormatter.format(data.users.total)}</span>
          )}
          {isLoading || !data ? (
            <Skeleton width={130} height={13} />
          ) : (
            <span className={styles.statSubtext}>
              {numberFormatter.format(data.users.monthlyActive)} MAU · {data.users.createdToday}{" "}
              new today
            </span>
          )}
        </Card>

        <Card padded className={clsx(styles.statCard, styles.tileWide)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <DollarSign size={18} />
            </span>
            <span className={styles.statLabel}>Revenue (month to date)</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <span className={styles.statValue}>{currencyFormatter.format(data.billing.revenue)}</span>
          )}
          {isLoading || !data ? (
            <Skeleton width={130} height={13} />
          ) : (
            <span className={styles.statSubtext}>
              {data.billing.expiringSoon} subscription(s) expiring soon
            </span>
          )}
        </Card>

        <Card padded className={clsx(styles.statCard, styles.tileWide, hasHealthIssue && styles.statCardAlert)}>
          <div className={styles.statCardHead}>
            <span className={styles.statIcon}>
              <Activity size={18} />
            </span>
            <span className={styles.statLabel}>System health</span>
          </div>
          {isLoading || !data ? (
            <Skeleton width={64} height={30} />
          ) : (
            <div className={styles.healthRows}>
              <div className={styles.healthRow}>
                <span className={styles.healthRowLabel}>Database</span>
                <Badge variant={HEALTH_BADGE_VARIANT[data.systemHealth.database] ?? "neutral"} dot>
                  {HEALTH_STATUS_LABEL[data.systemHealth.database] ?? data.systemHealth.database}
                </Badge>
              </div>
              <div className={styles.healthRow}>
                <span className={styles.healthRowLabel}>Broker</span>
                <Badge variant={HEALTH_BADGE_VARIANT[data.systemHealth.broker] ?? "neutral"} dot>
                  {HEALTH_STATUS_LABEL[data.systemHealth.broker] ?? data.systemHealth.broker}
                </Badge>
              </div>
            </div>
          )}
          <span className={styles.statSubtext}>&nbsp;</span>
        </Card>
      </div>
    </div>
  );
}

/**
 * Platform-only KPI strip (`dashboardType === "platform"`) — the remainder of what used to be a
 * six-tile stopgap before ADR-0020 landed (`PlatformAnalyticsSection` above now covers
 * organizations/devices/vehicles/users/billing/system-health with real breakdowns, not flat
 * totals). What's left here — drivers/students/parents — stays on this same simple
 * per-tile-fetcher shape: `listDrivers`'s own `.page.total` for drivers; `countStudents`/
 * `countParents` (`GET /students/count`/`GET /parents/count`) for students/parents, since RAAD
 * Platform roles hold no `transport_ops.students.list`/`.parents.list` permission (migration
 * `c4d9a2e6f813`), so reusing the list endpoint would 403. Not superseded by ADR-0020 — its own
 * `PlatformStatsDTO` docstring flags "Active Drivers" as a deliberate scope cut (no module
 * named in the ADR's own §1 Decision covers it), and students/parents were never part of its
 * scope at all.
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
    <div className={styles.section}>
      <span className={styles.sectionLabel}>People</span>
      <div className={styles.statsGrid}>
        {PLATFORM_STATS.map((stat, index) => {
          const result = results[index];
          const Icon = stat.icon;
          return (
            <Card key={stat.key} padded className={clsx(styles.statCard, styles.tileNarrow)}>
              <div className={styles.statCardHead}>
                <span className={styles.statIcon}>
                  <Icon size={18} />
                </span>
                <span className={styles.statLabel}>{stat.label}</span>
              </div>
              {result.isLoading ? (
                <Skeleton width={64} height={30} />
              ) : (
                <span className={styles.statValue}>
                  {result.isError ? "—" : numberFormatter.format(result.data ?? 0)}
                </span>
              )}
              <span className={styles.statSubtext}>&nbsp;</span>
            </Card>
          );
        })}
      </div>
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
    <div className={clsx(styles.page, "raad-view-transition")}>
      <Card className={styles.welcomeCard}>
        {roleDisplay && <Avatar initials={roleDisplay.abbreviation} color={roleDisplay.color} size="lg" />}
        <div className={styles.welcomeText}>
          <span className={styles.welcomeTitle}>Welcome{roleDisplay ? `, ${roleDisplay.label}` : ""}</span>
          <p className={styles.welcomeBody}>
            {dashboardType === "platform"
              ? "This is the RAAD platform console. Fleet, tracking, billing, and reporting summaries will appear here as each module comes online."
              : "This is your organization's console. Fleet, tracking, and rider summaries for your organization will appear here as each module comes online."}
          </p>
        </div>
      </Card>

      {dashboardType === "platform" && (
        <>
          <PlatformAnalyticsSection />
          <PlatformStatsRow />
        </>
      )}
    </div>
  );
}
