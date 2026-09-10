import { useQuery } from "@tanstack/react-query";
import { Activity, Building2, Cpu, Truck, Users } from "lucide-react";
import { Card } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { StatCard } from "../../shared/components/StatCard/StatCard";
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
 *
 * 2026-09-05: the four hand-built tiles became four `StatCard`s. The `meta` pill shows a real
 * secondary figure the same payload already carries (active organizations, online devices, MAU)
 * — never a period-over-period delta, because no endpoint in this product returns one.
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

  const pending = isLoading || !data;
  const activeOrganizations = data?.organizations.byStatus.active ?? 0;

  return (
    <div className={styles.grid}>
      <StatCard
        icon={<Building2 size={18} />}
        tone="brand"
        label="Organizations"
        isLoading={pending}
        value={data ? numberFormatter.format(data.organizations.total) : "—"}
        meta={data ? `${numberFormatter.format(activeOrganizations)} active` : undefined}
        metaTone={activeOrganizations > 0 ? "success" : "neutral"}
        footnote={data ? `${data.organizations.createdToday} new today` : undefined}
      />

      <StatCard
        icon={<Truck size={18} />}
        tone="brand"
        label="Vehicles"
        isLoading={pending}
        value={data ? numberFormatter.format(data.vehicles.total) : "—"}
        // `PlatformStats.vehicles` carries a flat total and nothing else (ADR-0020) — there is
        // no status breakdown on this payload to put in a pill, and Fleet Health below is the
        // panel that legitimately answers that question.
        footnote="Registered across every organization"
      />

      <StatCard
        icon={<Cpu size={18} />}
        tone="brand"
        label="Devices"
        isLoading={pending}
        value={data ? numberFormatter.format(data.devices.total) : "—"}
        meta={data ? `${data.devices.online} online` : undefined}
        metaTone={data && data.devices.offline > 0 ? "warning" : "success"}
        footnote={data ? `${data.devices.offline} currently offline` : undefined}
      />

      <StatCard
        icon={<Users size={18} />}
        tone="brand"
        label="Users"
        isLoading={pending}
        value={data ? numberFormatter.format(data.users.total) : "—"}
        meta={data ? `${numberFormatter.format(data.users.monthlyActive)} MAU` : undefined}
        metaTone="brand"
        footnote={data ? `${data.users.createdToday} new today` : undefined}
      />
    </div>
  );
}
