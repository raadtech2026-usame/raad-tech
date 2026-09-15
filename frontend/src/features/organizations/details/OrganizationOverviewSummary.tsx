import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bus, CreditCard, UserCog, Users } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { StatCard } from "../../../shared/components/StatCard/StatCard";
import { formatAmount, formatDateOnly } from "../../billing/format";
import { billingCycleLabel, subscriptionStatusLabel, subscriptionStatusTone } from "../../billing/labels";
import type { Subscription } from "../../billing/api";
import { orgParentCount, orgPlanCatalog, orgStudentCount, orgSubscriptions, orgUsers, orgVehicles } from "./api";
import type { OrganizationDetailTabId } from "./tabs";
import styles from "./OrganizationDetailsPage.module.css";

const NON_TERMINAL: ReadonlySet<Subscription["status"]> = new Set([
  "trial",
  "active",
  "past_due",
  "grace_period",
  "suspended",
]);

const LIST_ONE = { page: 1, pageSize: 1, sort: null, filters: {}, search: "" };

export interface OrganizationOverviewSummaryProps {
  organizationId: string;
  onSelectTab: (tab: OrganizationDetailTabId) => void;
}

/**
 * Organization Overview's own Subscription/Trial and Usage summary blocks (Organization
 * Management phase) — a compact preview of what the Subscription and Usage tabs show in full,
 * so a Founder doesn't have to leave Overview to see whether an organization is current on its
 * plan and roughly how big it is. Every figure is a real read through this page's own composed
 * client (`./api.ts`) — no new endpoint, no invented metric. Deliberately does **not** duplicate
 * Devices or Routes here (Part 6's own constraint): those stay full tabs, never Overview items.
 */
export function OrganizationOverviewSummary({
  organizationId,
  onSelectTab,
}: OrganizationOverviewSummaryProps) {
  const base = ["organizations", "detail", organizationId] as const;

  const subscriptionsQuery = useQuery({
    queryKey: [...base, "subscriptions", "overview-summary"],
    queryFn: () => orgSubscriptions(organizationId),
    staleTime: 30_000,
  });
  const subscription = useMemo(() => {
    const rows = subscriptionsQuery.data?.data ?? [];
    return rows.find((s) => NON_TERMINAL.has(s.status)) ?? rows[0] ?? null;
  }, [subscriptionsQuery.data]);

  const plansQuery = useQuery({
    queryKey: ["organizations", "detail", organizationId, "plan-catalog"],
    queryFn: orgPlanCatalog,
    staleTime: 60_000,
    enabled: Boolean(subscription),
  });
  const plan = plansQuery.data?.data.find((p) => p.id === subscription?.planId) ?? null;

  const usersQuery = useQuery({
    queryKey: [...base, "overview-usage", "users"],
    queryFn: () => orgUsers(organizationId, LIST_ONE),
    staleTime: 60_000,
  });
  const vehiclesQuery = useQuery({
    queryKey: [...base, "overview-usage", "vehicles"],
    queryFn: () => orgVehicles(organizationId, LIST_ONE),
    staleTime: 60_000,
  });
  const studentsQuery = useQuery({
    queryKey: [...base, "overview-usage", "students"],
    queryFn: () => orgStudentCount(organizationId),
    staleTime: 60_000,
  });
  const parentsQuery = useQuery({
    queryKey: [...base, "overview-usage", "parents"],
    queryFn: () => orgParentCount(organizationId),
    staleTime: 60_000,
  });

  return (
    <div className={styles.stack}>
      <section>
        <div className={styles.summaryHeader}>
          <h3 className={styles.sectionTitle}>Subscription</h3>
          <Button variant="ghost" size="sm" onClick={() => onSelectTab("subscription")}>
            View subscription →
          </Button>
        </div>
        {subscriptionsQuery.isPending ? (
          <Skeleton height={80} />
        ) : !subscription ? (
          <p className={styles.muted}>No RAAD subscription — this organization's users cannot open the dashboard.</p>
        ) : (
          <dl className={styles.detail}>
            <div>
              <dt>Status</dt>
              <dd>
                <Badge variant={subscriptionStatusTone(subscription.status)} dot>
                  {subscriptionStatusLabel(subscription.status)}
                </Badge>
              </dd>
            </div>
            <div>
              <dt>Plan</dt>
              <dd>{plan?.name ?? subscription.planId}</dd>
            </div>
            <div>
              <dt>Amount</dt>
              <dd>{plan ? `${formatAmount(plan.amount, plan.currency)} / ${billingCycleLabel(plan.billingCycle)}` : "—"}</dd>
            </div>
            <div>
              <dt>Next renewal</dt>
              <dd>{subscription.currentPeriodEnd ? formatDateOnly(subscription.currentPeriodEnd) : "—"}</dd>
            </div>
          </dl>
        )}
      </section>

      <section>
        <div className={styles.summaryHeader}>
          <h3 className={styles.sectionTitle}>Usage summary</h3>
          <Button variant="ghost" size="sm" onClick={() => onSelectTab("usage")}>
            View full usage →
          </Button>
        </div>
        <div className={styles.statGrid}>
          <StatCard
            icon={<UserCog size={16} />}
            tone="brand"
            label="Users"
            isLoading={usersQuery.isPending}
            value={usersQuery.data?.page.total ?? "—"}
          />
          <StatCard
            icon={<Bus size={16} />}
            tone="success"
            label="Vehicles"
            isLoading={vehiclesQuery.isPending}
            value={vehiclesQuery.data?.page.total ?? "—"}
          />
          <StatCard
            icon={<Users size={16} />}
            tone="purple"
            label="Students"
            isLoading={studentsQuery.isPending}
            value={studentsQuery.data ?? "—"}
          />
          <StatCard
            icon={<CreditCard size={16} />}
            tone="warning"
            label="Parents"
            isLoading={parentsQuery.isPending}
            value={parentsQuery.data ?? "—"}
          />
        </div>
      </section>
    </div>
  );
}
