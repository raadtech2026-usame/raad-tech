import { useQuery } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { Badge } from "../../shared/components/Badge/Badge";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import { StatBar } from "./StatBar";
import sectionStyles from "./dashboard.module.css";
import styles from "./DeviceHealthSection.module.css";

/** `PlatformStats.systemHealth.{database,broker}` raw wire values -> badge tone/label — moved
 * here verbatim from the dashboard's own pre-redesign `PlatformAnalyticsSection` (the System
 * Health tile now lives in this dedicated panel instead of the top KPI row, alongside the device
 * online/offline breakdown it's most related to, rather than duplicated in both places). */
const HEALTH_BADGE_VARIANT: Record<string, "success" | "danger" | "neutral"> = {
  ok: "success",
  down: "danger",
  not_configured: "neutral",
};

const HEALTH_STATUS_LABEL: Record<string, string> = {
  ok: "Operational",
  down: "Down",
  not_configured: "Not configured",
};

/** Device connectivity (`PlatformStats.devices.{online,offline}`) plus the two infra dependency
 * checks (`HealthCheckService`, Priority 1 Item 5) — one panel for "is the device plane, and the
 * platform itself, actually healthy right now." Shares its query with the top KPI row and Live
 * Operations (same `queryKey`, React Query serves all three from one network call). */
export function DeviceHealthSection() {
  const { data, isLoading, isError, error } = useQuery<PlatformStats>({
    queryKey: ["platform-analytics-stats"],
    queryFn: getPlatformStats,
    staleTime: 60_000,
  });

  return (
    <Card>
      <CardHeader title="Device Health" />
      <div className={sectionStyles.panelBody}>
        {isError ? (
          <EmptyState
            icon={<Cpu size={20} />}
            title="Could not load device health"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading || !data ? (
          <>
            <Skeleton height={10} />
            <Skeleton height={13} width={140} />
          </>
        ) : (
          <>
            <StatBar
              items={[
                { key: "online", label: "Online", value: data.devices.online, tone: "success" },
                { key: "offline", label: "Offline", value: data.devices.offline, tone: "danger" },
              ]}
              emptyLabel="No devices allocated yet."
            />
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
          </>
        )}
      </div>
    </Card>
  );
}
