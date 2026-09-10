import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ArrowLeft,
  CalendarClock,
  CreditCard,
  History,
  Info,
  ReceiptText,
  Wallet,
} from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Card, CardBody, CardHeader } from "../../../shared/components/Card/Card";
import { DataTable } from "../../../shared/components/Table/DataTable";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { StatCard } from "../../../shared/components/StatCard/StatCard";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { ApiError, type OffsetPage } from "../../../shared/api/types";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { humanizeEventName } from "../../../app/dashboard/formatRelativeTime";
import { useAuthStore } from "../../../shared/stores/authStore";
import { getOrganization } from "../../organizations/api";
import type { AuditEntry } from "../../platform-analytics/api";
import { getSubscription, type Invoice, type Payment, type Subscription } from "../api";
import {
  billingCycleLabel,
  invoiceStatusLabel,
  invoiceStatusTone,
  paymentStatusLabel,
  paymentStatusTone,
  subscriptionStatusLabel,
  subscriptionStatusTone,
} from "../labels";
import { formatAmount, formatDateOnly, formatDateTime } from "../format";
import { SubscriptionActions } from "../SubscriptionActions";
import {
  organizationAuditTimeline,
  organizationPayments,
  planCatalog,
  subscriptionEvents,
  subscriptionInvoices,
} from "./api";
import { explainSubscriptionStatus } from "./statusExplanations";
import styles from "./SubscriptionDetailsPage.module.css";

type TabId = "overview" | "invoices" | "payments" | "timeline";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "invoices", label: "Invoices" },
  { id: "payments", label: "Payments" },
  { id: "timeline", label: "Timeline & Events" },
];

const RENEWAL_ACTIONS = new Set(["SubscriptionOpened", "SubscriptionRenewed"]);

const invoiceColumns: ColumnDef<Invoice, unknown>[] = [
  { id: "number", header: "Number", cell: ({ row }) => <span className={styles.mono}>{row.original.number}</span> },
  { id: "amount", header: "Amount", cell: ({ row }) => formatAmount(row.original.amount, row.original.currency) },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={invoiceStatusTone(row.original.status)} dot>
        {invoiceStatusLabel(row.original.status)}
      </Badge>
    ),
  },
  {
    id: "period",
    header: "Period",
    cell: ({ row }) => `${formatDateOnly(row.original.periodStart)} – ${formatDateOnly(row.original.periodEnd)}`,
  },
  { id: "issued", header: "Issued", cell: ({ row }) => (row.original.issuedAt ? formatDateOnly(row.original.issuedAt) : "—") },
];

const paymentColumns: ColumnDef<Payment, unknown>[] = [
  { id: "date", header: "Date", cell: ({ row }) => formatDateTime(row.original.createdAt) },
  { id: "amount", header: "Amount", cell: ({ row }) => formatAmount(row.original.amount, row.original.currency) },
  { id: "provider", header: "Provider", cell: ({ row }) => row.original.provider },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={paymentStatusTone(row.original.status)} dot>
        {paymentStatusLabel(row.original.status)}
      </Badge>
    ),
  },
  { id: "confirmed", header: "Confirmed", cell: ({ row }) => (row.original.confirmedAt ? formatDateTime(row.original.confirmedAt) : "—") },
];

/**
 * Founder → one subscription, everything needed to troubleshoot it without paging through the
 * Billing list and matching an id by eye (`GET /billing/subscriptions/{id}`, added 2026-09-10
 * specifically to back this page — see `../api.ts`'s own docstring on `getSubscription`).
 *
 * **A composition, exactly like `OrganizationDetailsPage`.** Every section reads through a
 * client that already exists (`../api.ts`, `../../organizations/api.ts`,
 * `../../platform-analytics/api.ts`) with one extra filter — see `./api.ts`. No section invents
 * a new read model.
 *
 * **The status explanation is the point of this page.** `explainSubscriptionStatus` turns the
 * five ADR-0039 lifecycle timestamps already on `Subscription` into one plain-language sentence,
 * so a Founder never has to reconstruct "why is this Active/Grace/Past due/Suspended/Expired"
 * from raw dates by eye — the Status Timeline tab below then shows the exact event that produced
 * the current state, not just the current state itself.
 */
export function SubscriptionDetailsPage() {
  const { subscriptionId = "" } = useParams<{ subscriptionId: string }>();
  const [tab, setTab] = useState<TabId>("overview");
  const principal = useAuthStore((s) => s.principal);
  // `billing.subscriptions.manage` is granted only to founder/finance_staff (migration
  // a7f31c92be04) — the same gate `BillingPage.tsx` already applies before rendering
  // `SubscriptionActions`. Presentation of a server-enforced grant, never a substitute for it.
  const canManage = principal?.role === "founder" || principal?.role === "finance_staff";

  const subscription = useQuery({
    queryKey: ["billing", "subscriptions", "detail", subscriptionId],
    queryFn: () => getSubscription(subscriptionId),
    enabled: Boolean(subscriptionId),
    staleTime: 30_000,
  });

  const organizationId = subscription.data?.organizationId ?? null;

  const organization = useQuery({
    queryKey: ["organizations", "detail", organizationId],
    queryFn: () => getOrganization(organizationId as string),
    enabled: Boolean(organizationId),
    staleTime: 60_000,
  });

  const plans = useQuery({
    queryKey: ["billing", "plans", "lookup"],
    queryFn: planCatalog,
    staleTime: 60_000,
  });
  const plan = useMemo(
    () => plans.data?.data.find((candidate) => candidate.id === subscription.data?.planId) ?? null,
    [plans.data, subscription.data],
  );

  // Tab data loads only when its tab is opened — the same discipline `OrganizationDetailsPage`
  // already documents ("fifteen tabs firing on mount would be fifteen requests"). `invoices` is
  // the one exception with two consumers: the Payments tab needs the invoice ids it resolves
  // before it can filter the organization's payment history down to this subscription's own.
  const invoices = useQuery({
    queryKey: ["billing", "subscriptions", "detail", subscriptionId, "invoices"],
    queryFn: () => subscriptionInvoices(subscriptionId),
    enabled: Boolean(subscriptionId) && (tab === "invoices" || tab === "payments"),
    staleTime: 30_000,
  });

  const payments = useQuery({
    queryKey: ["billing", "subscriptions", "detail", subscriptionId, "payments", organizationId],
    queryFn: () => organizationPayments(organizationId as string),
    enabled: Boolean(organizationId) && tab === "payments",
    staleTime: 30_000,
  });

  const events = useQuery({
    queryKey: ["billing", "subscriptions", "detail", subscriptionId, "events"],
    queryFn: () => subscriptionEvents(subscriptionId),
    enabled: Boolean(subscriptionId) && tab === "timeline",
    staleTime: 30_000,
  });

  const orgAudit = useQuery({
    queryKey: ["billing", "subscriptions", "detail", subscriptionId, "org-audit", organizationId],
    queryFn: () => organizationAuditTimeline(organizationId as string),
    enabled: Boolean(organizationId) && tab === "timeline",
    staleTime: 30_000,
  });

  usePageHeader(
    organization.data?.name ?? "Subscription",
    subscription.data
      ? `${plan?.name ?? subscription.data.planId} · ${subscriptionStatusLabel(subscription.data.status)}`
      : "Loading…",
  );

  if (subscription.isPending) {
    return (
      <div className={styles.page}>
        <Skeleton height={28} />
        <Skeleton height={180} />
      </div>
    );
  }

  if (subscription.isError) {
    return (
      <div className={styles.page}>
        <EmptyState
          icon={<Info size={22} />}
          title="Could not load this subscription"
          description={
            subscription.error instanceof ApiError
              ? subscription.error.message
              : "Something went wrong. Please try again."
          }
        />
        <Link to="/platform/billing" className={styles.backLink}>
          <ArrowLeft size={14} /> Back to billing
        </Link>
      </div>
    );
  }

  const sub = subscription.data;

  return (
    <div className={clsx(styles.page, "raad-view-transition")}>
      <div className={styles.breadcrumb}>
        <Link to="/platform/billing" className={styles.backLink}>
          <ArrowLeft size={14} /> All subscriptions
        </Link>
        <Badge variant={subscriptionStatusTone(sub.status)} dot>
          {subscriptionStatusLabel(sub.status)}
        </Badge>
      </div>

      <div className={styles.notice}>
        <Info size={16} className={styles.noticeIcon} aria-hidden="true" />
        <p className={styles.noticeText}>{explainSubscriptionStatus(sub)}</p>
      </div>

      <div className={styles.statGrid}>
        <StatCard
          icon={<CreditCard size={16} />}
          label="Current plan"
          value={plan?.name ?? sub.planId}
          meta={plan ? billingCycleLabel(plan.billingCycle) : undefined}
        />
        <StatCard
          icon={<CalendarClock size={16} />}
          label="Renewal date"
          value={sub.currentPeriodEnd ? formatDateOnly(sub.currentPeriodEnd) : "—"}
          meta={sub.autoRenew ? "Auto-renew on" : "Auto-renew off"}
          metaTone={sub.autoRenew ? "success" : "neutral"}
        />
        <StatCard
          icon={<History size={16} />}
          label="Grace period"
          value={sub.gracePeriodEndsAt ? formatDateOnly(sub.gracePeriodEndsAt) : "Not in grace"}
          tone={sub.gracePeriodEndsAt ? "warning" : "neutral"}
        />
        <StatCard
          icon={<ReceiptText size={16} />}
          label="Expiry date"
          value={sub.expiredAt ? formatDateOnly(sub.expiredAt) : "Not expired"}
          tone={sub.expiredAt ? "danger" : "neutral"}
        />
      </div>

      {canManage && (
        <Card padded>
          <CardHeader title="Actions" subtitle="Platform-admin lifecycle controls" />
          <SubscriptionActions subscription={sub} />
        </Card>
      )}

      <div className={styles.tabBar}>
        <Tabs options={TABS} activeId={tab} onSelect={(id) => setTab(id as TabId)} />
      </div>

      <Card>
        <CardBody>
          {tab === "overview" && (
            <OverviewTab
              subscription={sub}
              organizationName={organization.data?.name ?? null}
              organizationIsLoading={organization.isPending}
              planName={plan?.name ?? null}
              planAmount={plan ? formatAmount(plan.amount, plan.currency) : null}
              planCycle={plan ? billingCycleLabel(plan.billingCycle) : null}
            />
          )}
          {tab === "invoices" && <InvoicesTab query={invoices} />}
          {tab === "payments" && <PaymentsTab invoicesQuery={invoices} paymentsQuery={payments} />}
          {tab === "timeline" && <TimelineTab eventsQuery={events} auditQuery={orgAudit} />}
        </CardBody>
      </Card>
    </div>
  );
}

interface OverviewTabProps {
  subscription: Subscription;
  organizationName: string | null;
  organizationIsLoading: boolean;
  planName: string | null;
  planAmount: string | null;
  planCycle: string | null;
}

function OverviewTab({
  subscription,
  organizationName,
  organizationIsLoading,
  planName,
  planAmount,
  planCycle,
}: OverviewTabProps) {
  return (
    <dl className={styles.detail}>
      <div>
        <dt>Current plan</dt>
        <dd>{planName ? `${planName}${planAmount ? ` — ${planAmount}` : ""}` : "—"}</dd>
      </div>
      <div>
        <dt>Organization</dt>
        <dd>
          {organizationIsLoading ? (
            "Loading…"
          ) : (
            <Link to={`/platform/organizations/${subscription.organizationId}`} className={styles.link}>
              {organizationName ?? subscription.organizationId}
            </Link>
          )}
        </dd>
      </div>
      <div>
        <dt>Current status</dt>
        <dd>
          <Badge variant={subscriptionStatusTone(subscription.status)} dot>
            {subscriptionStatusLabel(subscription.status)}
          </Badge>
        </dd>
      </div>
      <div>
        <dt>Activation date</dt>
        <dd>{formatDateTime(subscription.createdAt)}</dd>
      </div>
      <div>
        <dt>Renewal date</dt>
        <dd>{subscription.currentPeriodEnd ? formatDateTime(subscription.currentPeriodEnd) : "—"}</dd>
      </div>
      <div>
        <dt>Expiry date</dt>
        <dd>{subscription.expiredAt ? formatDateTime(subscription.expiredAt) : "Not expired"}</dd>
      </div>
      <div>
        <dt>Grace period ends</dt>
        <dd>{subscription.gracePeriodEndsAt ? formatDateTime(subscription.gracePeriodEndsAt) : "—"}</dd>
      </div>
      <div>
        <dt>Billing cycle</dt>
        <dd>{planCycle ?? "—"}</dd>
      </div>
      <div>
        <dt>Auto-renew</dt>
        <dd>{subscription.autoRenew ? "Yes" : "No"}</dd>
      </div>
      <div>
        <dt>Past due since</dt>
        <dd>{subscription.pastDueSince ? formatDateTime(subscription.pastDueSince) : "—"}</dd>
      </div>
      <div>
        <dt>Suspended</dt>
        <dd>{subscription.suspendedAt ? formatDateTime(subscription.suspendedAt) : "—"}</dd>
      </div>
      <div>
        <dt>Cancelled</dt>
        <dd>{subscription.cancelledAt ? formatDateTime(subscription.cancelledAt) : "—"}</dd>
      </div>
      <div>
        <dt>Subscription ID</dt>
        <dd className={styles.mono}>{subscription.id}</dd>
      </div>
    </dl>
  );
}

function InvoicesTab({ query }: { query: UseQueryResult<OffsetPage<Invoice>, unknown> }) {
  if (query.isPending) {
    return (
      <>
        <Skeleton height={18} />
        <Skeleton height={18} />
        <Skeleton height={18} />
      </>
    );
  }
  if (query.isError) {
    return (
      <EmptyState
        icon={<Info size={20} />}
        title="Could not load invoices"
        description={query.error instanceof ApiError ? query.error.message : "Something went wrong. Please try again."}
      />
    );
  }
  const rows = query.data.data;
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ReceiptText size={20} />}
        title="No invoices"
        description="RAAD has not issued an invoice against this subscription."
      />
    );
  }
  const [current, ...previous] = rows;

  return (
    <div className={styles.stack}>
      <section>
        <h3 className={styles.sectionTitle}>Current invoice</h3>
        <dl className={styles.detail}>
          <div>
            <dt>Number</dt>
            <dd className={styles.mono}>{current.number}</dd>
          </div>
          <div>
            <dt>Amount</dt>
            <dd>{formatAmount(current.amount, current.currency)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <Badge variant={invoiceStatusTone(current.status)} dot>
                {invoiceStatusLabel(current.status)}
              </Badge>
            </dd>
          </div>
          <div>
            <dt>Period</dt>
            <dd>
              {formatDateOnly(current.periodStart)} – {formatDateOnly(current.periodEnd)}
            </dd>
          </div>
          <div>
            <dt>Issued</dt>
            <dd>{current.issuedAt ? formatDateTime(current.issuedAt) : "—"}</dd>
          </div>
          <div>
            <dt>Due</dt>
            <dd>{current.dueAt ? formatDateTime(current.dueAt) : "—"}</dd>
          </div>
          <div>
            <dt>Paid</dt>
            <dd>{current.paidAt ? formatDateTime(current.paidAt) : "—"}</dd>
          </div>
        </dl>
      </section>

      <section>
        <h3 className={styles.sectionTitle}>Previous invoices</h3>
        {previous.length === 0 ? (
          <p className={styles.muted}>No earlier invoices — this is the only one issued so far.</p>
        ) : (
          <DataTable
            columns={invoiceColumns}
            data={previous}
            getRowId={(row) => row.id}
            emptyState={<EmptyState icon={<ReceiptText size={20} />} title="No previous invoices" description="" />}
          />
        )}
      </section>
    </div>
  );
}

function PaymentsTab({
  invoicesQuery,
  paymentsQuery,
}: {
  invoicesQuery: UseQueryResult<OffsetPage<Invoice>, unknown>;
  paymentsQuery: UseQueryResult<OffsetPage<Payment>, unknown>;
}) {
  if (invoicesQuery.isPending || paymentsQuery.isPending) {
    return (
      <>
        <Skeleton height={18} />
        <Skeleton height={18} />
        <Skeleton height={18} />
      </>
    );
  }
  if (invoicesQuery.isError || paymentsQuery.isError) {
    const error = invoicesQuery.error ?? paymentsQuery.error;
    return (
      <EmptyState
        icon={<Info size={20} />}
        title="Could not load payments"
        description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
      />
    );
  }

  const invoiceIds = new Set(invoicesQuery.data.data.map((invoice) => invoice.id));
  const rows = paymentsQuery.data.data.filter((payment) => invoiceIds.has(payment.invoiceId));

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Wallet size={20} />}
        title="No payments"
        description="No payment has been attempted against this subscription's invoices."
      />
    );
  }

  return (
    <>
      <p className={styles.count}>{rows.length} total</p>
      <DataTable
        columns={paymentColumns}
        data={rows}
        getRowId={(row) => row.id}
        emptyState={<EmptyState icon={<Wallet size={20} />} title="No payments" description="" />}
      />
    </>
  );
}

function TimelineTab({
  eventsQuery,
  auditQuery,
}: {
  eventsQuery: UseQueryResult<OffsetPage<AuditEntry>, unknown>;
  auditQuery: UseQueryResult<OffsetPage<AuditEntry>, unknown>;
}) {
  return (
    <div className={styles.stack}>
      <section>
        <h3 className={styles.sectionTitle}>Status timeline</h3>
        <p className={styles.muted}>
          Every transition this subscription's own lifecycle has gone through, newest first —
          the direct record of why it is in its current status.
        </p>
        <EventList
          query={eventsQuery}
          emptyTitle="No lifecycle events"
          emptyDescription="This subscription has not recorded a status transition yet."
        />
      </section>

      <section>
        <h3 className={styles.sectionTitle}>Renewal history</h3>
        <p className={styles.muted}>Only the events that opened or renewed a billing period.</p>
        <EventList
          query={eventsQuery}
          filter={(entry) => RENEWAL_ACTIONS.has(entry.action)}
          emptyTitle="No renewals yet"
          emptyDescription="This subscription has not been opened or renewed."
        />
      </section>

      <section>
        <h3 className={styles.sectionTitle}>Audit timeline</h3>
        <p className={styles.muted}>
          Every recorded action against this organization — invoices, payments and everything
          else, not only this subscription's own events. Capped at the most recent 50 entries.
        </p>
        <EventList
          query={auditQuery}
          emptyTitle="No audit entries"
          emptyDescription="Nothing has been recorded against this organization."
        />
      </section>
    </div>
  );
}

function metadataSummary(metadata: Record<string, unknown> | null): string | null {
  if (!metadata) return null;
  const parts: string[] = [];
  if (typeof metadata.grace_period_ends_at === "string") {
    parts.push(`Grace until ${formatDateTime(metadata.grace_period_ends_at)}`);
  }
  if (typeof metadata.period_start === "string" && typeof metadata.period_end === "string") {
    parts.push(`Period ${formatDateOnly(metadata.period_start)} – ${formatDateOnly(metadata.period_end)}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function EventList({
  query,
  filter,
  emptyTitle,
  emptyDescription,
}: {
  query: UseQueryResult<OffsetPage<AuditEntry>, unknown>;
  filter?: (entry: AuditEntry) => boolean;
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (query.isPending) {
    return (
      <>
        <Skeleton height={18} />
        <Skeleton height={18} />
      </>
    );
  }
  if (query.isError) {
    return (
      <EmptyState
        icon={<Info size={20} />}
        title="Could not load this section"
        description={query.error instanceof ApiError ? query.error.message : "Something went wrong. Please try again."}
      />
    );
  }

  const rows = filter ? query.data.data.filter(filter) : query.data.data;
  if (rows.length === 0) {
    return <EmptyState icon={<History size={20} />} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <ul className={styles.eventList}>
      {rows.map((entry) => {
        const meta = metadataSummary(entry.metadata);
        return (
          <li key={entry.id} className={styles.eventRow}>
            <span className={styles.eventTime}>{formatDateTime(entry.createdAt)}</span>
            <span className={styles.eventAction}>{humanizeEventName(entry.action)}</span>
            {entry.entityType && <span className={styles.eventEntity}>{entry.entityType}</span>}
            <span className={styles.eventActor}>{entry.actorUserId ?? "system"}</span>
            {meta && <span className={styles.eventMeta}>{meta}</span>}
          </li>
        );
      })}
    </ul>
  );
}
