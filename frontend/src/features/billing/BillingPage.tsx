import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { CreditCard, FileText, Layers, Plus, Search } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../shared/stores/authStore";
import { ApiError } from "../../shared/api/types";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog/ConfirmDialog";
import { DataTable, type DataTableColumnMeta } from "../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../shared/components/Table/FilterChips";
import { PlanForm } from "./PlanForm";
import { SubscriptionActions } from "./SubscriptionActions";
import { Pagination } from "../../shared/components/Table/Pagination";
import { MonoText } from "../../shared/components/Table/cells";
import { DetailDrawer } from "../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Input } from "../../shared/components/Input/Input";
import { useToast } from "../../shared/components/Toast/toastStore";
import { Tabs } from "../../shared/components/Tabs/Tabs";
import {
  listInvoices,
  listOrganizationsForPicker,
  listPlans,
  listSubscriptions,
  setPlanStatus,
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
import { formatAmount, formatDateOnly, formatDateTime } from "./format";
import styles from "./BillingPage.module.css";

const SEARCH_DEBOUNCE_MS = 300;

const PLAN_STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const SUBSCRIPTION_STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "trial", label: "Trial", tone: "info" },
  { id: "active", label: "Active", tone: "success" },
  // ADR-0039's two new states. Without these there was no way to filter for exactly the
  // organizations that need attention - the ones an admin would actually come to this page for.
  { id: "past_due", label: "Past due", tone: "warning" },
  { id: "grace_period", label: "Grace period", tone: "warning" },
  { id: "suspended", label: "Suspended", tone: "danger" },
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
  const navigate = useNavigate();

  const canSeeAllTabs = principal?.role !== "regional_manager" && principal?.role !== "support_staff";
  // `billing.subscriptions.manage` is granted to exactly these two roles (migration
  // a7f31c92be04). org_admin deliberately does not hold it - a school cannot lift its own
  // suspension - and this page is platform-only anyway.
  const canManageSubscriptions = principal?.role === "founder" || principal?.role === "finance_staff";
  // `billing.plans.manage` is Founder-only (ADR-0040 §7, migration b5c81f3d47a9) — deliberately
  // narrower than the read-only `billing.plans.list` five roles hold, because changing what RAAD
  // charges is materially more sensitive than reading the price list. Presentation only; the
  // backend's RBAC check is the real gate either way.
  const canManagePlans = principal?.role === "founder";

  const [activeTab, setActiveTab] = useState<string>("plans");
  const effectiveTab = canSeeAllTabs ? activeTab : "plans";

  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [planFormOpen, setPlanFormOpen] = useState(false);
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null);
  const [togglingPlan, setTogglingPlan] = useState<Plan | null>(null);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);

  const queryClient = useQueryClient();
  const toast = useToast();

  const planStatusMutation = useMutation({
    mutationFn: (plan: Plan) => setPlanStatus(plan.id, plan.status !== "active"),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["billing", "plans"] });
      toast.success(
        saved.status === "active" ? "Plan activated" : "Plan disabled",
        saved.status === "active"
          ? `${saved.name} can be selected when onboarding an organization.`
          : `${saved.name} is no longer offered. Subscriptions already on it are unaffected.`,
      );
      setTogglingPlan(null);
    },
    onError: (error) => {
      toast.error(
        "Could not change the plan status",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

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
        header: "Vehicles",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => row.original.vehicleLimit ?? "Unlimited",
      },
      // ADR-0040 §4 added both alongside the pre-existing vehicle allowance; a tier's included
      // hardware and seats are as much a part of "what am I buying" as its bus count.
      {
        id: "deviceLimit",
        header: "Devices",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => row.original.deviceLimit ?? "Unlimited",
      },
      {
        id: "userLimit",
        header: "Users",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => row.original.userLimit ?? "Unlimited",
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
      ...(canManagePlans
        ? [
            {
              id: "actions",
              header: "",
              meta: { align: "right" } satisfies DataTableColumnMeta,
              cell: ({ row }: { row: { original: Plan } }) => (
                <div
                  className={styles.rowActions}
                  // The row itself opens the read-only detail drawer; these are distinct
                  // actions and must not also trigger it.
                  onClick={(event) => event.stopPropagation()}
                >
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setEditingPlan(row.original);
                      setPlanFormOpen(true);
                    }}
                  >
                    Edit
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setTogglingPlan(row.original)}>
                    {row.original.status === "active" ? "Disable" : "Activate"}
                  </Button>
                </div>
              ),
            } as ColumnDef<Plan, unknown>,
          ]
        : []),
    ],
    [canManagePlans],
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
      // Only rendered for the roles that actually hold `billing.subscriptions.manage`
      // (founder / finance_staff, per migration a7f31c92be04). Presentation of a server-enforced
      // grant, never a substitute for it - the API re-checks on every call regardless.
      ...(canManageSubscriptions
        ? [
            {
              id: "actions",
              header: "",
              cell: ({ row }) => <SubscriptionActions subscription={row.original} />,
            } satisfies ColumnDef<Subscription, unknown>,
          ]
        : []),
    ],
    [organizationNameById, planNameById, canManageSubscriptions],
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
            {canManagePlans && (
              <Button
                leadingIcon={<Plus size={14} />}
                onClick={() => {
                  setEditingPlan(null);
                  setPlanFormOpen(true);
                }}
              >
                New plan
              </Button>
            )}
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
                onRowClick={(row) => navigate(`/platform/billing/subscriptions/${row.id}`)}
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

      <PlanForm
        open={planFormOpen}
        onClose={() => {
          setPlanFormOpen(false);
          setEditingPlan(null);
        }}
        plan={editingPlan}
      />

      <ConfirmDialog
        open={togglingPlan !== null}
        title={togglingPlan?.status === "active" ? "Disable this plan?" : "Activate this plan?"}
        description={
          togglingPlan?.status === "active"
            ? `${togglingPlan.name} will no longer be offered when onboarding an organization. Subscriptions already on it keep running and keep billing normally.`
            : togglingPlan
              ? `${togglingPlan.name} will be selectable again when onboarding an organization.`
              : undefined
        }
        confirmLabel={togglingPlan?.status === "active" ? "Disable plan" : "Activate plan"}
        tone={togglingPlan?.status === "active" ? "danger" : "primary"}
        loading={planStatusMutation.isPending}
        onConfirm={() => togglingPlan && planStatusMutation.mutate(togglingPlan)}
        onCancel={() => setTogglingPlan(null)}
      />
    </div>
  );
}
