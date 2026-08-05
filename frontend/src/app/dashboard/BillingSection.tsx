import { useQuery } from "@tanstack/react-query";
import { CreditCard, DollarSign } from "lucide-react";
import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import { StatBar, type StatBarItem } from "./StatBar";
import sectionStyles from "./dashboard.module.css";

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

/** `billing.domain.value_objects.SubscriptionStatus` — no `features/billing/` folder exists yet
 * (F9, not started per `PROJECT_STATUS.md`), so unlike Vehicles/Users/Organizations there's no
 * existing `labels.ts` to reuse; this is the same small, self-contained mapping every other
 * feature folder in this codebase already keeps for its own status enum. */
const SUBSCRIPTION_STATUS_LABEL: Record<string, string> = {
  trial: "Trial",
  active: "Active",
  suspended: "Suspended",
  expired: "Expired",
  cancelled: "Cancelled",
};

const SUBSCRIPTION_STATUS_TONE: Record<string, BadgeVariant> = {
  trial: "info",
  active: "success",
  suspended: "warning",
  expired: "danger",
  cancelled: "neutral",
};

function usePlatformStats() {
  return useQuery<PlatformStats>({
    queryKey: ["platform-analytics-stats"],
    queryFn: getPlatformStats,
    staleTime: 60_000,
  });
}

/** Subscription status breakdown (`PlatformStats.billing.subscriptionByStatus`) — an arbitrary
 * `Record<string, number>` of whichever statuses actually have rows today, never a hardcoded
 * five-item list (a fresh deployment may show only `active`, or nothing at all). */
export function SubscriptionSummaryCard() {
  const { data, isLoading, isError, error } = usePlatformStats();

  const items: StatBarItem[] = data
    ? Object.entries(data.billing.subscriptionByStatus).map(([status, value]) => ({
        key: status,
        label: SUBSCRIPTION_STATUS_LABEL[status] ?? status,
        value,
        tone: SUBSCRIPTION_STATUS_TONE[status] ?? "neutral",
      }))
    : [];

  return (
    <Card>
      <CardHeader title="Subscriptions" />
      <div className={sectionStyles.panelBody}>
        {isError ? (
          <EmptyState
            icon={<CreditCard size={20} />}
            title="Could not load subscriptions"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading || !data ? (
          <Skeleton height={10} />
        ) : (
          <>
            <StatBar items={items} emptyLabel="No subscriptions opened yet." />
            {data.billing.expiringSoon > 0 && (
              <p className={sectionStyles.panelStatCaption}>
                {data.billing.expiringSoon} subscription{data.billing.expiringSoon === 1 ? "" : "s"} expiring soon
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

/** Month-to-date revenue (`PlatformStats.billing.revenue`) — a single point-in-time total, the
 * only revenue figure this backend currently computes (`platform_audit.PlatformStatsApplication
 * Service`, ADR-0020). No trend/history endpoint exists, so this deliberately shows one clear
 * number rather than fabricating a sparkline from data that isn't there. */
export function RevenueSummaryCard() {
  const { data, isLoading, isError, error } = usePlatformStats();

  return (
    <Card>
      <CardHeader title="Revenue" />
      <div className={sectionStyles.panelBody}>
        {isError ? (
          <EmptyState
            icon={<DollarSign size={20} />}
            title="Could not load revenue"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading || !data ? (
          <Skeleton height={36} width={140} />
        ) : (
          <>
            <div className={sectionStyles.panelStat}>
              <span className={sectionStyles.panelStatValue}>{currencyFormatter.format(data.billing.revenue)}</span>
            </div>
            <p className={sectionStyles.panelStatCaption}>Month to date, across every organization</p>
          </>
        )}
      </div>
    </Card>
  );
}
