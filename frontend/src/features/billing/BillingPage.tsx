import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { CreditCard, FileText, Layers, Search } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../shared/stores/authStore";
import { ApiError } from "../../shared/api/types";
import { Badge } from "../../shared/components/Badge/Badge";
import { DataTable, type DataTableColumnMeta } from "../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../shared/components/Table/FilterChips";
import { Pagination } from "../../shared/components/Table/Pagination";
import { MonoText } from "../../shared/components/Table/cells";
import { DetailDrawer } from "../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Input } from "../../shared/components/Input/Input";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import {
  listInvoices,
  listOrganizationsForPicker,
  listPlans,
  listSubscriptions,
  type Invoice,
  type Plan,
  type Subscription,
} from "./api";
import {
  billingCycleLabel,
  invoiceStatusLabel,
  invoiceStatusTone,
  planStatusLabel,
  planStatusTone,
  subscriptionStatusLabel,
  subscriptionStatusTone,
} from "./labels";
import styles from "./BillingPage.module.css";

const SEARCH_DEBOUNCE_MS = 300;

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** `Invoice.periodStart`/`periodEnd` are date-only (`YYYY-MM-DD`, no time component) — parsing
 * that through a plain `new Date(...)` and formatting in the viewer's local timezone can roll
 * the displayed day backward whenever the local offset is negative (a well-known JS gotcha for
 * date-only strings, which `Date` treats as UTC midnight). Formatting in UTC instead sidesteps
 * it, since there's no local "time of day" to convert in the first place. */
function formatDateOnly(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function formatAmount(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

const PLAN_STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const SUBSCRIPTION_STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "trial", label: "Trial", tone: "info" },
  { id: "active", label: "Active", tone: "success" },
  { id: "suspended", label: "Suspended", tone: "warning" },
  { id: "expired", label: "Expired", tone: "danger" },
  { id: "cancelled", label: "Cancelled", tone: "neutral" },
];

const INVOICE_STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "draft", label: "Draft", tone: "neutral" },
  { id: "issued", label: "Issued", tone: "warning" },
  { id: "paid", label: "Paid", tone: "success" },
  { id: "void", label: "Void", tone: "danger" },
];

const TAB_OPTIONS = [
  { id: "plans", label: "Plans" },
  { id: "subscriptions", label: "Subscriptions" },
  { id: "invoices", label: "Invoices" },
];

/**
 * `/platform/billing` + `/org/billing` (F9) — one shared component, matching every other phase's
 * two-dashboard pattern; none of the three list routes are tenant-scoped (a real, pre-existing,
 * already-flagged gap — `./api.ts`'s own docstrings), so the page looks the same regardless of
 * which dashboard reaches it. Read-only by design: `billing/api/routers.py`'s own module
 * docstring confirms no write route exists for any of `Plan`/`Subscription`/`Invoice` this
 * phase, and `POST /billing/payments` always fails (no bound payment provider) — see `./api.ts`'s
 * own docstring for why no "Pay now" control exists anywhere on this page.
 *
 * **Regional Manager/Support Staff see Plans only, no tab switcher** — confirmed against the
 * seeded RBAC matrix that this pair holds `billing.plans.list` alone, not
 * `billing.subscriptions.list`/`.invoices.list` (every other role that reaches this page holds
 * all three). Omitted rather than rendered-then-403, the same posture the Founder Dashboard
 * already established for Finance Staff's narrower access.
 */
export function BillingPage() {
  usePageHeader("Billing", "Plans, subscriptions, and invoices across RAAD");
  const principal = useAuthStore((s) => s.principal);

  const canSeeAllTabs = principal?.role !== "regional_manager" && principal?.role !== "support_staff";

  const [activeTab, setActiveTab] = useState<string>("plans");
  const effectiveTab = canSeeAllTabs ? activeTab : "plans";

  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [selectedSubscription, setSelectedSubscription] = useState<Subscription | null>(null);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);

  const [planSearchInput, setPlanSearchInput] = useState("");
  const [invoiceSearchInput, setInvoiceSearchInput] = useState("");

  // Organization/plan *names* aren't in the Subscription/Invoice responses (only opaque ids) -
  // small, unfiltered lookup reads, the same "own minimal read, resolve names client-side"
  // precedent `OrganizationsPage`'s own `regionsLookup` already established. Capped at the first
  // 100 rows; beyond that this falls back to the raw id rather than a fabricated name.
  const organizationsLookup = useQuery({
    queryKey: ["organizations", "lookup"],
    queryFn: listOrganizationsForPicker,
    staleTime: 60_000,
    enabled: canSeeAllTabs && (effectiveTab === "subscriptions" || effectiveTab === "invoices"),
  });
  const organizationNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const org of organizationsLookup.data ?? []) {
      map.set(org.id, org.name);
    }
    return map;
  }, [organizationsLookup.data]);

  const plansLookup = useQuery({
    queryKey: ["billing", "plans", "lookup"],
    queryFn: () =>
      listPlans({ page: 1, pageSize: 100, sort: { field: "name", direction: "asc" }, filters: {}, search: "" }),
    staleTime: 60_000,
    enabled: canSeeAllTabs && effectiveTab === "subscriptions",
  });
  const planNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const plan of plansLookup.data?.data ?? []) {
      map.set(plan.id, plan.name);
    }
    return map;
  }, [plansLookup.data]);

  const plans = usePaginatedQuery({
    queryKey: ["billing", "plans", "list"],
    fetcher: listPlans,
    initialSort: { field: "name", direction: "asc" },
    enabled: effectiveTab === "plans",
  });

  const subscriptions = usePaginatedQuery({
    queryKey: ["billing", "subscriptions", "list"],
    fetcher: listSubscriptions,
    initialSort: { field: "created_at", direction: "desc" },
    enabled: canSeeAllTabs && effectiveTab === "subscriptions",
  });

  const invoices = usePaginatedQuery({
    queryKey: ["billing", "invoices", "list"],
    fetcher: listInvoices,
    initialSort: { field: "created_at", direction: "desc" },
    enabled: canSeeAllTabs && effectiveTab === "invoices",
  });

  useEffect(() => {
    const handle = setTimeout(() => plans.setSearch(planSearchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planSearchInput]);

  useEffect(() => {
    const handle = setTimeout(() => invoices.setSearch(invoiceSearchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceSearchInput]);

  const planColumns = useMemo<ColumnDef<Plan, unknown>[]>(
    () => [
      {
        id: "name",
        header: "Plan",
        meta: { sortField: "name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{row.original.name}</span>,
      },
      {
        id: "billingCycle",
        header: "Billing cycle",
        cell: ({ row }) => billingCycleLabel(row.original.billingCycle),
      },
      {
        id: "amount",
        header: "Amount",
        meta: { sortField: "amount", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatAmount(row.original.amount, row.original.currency),
      },
      {
        id: "vehicleLimit",
        header: "Vehicle limit",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => row.original.vehicleLimit ?? "Unlimited",
      },
      {
        id: "status",
        header: "Status",
        meta: { sortField: "status" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={planStatusTone(row.original.status)} dot>
            {planStatusLabel(row.original.status)}
          </Badge>
        ),
      },
    ],
    [],
  );

  const subscriptionColumns = useMemo<ColumnDef<Subscription, unknown>[]>(
    () => [
      {
        id: "organization",
        header: "Organization",
        cell: ({ row }) => {
          const name = organizationNameById.get(row.original.organizationId);
          return name ? <span>{name}</span> : <MonoText>{row.original.organizationId}</MonoText>;
        },
      },
      {
        id: "plan",
        header: "Plan",
        cell: ({ row }) => {
          const name = planNameById.get(row.original.planId);
          return name ? <span>{name}</span> : <MonoText>{row.original.planId}</MonoText>;
        },
      },
      {
        id: "status",
        header: "Status",
        meta: { sortField: "status" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={subscriptionStatusTone(row.original.status)} dot>
            {subscriptionStatusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        id: "period",
        header: "Current period",
        cell: ({ row }) =>
          row.original.currentPeriodStart && row.original.currentPeriodEnd
            ? `${formatDateTime(row.original.currentPeriodStart)} – ${formatDateTime(row.original.currentPeriodEnd)}`
            : "—",
      },
      {
        id: "autoRenew",
        header: "Auto-renew",
        cell: ({ row }) => (row.original.autoRenew ? "Yes" : "No"),
      },
    ],
    [organizationNameById, planNameById],
  );

  const invoiceColumns = useMemo<ColumnDef<Invoice, unknown>[]>(
    () => [
      {
        id: "number",
        header: "Invoice",
        meta: { sortField: "number" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <MonoText>{row.original.number}</MonoText>,
      },
      {
        id: "organization",
        header: "Organization",
        cell: ({ row }) => {
          const name = organizationNameById.get(row.original.organizationId);
          return name ? <span>{name}</span> : <MonoText>{row.original.organizationId}</MonoText>;
        },
      },
      {
        id: "amount",
        header: "Amount",
        meta: { sortField: "amount", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatAmount(row.original.amount, row.original.currency),
      },
      {
        id: "period",
        header: "Period",
        cell: ({ row }) => `${formatDateOnly(row.original.periodStart)} – ${formatDateOnly(row.original.periodEnd)}`,
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
    ],
    [organizationNameById],
  );

  const activePlanFilter = plans.filters.status ?? "all";
  const activeSubscriptionFilter = subscriptions.filters.status ?? "all";
  const activeInvoiceFilter = invoices.filters.status ?? "all";

  return (
    <div className={styles.page}>
      {canSeeAllTabs && <Tabs options={TAB_OPTIONS} activeId={effectiveTab} onSelect={setActiveTab} />}

      {effectiveTab === "plans" && (
        <>
          <div className={styles.toolbar}>
            <FilterChips
              options={PLAN_STATUS_FILTERS}
              activeId={activePlanFilter}
              onSelect={(id) => plans.setFilter("status", id === "all" ? null : id)}
            />
            <Input
              icon={<Search size={14} />}
              placeholder="Search plans…"
              value={planSearchInput}
              onChange={(event) => setPlanSearchInput(event.target.value)}
              aria-label="Search plans"
            />
          </div>

          {plans.isError ? (
            <EmptyState
              icon={<Layers size={22} />}
              title="Could not load plans"
              description={plans.error instanceof ApiError ? plans.error.message : "Something went wrong. Please try again."}
            />
          ) : (
            <>
              <DataTable
                columns={planColumns}
                data={plans.rows}
                getRowId={(row) => row.id}
                isLoading={plans.isLoading}
                sort={plans.sort}
                onSortChange={plans.toggleSort}
                onRowClick={setSelectedPlan}
                emptyState={
                  <EmptyState icon={<Layers size={22} />} title="No plans yet" description="Billing plans will appear here once created." />
                }
              />
              <Pagination page={plans.page} pageSize={plans.pageSize} total={plans.total} onPageChange={plans.setPage} />
            </>
          )}
        </>
      )}

      {effectiveTab === "subscriptions" && canSeeAllTabs && (
        <>
          <div className={styles.toolbar}>
            <FilterChips
              options={SUBSCRIPTION_STATUS_FILTERS}
              activeId={activeSubscriptionFilter}
              onSelect={(id) => subscriptions.setFilter("status", id === "all" ? null : id)}
            />
          </div>

          {subscriptions.isError ? (
            <EmptyState
              icon={<CreditCard size={22} />}
              title="Could not load subscriptions"
              description={
                subscriptions.error instanceof ApiError ? subscriptions.error.message : "Something went wrong. Please try again."
              }
            />
          ) : (
            <>
              <DataTable
                columns={subscriptionColumns}
                data={subscriptions.rows}
                getRowId={(row) => row.id}
                isLoading={subscriptions.isLoading}
                sort={subscriptions.sort}
                onSortChange={subscriptions.toggleSort}
                onRowClick={setSelectedSubscription}
                emptyState={
                  <EmptyState
                    icon={<CreditCard size={22} />}
                    title="No subscriptions yet"
                    description="Organization subscriptions will appear here once opened."
                  />
                }
              />
              <Pagination
                page={subscriptions.page}
                pageSize={subscriptions.pageSize}
                total={subscriptions.total}
                onPageChange={subscriptions.setPage}
              />
            </>
          )}
        </>
      )}

      {effectiveTab === "invoices" && canSeeAllTabs && (
        <>
          <div className={styles.toolbar}>
            <FilterChips
              options={INVOICE_STATUS_FILTERS}
              activeId={activeInvoiceFilter}
              onSelect={(id) => invoices.setFilter("status", id === "all" ? null : id)}
            />
            <Input
              icon={<Search size={14} />}
              placeholder="Search invoice number…"
              value={invoiceSearchInput}
              onChange={(event) => setInvoiceSearchInput(event.target.value)}
              aria-label="Search invoices"
            />
          </div>

          {invoices.isError ? (
            <EmptyState
              icon={<FileText size={22} />}
              title="Could not load invoices"
              description={invoices.error instanceof ApiError ? invoices.error.message : "Something went wrong. Please try again."}
            />
          ) : (
            <>
              <DataTable
                columns={invoiceColumns}
                data={invoices.rows}
                getRowId={(row) => row.id}
                isLoading={invoices.isLoading}
                sort={invoices.sort}
                onSortChange={invoices.toggleSort}
                onRowClick={setSelectedInvoice}
                emptyState={
                  <EmptyState icon={<FileText size={22} />} title="No invoices yet" description="Invoices will appear here once issued." />
                }
              />
              <Pagination page={invoices.page} pageSize={invoices.pageSize} total={invoices.total} onPageChange={invoices.setPage} />
            </>
          )}
        </>
      )}

      <DetailDrawer
        open={selectedPlan !== null}
        onClose={() => setSelectedPlan(null)}
        icon={<Layers size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedPlan?.name}
        subtitle={selectedPlan ? billingCycleLabel(selectedPlan.billingCycle) : undefined}
        status={
          selectedPlan && (
            <Badge variant={planStatusTone(selectedPlan.status)} dot>
              {planStatusLabel(selectedPlan.status)}
            </Badge>
          )
        }
        rows={
          selectedPlan
            ? [
                { key: "Amount", value: formatAmount(selectedPlan.amount, selectedPlan.currency) },
                { key: "Vehicle limit", value: selectedPlan.vehicleLimit ?? "Unlimited" },
                { key: "Plan ID", value: <MonoText>{selectedPlan.id}</MonoText> },
                { key: "Created", value: formatDateTime(selectedPlan.createdAt) },
                { key: "Updated", value: formatDateTime(selectedPlan.updatedAt) },
              ]
            : []
        }
      />

      <DetailDrawer
        open={selectedSubscription !== null}
        onClose={() => setSelectedSubscription(null)}
        icon={<CreditCard size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedSubscription ? organizationNameById.get(selectedSubscription.organizationId) ?? selectedSubscription.organizationId : undefined}
        subtitle={selectedSubscription ? planNameById.get(selectedSubscription.planId) ?? selectedSubscription.planId : undefined}
        status={
          selectedSubscription && (
            <Badge variant={subscriptionStatusTone(selectedSubscription.status)} dot>
              {subscriptionStatusLabel(selectedSubscription.status)}
            </Badge>
          )
        }
        rows={
          selectedSubscription
            ? [
                { key: "Current period start", value: formatDateTime(selectedSubscription.currentPeriodStart) },
                { key: "Current period end", value: formatDateTime(selectedSubscription.currentPeriodEnd) },
                { key: "Auto-renew", value: selectedSubscription.autoRenew ? "Yes" : "No" },
                { key: "Subscription ID", value: <MonoText>{selectedSubscription.id}</MonoText> },
                { key: "Created", value: formatDateTime(selectedSubscription.createdAt) },
                { key: "Updated", value: formatDateTime(selectedSubscription.updatedAt) },
              ]
            : []
        }
      />

      <DetailDrawer
        open={selectedInvoice !== null}
        onClose={() => setSelectedInvoice(null)}
        icon={<FileText size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedInvoice?.number}
        subtitle={selectedInvoice ? organizationNameById.get(selectedInvoice.organizationId) ?? selectedInvoice.organizationId : undefined}
        status={
          selectedInvoice && (
            <Badge variant={invoiceStatusTone(selectedInvoice.status)} dot>
              {invoiceStatusLabel(selectedInvoice.status)}
            </Badge>
          )
        }
        rows={
          selectedInvoice
            ? [
                { key: "Amount", value: formatAmount(selectedInvoice.amount, selectedInvoice.currency) },
                { key: "Period", value: `${formatDateOnly(selectedInvoice.periodStart)} – ${formatDateOnly(selectedInvoice.periodEnd)}` },
                { key: "Issued", value: formatDateTime(selectedInvoice.issuedAt) },
                { key: "Due", value: formatDateTime(selectedInvoice.dueAt) },
                { key: "Paid", value: formatDateTime(selectedInvoice.paidAt) },
                { key: "Subscription ID", value: <MonoText>{selectedInvoice.subscriptionId}</MonoText> },
                { key: "Invoice ID", value: <MonoText>{selectedInvoice.id}</MonoText> },
              ]
            : []
        }
      />
    </div>
  );
}
