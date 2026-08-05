import { useQuery } from "@tanstack/react-query";
import { Activity, Building2, Cpu, Truck, Users } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import styles from "./KpiSection.module.css";

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/**
 * The top KPI row — platform scale at a glance. Revenue and System Health deliberately don't
 * repeat here: they get their own, richer dedicated panels further down the page (Billing's
 * `RevenueSummaryCard`, `DeviceHealthSection`) instead of a duplicate flat number in both places.
 * Same `GET /admin/platform-stats` query every other dashboard panel shares (identical
 * `queryKey`, so this costs zero extra network calls beyond the first).
 */
export function KpiSection() {
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

  return (
    <div className={styles.grid}>
      <Card padded className={styles.tile}>
        <div className={styles.head}>
          <span className={styles.icon}>
            <Building2 size={20} />
          </span>
          <span className={styles.label}>Organizations</span>
        </div>
        {isLoading || !data ? (
          <Skeleton width={80} height={38} />
        ) : (
          <span className={styles.value}>{numberFormatter.format(data.organizations.total)}</span>
        )}
        {isLoading || !data ? (
          <Skeleton width={140} height={13} />
        ) : (
          <span className={styles.subtext}>
            {data.organizations.byStatus.active ?? 0} active · {data.organizations.createdToday} new today
          </span>
        )}
      </Card>

      <Card padded className={styles.tile}>
        <div className={styles.head}>
          <span className={styles.icon}>
            <Truck size={20} />
          </span>
          <span className={styles.label}>Vehicles</span>
        </div>
        {isLoading || !data ? (
          <Skeleton width={80} height={38} />
        ) : (
          <span className={styles.value}>{numberFormatter.format(data.vehicles.total)}</span>
        )}
        <span className={styles.subtext}>&nbsp;</span>
      </Card>

      <Card padded className={styles.tile}>
        <div className={styles.head}>
          <span className={styles.icon}>
            <Cpu size={20} />
          </span>
          <span className={styles.label}>Devices</span>
        </div>
        {isLoading || !data ? (
          <Skeleton width={80} height={38} />
        ) : (
          <span className={styles.value}>{numberFormatter.format(data.devices.total)}</span>
        )}
        {isLoading || !data ? (
          <Skeleton width={140} height={13} />
        ) : (
          <span className={styles.subtext}>
            {data.devices.online} online · {data.devices.offline} offline
          </span>
        )}
      </Card>

      <Card padded className={styles.tile}>
        <div className={styles.head}>
          <span className={styles.icon}>
            <Users size={20} />
          </span>
          <span className={styles.label}>Users</span>
        </div>
        {isLoading || !data ? (
          <Skeleton width={80} height={38} />
        ) : (
          <span className={styles.value}>{numberFormatter.format(data.users.total)}</span>
        )}
        {isLoading || !data ? (
          <Skeleton width={140} height={13} />
        ) : (
          <span className={styles.subtext}>
            {numberFormatter.format(data.users.monthlyActive)} MAU · {data.users.createdToday} new today
          </span>
        )}
      </Card>
    </div>
  );
}
