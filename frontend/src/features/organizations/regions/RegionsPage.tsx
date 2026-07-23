import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Globe, Plus, Search } from "lucide-react";
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
import { CreateRegionForm } from "./CreateRegionForm";
import { listRegions, updateRegionStatus, type Region, type RegionStatus } from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./RegionsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const ALL_STATUSES: RegionStatus[] = ["active", "inactive"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/**
 * `/platform/regions` — Founder-only (only `founder` holds `organization.regions.create`/
 * `.update` in the seeded RBAC matrix; `regional_manager` holds `.read` only, and no other
 * platform role holds any `organization.regions.*` permission at all). `canManage` below is a
 * presentation-layer hint only (`.claude/rules/frontend.md` #2) — the backend's own
 * `require_permission` is the real gate.
 *
 * Regions have no per-organization scoping of their own (`regions` carries no
 * `organization_id` — Database Design §4.1) — closing the gap that previously left
 * `POST /organizations`'s required `region_id` field permanently unsatisfiable in any fresh
 * environment (no seed data, no UI to create one). `GET /regions` already returns the full
 * `RegionResponse` shape, so — unlike `Driver`/`Route` — no second detail fetch is needed; the
 * list row itself is the complete record, the same simpler pattern `VehiclesPage.tsx` uses.
 */
export function RegionsPage() {
  usePageHeader("Regions", "Platform regions used for tenant and staff scoping");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedRegion, setSelectedRegion] = useState<Region | null>(null);
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
    queryKey: ["regions", "management-list"],
    fetcher: listRegions,
    initialSort: { field: "name", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const statusMutation = useMutation({
    mutationFn: (input: { id: string; status: RegionStatus }) => updateRegionStatus(input.id, input.status),
    onSuccess: (region) => {
      queryClient.invalidateQueries({ queryKey: ["regions", "management-list"] });
      setSelectedRegion(region);
      toast.success("Region updated", `${region.name} is now ${statusLabel(region.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the region.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: RegionStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedRegion?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<Region, unknown>[]>(
    () => [
      {
        id: "name",
        header: "Region",
        meta: { sortField: "name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{row.original.name}</span>,
      },
      {
        id: "geographicScope",
        header: "Geographic scope",
        cell: ({ row }) => <span>{row.original.geographicScope ?? "—"}</span>,
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
  const canManage = principal?.role === "founder";

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
            placeholder="Search regions…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search regions"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Region
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Globe size={22} />}
          title="Could not load regions"
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
            onRowClick={setSelectedRegion}
            emptyState={
              <EmptyState
                icon={<Globe size={22} />}
                title="No regions yet"
                description="Regions you create will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Region
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
        open={selectedRegion !== null}
        onClose={() => setSelectedRegion(null)}
        icon={<Globe size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedRegion?.name}
        status={
          selectedRegion && (
            <Badge variant={statusTone(selectedRegion.status)} dot>
              {statusLabel(selectedRegion.status)}
            </Badge>
          )
        }
        rows={
          selectedRegion
            ? [
                { key: "Geographic scope", value: selectedRegion.geographicScope ?? "Not set" },
                { key: "Region ID", value: <MonoText>{selectedRegion.id}</MonoText> },
                { key: "Created", value: formatDate(selectedRegion.createdAt) },
                { key: "Updated", value: formatDate(selectedRegion.updatedAt) },
              ]
            : []
        }
        footer={
          selectedRegion &&
          canManage && (
            <div className={styles.drawerActions}>
              {ALL_STATUSES.filter((status) => status !== selectedRegion.status).map((status) => (
                <Button
                  key={status}
                  variant={status === "inactive" ? "danger" : "secondary"}
                  loading={isPendingFor(status)}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedRegion.id, status })}
                >
                  {status === "active" ? "Activate" : "Deactivate"}
                </Button>
              ))}
            </div>
          )
        }
      />

      <CreateRegionForm open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
