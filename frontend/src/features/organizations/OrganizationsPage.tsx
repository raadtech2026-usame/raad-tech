import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { Building2, Plus, Search } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../shared/stores/authStore";
import { ApiError } from "../../shared/api/types";
import { DataTable, type DataTableColumnMeta } from "../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../shared/components/Table/FilterChips";
import { Pagination } from "../../shared/components/Table/Pagination";
import { LeadCell, MonoText } from "../../shared/components/Table/cells";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { Input } from "../../shared/components/Input/Input";
import { CreateOrganizationForm } from "./CreateOrganizationForm";
import {
  listOrganizations,
  listRegions,
  type Organization,
} from "./api";
import { orgTypeLabel, statusLabel, statusTone } from "./labels";
import { listPlans, listSubscriptions } from "../billing/api";
import { subscriptionStatusLabel, subscriptionStatusTone } from "../billing/labels";
import styles from "./OrganizationsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "suspended", label: "Suspended", tone: "warning" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * `/platform/organizations` (API Contracts §4.1) — Founder/Regional Manager/Support Staff/
 * Finance Staff land here per `RouteGuard`'s `PLATFORM_ROLES` (`app/router.tsx`); Org Admins
 * never reach this route (`organizationNav` has no Organizations entry — they don't manage
 * tenants, CLAUDE.md's own note on this). Not yet scope-filtered server-side for Regional
 * Manager/Support Staff (a system-wide, already-flagged backend gap — see `./api.ts`'s own
 * `listOrganizations` docstring), so every viewer currently sees every organization.
 */
export function OrganizationsPage() {
  usePageHeader("Organizations", "Platform tenants — schools and transport operators on RAAD");

  const principal = useAuthStore((s) => s.principal);

  const [createOpen, setCreateOpen] = useState(false);
  const [searchInput, setSearchInput] = useState("");

  const {
    rows,
    total,
    page,
    pageSize,
    sort,
    filters,
    isLoading,
    isError,
    error,
    setPage,
    toggleSort,
    setFilter,
    setSearch,
  } = usePaginatedQuery({
    queryKey: ["organizations", "list"],
    fetcher: listOrganizations,
    initialSort: { field: "name", direction: "asc" },
  });

  // Debounces the free-text `?q=` search so it doesn't fire a request on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Read-only region-name lookup: `Organization.regionId` has no join, only an opaque id, so a
  // friendly region name in the table/drawer needs a separate `GET /regions` read. Up to
  // `MAX_PAGE_SIZE` (100) regions resolve to a name; beyond that this falls back to the raw id
  // rather than fabricating a name — a real, documented limitation, not a bug.
  const regionsLookup = useQuery({
    queryKey: ["regions", "lookup"],
    queryFn: () =>
      listRegions({ page: 1, pageSize: 100, sort: { field: "name", direction: "asc" }, filters: {}, search: "" }),
    staleTime: 60_000,
  });

  const regionNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const region of regionsLookup.data?.data ?? []) {
      map.set(region.id, region.name);
    }
    return map;
  }, [regionsLookup.data]);

  const navigate = useNavigate();

  // One request each, joined in memory. Both catalogues are small and capped, so this is a
  // constant two extra reads for the whole page — never one per row.
  const subscriptionsLookup = useQuery({
    queryKey: ["billing", "subscriptions", "org-list-lookup"],
    queryFn: () =>
      listSubscriptions({
        page: 1,
        pageSize: 100,
        sort: null,
        filters: {},
        search: "",
      }),
    staleTime: 60_000,
  });
  const plansLookup = useQuery({
    queryKey: ["billing", "plans", "lookup"],
    queryFn: () =>
      listPlans({ page: 1, pageSize: 100, sort: null, filters: {}, search: "" }),
    staleTime: 5 * 60_000,
  });

  const subscriptionByOrg = useMemo(() => {
    const map = new Map<string, (typeof subscriptionsLookup.data extends undefined ? never : NonNullable<typeof subscriptionsLookup.data>)["data"][number]>();
    for (const subscription of subscriptionsLookup.data?.data ?? []) {
      map.set(subscription.organizationId, subscription);
    }
    return map;
  }, [subscriptionsLookup.data]);

  const planNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const plan of plansLookup.data?.data ?? []) {
      map.set(plan.id, plan.name);
    }
    return map;
  }, [plansLookup.data]);

  const columns = useMemo<ColumnDef<Organization, unknown>[]>(
    () => [
      {
        id: "name",
        header: "Organization",
        meta: { sortField: "name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <LeadCell
            icon={<Building2 size={15} />}
            title={row.original.name}
            subtitle={orgTypeLabel(row.original.orgType)}
            iconTint="var(--color-brand-primary-tint)"
            iconColor="var(--color-brand-primary)"
          />
        ),
      },
      {
        id: "region",
        header: "Region",
        cell: ({ row }) => {
          const name = regionNameById.get(row.original.regionId);
          return name ? <span>{name}</span> : <MonoText>{row.original.regionId}</MonoText>;
        },
      },
      {
        id: "status",
        header: "Status",
        meta: { sortField: "status" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={statusTone(row.original.status)} dot>
            {statusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        id: "plan",
        header: "Plan",
        cell: ({ row }) => {
          const subscription = subscriptionByOrg.get(row.original.id);
          if (!subscription) return <span className={styles.noPlan}>—</span>;
          return <span>{planNameById.get(subscription.planId) ?? subscription.planId}</span>;
        },
      },
      {
        id: "subscription",
        header: "Subscription",
        cell: ({ row }) => {
          const subscription = subscriptionByOrg.get(row.original.id);
          if (subscriptionsLookup.isPending) return <span className={styles.noPlan}>…</span>;
          // An organization with no subscription cannot open its dashboard at all
          // (ADR-0039, amended 2026-09-09), so it is called out rather than left blank.
          if (!subscription) return <Badge variant="danger" dot>No subscription</Badge>;
          return (
            <Badge variant={subscriptionStatusTone(subscription.status)} dot>
              {subscriptionStatusLabel(subscription.status)}
            </Badge>
          );
        },
      },
      {
        id: "renewal",
        header: "Renews",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const subscription = subscriptionByOrg.get(row.original.id);
          const renewal = subscription?.currentPeriodEnd ?? null;
          return <span>{renewal ? formatDate(renewal) : "—"}</span>;
        },
      },
      {
        id: "createdAt",
        header: "Created",
        meta: { sortField: "created_at", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{formatDate(row.original.createdAt)}</span>,
      },
    ],
    [regionNameById, subscriptionByOrg, planNameById, subscriptionsLookup.isPending],
  );

  const activeStatusFilter = filters.status ?? "all";
  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — Finance Staff's
  // documented "billing scope only" (`.claude/rules/security.md` #3) already excludes them from
  // every operational create/edit action in `navConfig.ts`; hiding this button follows that same
  // established precedent one level deeper. The backend's own RBAC permission check
  // (`organization.organizations.create`) remains the real, unbypassable gate regardless.
  const canCreate = principal?.role !== "finance_staff";

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <FilterChips
          options={STATUS_FILTERS}
          activeId={activeStatusFilter}
          onSelect={(id) => setFilter("status", id === "all" ? null : id)}
        />
        <div className={styles.toolbarActions}>
          <Input
            icon={<Search size={14} />}
            placeholder="Search organizations…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search organizations"
          />
          {canCreate && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Organization
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Building2 size={22} />}
          title="Could not load organizations"
          description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            data={rows}
            getRowId={(row) => row.id}
            isLoading={isLoading}
            sort={sort}
            onSortChange={toggleSort}
            onRowClick={(organization) =>
              navigate(`/platform/organizations/${organization.id}`)
            }
            emptyState={
              <EmptyState
                icon={<Building2 size={22} />}
                title="No organizations yet"
                description="Organizations you register will appear here."
                action={
                  canCreate ? (
                    <Button
                      variant="secondary"
                      leadingIcon={<Plus size={15} />}
                      onClick={() => setCreateOpen(true)}
                    >
                      New Organization
                    </Button>
                  ) : undefined
                }
              />
            }
          />
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
        </>
      )}



      <CreateOrganizationForm open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
