import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Navigation, Plus, Search } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { DataTable, type DataTableColumnMeta } from "../../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../../shared/components/Table/FilterChips";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { MonoText } from "../../../shared/components/Table/cells";
import { DetailDrawer } from "../../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { CreateRouteForm } from "./CreateRouteForm";
import { AddStopForm } from "./AddStopForm";
import {
  getRoute,
  listOrganizationsForPicker,
  listRoutes,
  updateRouteStatus,
  type Route,
  type RouteStatus,
  type RouteSummary,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./RoutesPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const ALL_STATUSES: RouteStatus[] = ["active", "inactive"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** The "Stops" section of the route detail drawer — lists the route's stops, always in
 * `sequence_no` order (embedded on `GET /routes/{id}`, already server-sorted). For `canManage`
 * roles, an "Add stop" action opens `AddStopForm`.
 *
 * **No reorder or remove action exists here, deliberately, not by oversight.** `Route.move_stop`/
 * `remove_stop` have no HTTP route this phase (see `./api.ts`'s `addStopToRoute` docstring for
 * the full citation) — building a reorder/remove UI against a non-existent endpoint would be
 * exactly the kind of "invent ahead of an approved backend surface" this project's own
 * discipline forbids (the master roadmap's own F5 risk note calls this out explicitly). The
 * caption below is the honest "why can't I reorder stops" affordance that same note asks for. */
function StopsSection({
  route,
  canManage,
  onAddStop,
}: {
  route: Route;
  canManage: boolean;
  onAddStop: () => void;
}) {
  return (
    <div className={styles.stops}>
      <div className={styles.stopsHeader}>
        <span className={styles.stopsTitle}>Stops</span>
        {canManage && (
          <Button size="sm" variant="secondary" leadingIcon={<Plus size={13} />} onClick={onAddStop}>
            Add stop
          </Button>
        )}
      </div>

      {route.stops.length === 0 && <span className={styles.stopsEmpty}>No stops added yet.</span>}

      {route.stops.map((stop) => (
        <div key={stop.id} className={styles.stopRow}>
          <div>
            <div className={styles.stopName}>
              {stop.sequenceNo}. {stop.name}
            </div>
            <div className={styles.stopMeta}>
              {stop.latitude.toFixed(4)}, {stop.longitude.toFixed(4)}
              {stop.geofenceRadiusM ? ` · ${stop.geofenceRadiusM}m geofence` : ""}
            </div>
          </div>
        </div>
      ))}

      {route.stops.length > 0 && (
        <span className={styles.stopsCaption}>
          Stops are shown in order. Reordering and removing individual stops isn't available yet —
          no backend endpoint exists for it.
        </span>
      )}
    </div>
  );
}

/**
 * `/platform/routes` and `/org/routes` (API Contracts §4.3 line 125: "Org Admin") — one shared
 * page component reused at both routes, mirroring `StudentsPage`/`DriversPage`'s identical
 * posture. Per the seeded RBAC matrix, only `founder`/`org_admin` hold `transport_ops.routes.
 * create`/`.update`/`.routes.stops.create` — `regional_manager`/`support_staff` hold `.list`/
 * `.read`/`.stops.list` only, and `finance_staff`/`driver`/`parent` hold none at all. `canManage`
 * below is a presentation-layer hint only (`.claude/rules/frontend.md` #2).
 *
 * **The list table shows only Name + Status** — `GET /routes` returns `RouteSummaryResponse`
 * (no stops, no organization/timestamps). Opening the detail drawer issues a second
 * `GET /routes/{id}` for the richer fields *and* the embedded, pre-ordered stop list — see
 * `./api.ts`'s `Route`/`RouteSummary` docstrings.
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap).
 */
export function RoutesPage() {
  usePageHeader("Routes", "Routes and their ordered stops across the platform");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedRoute, setSelectedRoute] = useState<RouteSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [addStopOpen, setAddStopOpen] = useState(false);
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
    queryKey: ["routes", "list"],
    fetcher: listRoutes,
    initialSort: { field: "name", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Full-detail fetch for the drawer — see this component's own docstring for why the list row
  // alone (`RouteSummary`) can't supply organization/stop/timestamp fields.
  const detailQuery = useQuery({
    queryKey: ["routes", "detail", selectedRoute?.id],
    queryFn: () => getRoute(selectedRoute!.id),
    enabled: selectedRoute !== null,
  });

  const organizationsLookup = useQuery({
    queryKey: ["organizations", "picker-lookup"],
    queryFn: () => listOrganizationsForPicker(""),
    staleTime: 60_000,
  });

  const organizationNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const org of organizationsLookup.data ?? []) {
      map.set(org.id, org.name);
    }
    return map;
  }, [organizationsLookup.data]);

  const statusMutation = useMutation({
    mutationFn: (input: { id: string; status: RouteStatus }) => updateRouteStatus(input.id, input.status),
    onSuccess: (route) => {
      queryClient.invalidateQueries({ queryKey: ["routes", "list"] });
      queryClient.invalidateQueries({ queryKey: ["routes", "detail", route.id] });
      setSelectedRoute({ id: route.id, name: route.name, status: route.status });
      toast.success("Route updated", `${route.name} is now ${statusLabel(route.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message = mutationError instanceof ApiError ? mutationError.message : "Could not update the route.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: RouteStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedRoute?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<RouteSummary, unknown>[]>(
    () => [
      {
        id: "name",
        header: "Route",
        meta: { sortField: "name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{row.original.name}</span>,
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
    ],
    [],
  );

  const activeStatusFilter = filters.status ?? "all";

  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — see this
  // component's own docstring for the exact RBAC citation.
  const canManage = principal?.role === "founder" || principal?.role === "org_admin";

  const detail = detailQuery.data;
  const nextSequenceNo = detail ? Math.max(0, ...detail.stops.map((s) => s.sequenceNo)) + 1 : 1;

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
            placeholder="Search routes…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search routes"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Route
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Navigation size={22} />}
          title="Could not load routes"
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
            onRowClick={setSelectedRoute}
            emptyState={
              <EmptyState
                icon={<Navigation size={22} />}
                title="No routes yet"
                description="Routes you create will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Route
                    </Button>
                  ) : undefined
                }
              />
            }
          />
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
        </>
      )}

      <DetailDrawer
        open={selectedRoute !== null}
        onClose={() => setSelectedRoute(null)}
        icon={<Navigation size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedRoute?.name}
        status={
          selectedRoute && (
            <Badge variant={statusTone(selectedRoute.status)} dot>
              {statusLabel(selectedRoute.status)}
            </Badge>
          )
        }
        mapSlot={
          detail && (
            <StopsSection route={detail} canManage={canManage} onAddStop={() => setAddStopOpen(true)} />
          )
        }
        rows={
          selectedRoute
            ? detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !detail
                ? [{ key: "Details", value: "Could not load details." }]
                : [
                    {
                      key: "Organization",
                      value: organizationNameById.get(detail.organizationId) ?? detail.organizationId,
                    },
                    { key: "Route ID", value: <MonoText>{detail.id}</MonoText> },
                    { key: "Created", value: formatDate(detail.createdAt) },
                    { key: "Updated", value: formatDate(detail.updatedAt) },
                  ]
            : []
        }
        footer={
          selectedRoute &&
          canManage && (
            <div className={styles.drawerActions}>
              {ALL_STATUSES.filter((status) => status !== selectedRoute.status).map((status) => (
                <Button
                  key={status}
                  variant={status === "inactive" ? "danger" : "secondary"}
                  loading={isPendingFor(status)}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedRoute.id, status })}
                >
                  {status === "active" ? "Activate" : "Deactivate"}
                </Button>
              ))}
            </div>
          )
        }
      />

      <CreateRouteForm open={createOpen} onClose={() => setCreateOpen(false)} />

      <AddStopForm
        open={addStopOpen}
        onClose={() => setAddStopOpen(false)}
        routeId={selectedRoute?.id ?? null}
        routeName={selectedRoute?.name}
        nextSequenceNo={nextSequenceNo}
      />
    </div>
  );
}
