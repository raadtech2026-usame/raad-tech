import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, UserRound } from "lucide-react";
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
import { CreateDriverForm } from "./CreateDriverForm";
import {
  getDriver,
  listDrivers,
  listOrganizationsForPicker,
  updateDriverStatus,
  type DriverStatus,
  type DriverSummary,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./DriversPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const ALL_STATUSES: DriverStatus[] = ["active", "inactive"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/**
 * `/platform/drivers` and `/org/drivers` (Phase 10.8's own flagged gap: API Contracts §4.3 lists
 * no `/drivers` resource row at all, unlike `/students`/`/parents` — built anyway on Database
 * Design §6.1/ADR-0001's unambiguous table ownership, the same precedent `student_parents`
 * already established for an identically undocumented sub-resource). One shared page component
 * reused at both routes, mirroring `StudentsPage`/`ParentsPage`'s identical posture.
 *
 * Per the seeded RBAC matrix, only `founder`/`org_admin` hold `transport_ops.drivers.create`/
 * `.update` — `regional_manager`/`support_staff` hold `.list`/`.read` only, and `finance_staff`/
 * `driver`/`parent` hold none at all. `canManage` below is a presentation-layer hint only
 * (`.claude/rules/frontend.md` #2); the backend's own `require_permission` is the real gate.
 *
 * **The list table shows only License No + Status** — `GET /drivers` returns
 * `DriverSummaryResponse` (`id`/`license_no`/`status` only, see `./api.ts`'s `DriverSummary`
 * docstring: `Driver` has no `full_name` column at all, unlike `Student`/`Parent`). Opening the
 * detail drawer issues a second `GET /drivers/{id}` for the organization/linked-user/timestamp
 * fields, shown once that request resolves (a `Skeleton` placeholder covers the gap, never a
 * fabricated value).
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap), so every viewer
 * who can reach this route currently sees every driver, not just their own organization's.
 */
export function DriversPage() {
  usePageHeader("Drivers", "Drivers registered across the platform");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedDriver, setSelectedDriver] = useState<DriverSummary | null>(null);
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
    queryKey: ["drivers", "list"],
    fetcher: listDrivers,
    initialSort: { field: "license_no", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Full-detail fetch for the drawer — see this component's own docstring for why the list row
  // alone (`DriverSummary`) can't supply organization/linked-user/timestamp fields.
  const detailQuery = useQuery({
    queryKey: ["drivers", "detail", selectedDriver?.id],
    queryFn: () => getDriver(selectedDriver!.id),
    enabled: selectedDriver !== null,
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
    mutationFn: (input: { id: string; status: DriverStatus }) => updateDriverStatus(input.id, input.status),
    onSuccess: (driver) => {
      queryClient.invalidateQueries({ queryKey: ["drivers", "list"] });
      queryClient.invalidateQueries({ queryKey: ["drivers", "detail", driver.id] });
      setSelectedDriver({ id: driver.id, licenseNo: driver.licenseNo, status: driver.status });
      toast.success("Driver updated", `${driver.licenseNo} is now ${statusLabel(driver.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the driver.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: DriverStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedDriver?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<DriverSummary, unknown>[]>(
    () => [
      {
        id: "licenseNo",
        header: "License No",
        meta: { sortField: "license_no" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <MonoText>{row.original.licenseNo}</MonoText>,
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
            placeholder="Search by license no…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search drivers"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Driver
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<UserRound size={22} />}
          title="Could not load drivers"
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
            onRowClick={setSelectedDriver}
            emptyState={
              <EmptyState
                icon={<UserRound size={22} />}
                title="No drivers yet"
                description="Drivers you register will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Driver
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
        open={selectedDriver !== null}
        onClose={() => setSelectedDriver(null)}
        icon={<UserRound size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedDriver?.licenseNo}
        status={
          selectedDriver && (
            <Badge variant={statusTone(selectedDriver.status)} dot>
              {statusLabel(selectedDriver.status)}
            </Badge>
          )
        }
        rows={
          selectedDriver
            ? detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !detail
                ? [{ key: "Details", value: "Could not load details." }]
                : [
                    {
                      key: "Organization",
                      value: organizationNameById.get(detail.organizationId) ?? detail.organizationId,
                    },
                    { key: "Linked user ID", value: <MonoText>{detail.userId}</MonoText> },
                    { key: "Driver ID", value: <MonoText>{detail.id}</MonoText> },
                    { key: "Created", value: formatDate(detail.createdAt) },
                    { key: "Updated", value: formatDate(detail.updatedAt) },
                  ]
            : []
        }
        footer={
          selectedDriver &&
          canManage && (
            <div className={styles.drawerActions}>
              {ALL_STATUSES.filter((status) => status !== selectedDriver.status).map((status) => (
                <Button
                  key={status}
                  variant={status === "inactive" ? "danger" : "secondary"}
                  loading={isPendingFor(status)}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedDriver.id, status })}
                >
                  {status === "active" ? "Activate" : "Deactivate"}
                </Button>
              ))}
            </div>
          )
        }
      />

      <CreateDriverForm open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
