import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { CreditCard, FileText, Receipt } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../shared/stores/authStore";
import { ApiError } from "../../shared/api/types";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { DataTable, type DataTableColumnMeta } from "../../shared/components/Table/DataTable";
import { Pagination } from "../../shared/components/Table/Pagination";
import { MonoText } from "../../shared/components/Table/cells";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { getOrganization } from "../organizations/api";
import {
  getBillingProviderConfig,
  listInvoices,
  listPayments,
  listPlans,
  listSubscriptions,
  type Invoice,
  type Payment,
} from "./api";
import {
  invoiceStatusLabel,
  invoiceStatusTone,
  paymentStatusLabel,
  paymentStatusTone,
  subscriptionStatusLabel,
  subscriptionStatusTone,
} from "./labels";
import { formatAmount, formatDateOnly, formatDateTime } from "./format";
import { PayInvoiceDialog } from "./PayInvoiceDialog";
import styles from "./OrgBillingPage.module.css";

interface InvoicesSectionProps {
  subscriptionId: string;
  payDisabled: boolean;
  onPay: (invoice: Invoice) => void;
}

/** Split out from `OrgBillingPage` for one reason: mounting it only once `subscriptionId` is
 * known means `usePaginatedQuery`'s `initialFilters` is correct on this component's very first
 * render, with no window where an unfiltered `GET /billing/invoices` could fire. That matters
 * here specifically because that route is not tenant-scoped server-side (`./api.ts`'s own
 * docstring, a real pre-existing gap) — an unfiltered request would return every organization's
 * invoices, not just this one's. Only this org's *current* subscription's invoices are shown; a
 * prior, no-longer-current subscription's invoices (if this org ever cancelled and reopened one)
 * are out of scope for this page, a deliberate limit given this page's own "current billing
 * situation" purpose. */
function InvoicesSection({ subscriptionId, payDisabled, onPay }: InvoicesSectionProps) {
  const invoices = usePaginatedQuery({
    queryKey: ["billing", "invoices", "self", subscriptionId],
    fetcher: listInvoices,
    initialSort: { field: "created_at", direction: "desc" },
    initialFilters: { subscription_id: subscriptionId },
  });

  const columns = useMemo<ColumnDef<Invoice, unknown>[]>(
    () => [
      {
        id: "number",
        header: "Invoice",
        meta: { sortField: "number" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <MonoText>{row.original.number}</MonoText>,
      },
      {
        id: "period",
        header: "Period",
        cell: ({ row }) => `${formatDateOnly(row.original.periodStart)} – ${formatDateOnly(row.original.periodEnd)}`,
      },
      {
        id: "amount",
        header: "Amount",
        meta: { sortField: "amount", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatAmount(row.original.amount, row.original.currency),
      },
      {
        id: "status",
        header: "Status",
        meta: { sortField: "status" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={invoiceStatusTone(row.original.status)} dot>
            {invoiceStatusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        id: "dueAt",
        header: "Due",
        meta: { sortField: "due_at", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatDateTime(row.original.dueAt),
      },
      {
        id: "action",
        header: "",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) =>
          row.original.status === "issued" ? (
            <Button
              size="sm"
              disabled={payDisabled}
              onClick={(event) => {
                event.stopPropagation();
                onPay(row.original);
              }}
            >
              Pay
            </Button>
          ) : null,
      },
    ],
    [payDisabled, onPay],
  );

  return (
    <Card>
      <CardHeader title="Invoices" />
      <div className={styles.tableBody}>
        {invoices.isError ? (
          <EmptyState
            icon={<FileText size={22} />}
            title="Could not load invoices"
            description={invoices.error instanceof ApiError ? invoices.error.message : "Something went wrong. Please try again."}
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              data={invoices.rows}
              getRowId={(row) => row.id}
              isLoading={invoices.isLoading}
              sort={invoices.sort}
              onSortChange={invoices.toggleSort}
              emptyState={
                <EmptyState icon={<FileText size={22} />} title="No invoices yet" description="Invoices will appear here once issued." />
              }
            />
            <Pagination page={invoices.page} pageSize={invoices.pageSize} total={invoices.total} onPageChange={invoices.setPage} />
          </>
        )}
      </div>
    </Card>
  );
}

const PAYMENT_COLUMNS: ColumnDef<Payment, unknown>[] = [
  {
    id: "provider",
    header: "Provider",
    cell: ({ row }) => <span className={styles.providerLabel}>{row.original.provider}</span>,
  },
  {
    id: "amount",
    header: "Amount",
    meta: { sortField: "amount", align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => formatAmount(row.original.amount, row.original.currency),
  },
  {
    id: "status",
    header: "Status",
    meta: { sortField: "status" } satisfies DataTableColumnMeta,
    cell: ({ row }) => (
      <Badge variant={paymentStatusTone(row.original.status)} dot>
        {paymentStatusLabel(row.original.status)}
      </Badge>
    ),
  },
  {
    id: "failureReason",
    header: "Detail",
    cell: ({ row }) => row.original.failureReason ?? "—",
  },
  {
    id: "createdAt",
    header: "Date",
    meta: { sortField: "created_at", align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  },
];

/**
 * `/org/billing` (ADR-0022) — Org Admin's own current subscription/plan, invoices, and payment
 * history, plus a real "Pay Invoice" flow. Replaces the shared `BillingPage` at this one route
 * only — `/platform/billing` is untouched, still the cross-organization admin table view.
 * Everything here is scoped to `principal.organizationId`, closing what the shared page's own
 * docstring flags as a real gap for that view (its three list routes are unscoped server-side).
 */
export function OrgBillingPage() {
  usePageHeader("Billing", "Your subscription, invoices, and payment history");
  const principal = useAuthStore((s) => s.principal);
  const orgId = principal?.organizationId ?? null;

  const [payingInvoice, setPayingInvoice] = useState<Invoice | null>(null);

  const organizationQuery = useQuery({
    queryKey: ["organizations", "self", orgId],
    queryFn: () => getOrganization(orgId as string),
    enabled: orgId !== null,
    staleTime: 60_000,
  });

  const providerConfigQuery = useQuery({
    queryKey: ["billing", "provider-config"],
    queryFn: getBillingProviderConfig,
    staleTime: 60_000,
  });
  const onlinePaymentAvailable = providerConfigQuery.data?.provider === "stripe";

  const plansLookup = useQuery({
    queryKey: ["billing", "plans", "lookup"],
    queryFn: () =>
      listPlans({ page: 1, pageSize: 100, sort: { field: "name", direction: "asc" }, filters: {}, search: "" }),
    staleTime: 60_000,
  });
  const planNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const plan of plansLookup.data?.data ?? []) {
      map.set(plan.id, plan.name);
    }
    return map;
  }, [plansLookup.data]);

  // organization_id *is* a whitelisted filter on /billing/subscriptions (unlike /billing/invoices
  // — see InvoicesSection above), and orgId is known synchronously from the signed-in principal,
  // so this can query directly without the same mount-ordering concern.
  const subscriptionQuery = useQuery({
    queryKey: ["billing", "subscriptions", "self", orgId],
    queryFn: () =>
      listSubscriptions({
        page: 1,
        pageSize: 1,
        sort: { field: "created_at", direction: "desc" },
        filters: { organization_id: orgId as string },
        search: "",
      }),
    enabled: orgId !== null,
  });
  const subscription = subscriptionQuery.data?.data[0] ?? null;

  const payments = usePaginatedQuery({
    queryKey: ["billing", "payments", "self", orgId],
    fetcher: listPayments,
    initialSort: { field: "created_at", direction: "desc" },
    initialFilters: orgId !== null ? { organization_id: orgId } : {},
    enabled: orgId !== null,
  });

  if (orgId === null) {
    return (
      <EmptyState
        icon={<CreditCard size={22} />}
        title="No organization on this account"
        description="This account is not linked to an organization."
      />
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.summaryRow}>
        <Card>
          <CardHeader title="Organization" />
          <div className={styles.panelBody}>
            {organizationQuery.isLoading ? (
              <Skeleton height={28} width={160} />
            ) : organizationQuery.isError ? (
              <span className={styles.errorText}>Could not load organization details.</span>
            ) : (
              <div className={styles.panelStat}>
                <span className={styles.panelStatValue}>{organizationQuery.data?.name}</span>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Subscription"
            action={
              subscription ? (
                <Badge variant={subscriptionStatusTone(subscription.status)} dot>
                  {subscriptionStatusLabel(subscription.status)}
                </Badge>
              ) : undefined
            }
          />
          <div className={styles.panelBody}>
            {subscriptionQuery.isLoading ? (
              <Skeleton height={28} width={160} />
            ) : subscriptionQuery.isError ? (
              <span className={styles.errorText}>Could not load subscription details.</span>
            ) : subscription ? (
              <>
                <div className={styles.panelStat}>
                  <span className={styles.panelStatValue}>
                    {planNameById.get(subscription.planId) ?? subscription.planId}
                  </span>
                </div>
                <p className={styles.panelStatCaption}>
                  {subscription.currentPeriodStart && subscription.currentPeriodEnd
                    ? `Current period: ${formatDateTime(subscription.currentPeriodStart)} – ${formatDateTime(subscription.currentPeriodEnd)}`
                    : "No active billing period"}
                </p>
                <p className={styles.panelStatCaption}>Auto-renew: {subscription.autoRenew ? "On" : "Off"}</p>
              </>
            ) : (
              <p className={styles.panelStatCaption}>No subscription on file yet.</p>
            )}
          </div>
        </Card>
      </div>

      {!providerConfigQuery.isLoading && !onlinePaymentAvailable && (
        <EmptyState
          icon={<CreditCard size={20} />}
          title="Online payment is not available yet"
          description="Your platform administrator has not configured a payment provider. Contact RAAD support to pay an invoice."
        />
      )}

      {subscriptionQuery.isLoading ? (
        <Card>
          <CardHeader title="Invoices" />
          <div className={styles.tableBody}>
            <Skeleton height={120} />
          </div>
        </Card>
      ) : subscription ? (
        <InvoicesSection
          subscriptionId={subscription.id}
          payDisabled={!onlinePaymentAvailable}
          onPay={setPayingInvoice}
        />
      ) : (
        <Card>
          <CardHeader title="Invoices" />
          <div className={styles.tableBody}>
            <EmptyState icon={<FileText size={22} />} title="No invoices yet" description="Invoices will appear here once a subscription is opened." />
          </div>
        </Card>
      )}

      <Card>
        <CardHeader title="Payment history" />
        <div className={styles.tableBody}>
          {payments.isError ? (
            <EmptyState
              icon={<Receipt size={22} />}
              title="Could not load payment history"
              description={payments.error instanceof ApiError ? payments.error.message : "Something went wrong. Please try again."}
            />
          ) : (
            <>
              <DataTable
                columns={PAYMENT_COLUMNS}
                data={payments.rows}
                getRowId={(row) => row.id}
                isLoading={payments.isLoading}
                sort={payments.sort}
                onSortChange={payments.toggleSort}
                emptyState={
                  <EmptyState icon={<Receipt size={22} />} title="No payments yet" description="Payments will appear here once made." />
                }
              />
              <Pagination page={payments.page} pageSize={payments.pageSize} total={payments.total} onPageChange={payments.setPage} />
            </>
          )}
        </div>
      </Card>

      {payingInvoice && (
        <PayInvoiceDialog
          invoice={payingInvoice}
          onClose={() => setPayingInvoice(null)}
          onPaid={() => setPayingInvoice(null)}
        />
      )}
    </div>
  );
}
