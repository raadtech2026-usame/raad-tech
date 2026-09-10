import { useQuery } from "@tanstack/react-query";
import { CreditCard, Landmark } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import { getCurrentSubscription } from "../../features/billing/api";
import { subscriptionStatusLabel, subscriptionStatusTone } from "../../features/billing/labels";
import { currentPeriod, formatAmount, getFinanceSummary } from "../../features/school-erp/api";
import sectionStyles from "./dashboard.module.css";
import styles from "./OrganizationFinanceSection.module.css";

/**
 * Two financial domains, deliberately kept apart on the Organization Dashboard exactly as they
 * are everywhere else in this codebase (ADR-0038 §2): the org's own RAAD subscription
 * (`billing`, C8 — `GET /billing/subscriptions/current`, "the caller's OWN organization's
 * subscription") and the school's student-billing summary (`school_erp`, C11 —
 * `GET /school-finance/summary`, already reused as-is from `OrgFinancePage`'s own KPI row). No
 * new endpoint, no new permission — both routes were already reachable by Org Admin (confirmed
 * live, 2026-09-10) and simply had no home on this page before now.
 */
export function SubscriptionStatusCard() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["org-dashboard", "subscription"],
    queryFn: getCurrentSubscription,
    staleTime: 60_000,
  });

  return (
    <Card>
      <CardHeader icon={<CreditCard size={18} />} title="Subscription" subtitle="Your organization's own RAAD plan" />
      <div className={sectionStyles.panelBody}>
        {isError ? (
          <EmptyState
            icon={<CreditCard size={20} />}
            title="Could not load subscription"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading ? (
          <Skeleton height={24} />
        ) : !data ? (
          <EmptyState icon={<CreditCard size={20} />} title="No subscription on file" />
        ) : (
          <div className={styles.subscriptionRow}>
            <Badge variant={subscriptionStatusTone(data.status)} dot>
              {subscriptionStatusLabel(data.status)}
            </Badge>
            {data.currentPeriodEnd && (
              <span className={styles.subscriptionMeta}>
                Renews {new Date(data.currentPeriodEnd).toLocaleDateString()}
              </span>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

export function SchoolFinanceSummaryCard() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["org-dashboard", "finance-summary"],
    queryFn: () => getFinanceSummary(currentPeriod()),
    staleTime: 60_000,
  });

  return (
    <Card>
      <CardHeader icon={<Landmark size={18} />} title="School finance" subtitle="This period" />
      <div className={sectionStyles.panelBody}>
        {isError ? (
          <EmptyState
            icon={<Landmark size={20} />}
            title="Could not load finance summary"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading || !data ? (
          <Skeleton height={24} />
        ) : (
          <dl className={styles.financeGrid}>
            <div>
              <dt>Billed</dt>
              <dd>{formatAmount(data.billedAmount, data.currency)}</dd>
            </div>
            <div>
              <dt>Collected</dt>
              <dd>{formatAmount(data.collectedAmount, data.currency)}</dd>
            </div>
            <div>
              <dt>Outstanding</dt>
              <dd>{formatAmount(data.outstandingAmount, data.currency)}</dd>
            </div>
            <div>
              <dt>Overdue invoices</dt>
              <dd className={data.overdueInvoiceCount > 0 ? styles.warn : undefined}>
                {data.overdueInvoiceCount}
              </dd>
            </div>
          </dl>
        )}
      </div>
    </Card>
  );
}
