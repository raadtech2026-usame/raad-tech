import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, Truck } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { DataTable, type DataTableColumnMeta } from "../../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../../shared/components/Table/FilterChips";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { LeadCell, MonoText } from "../../../shared/components/Table/cells";
import { DetailDrawer } from "../../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Input } from "../../../shared/components/Input/Input";
import { CreateVehicleForm } from "./CreateVehicleForm";
import {
  listOrganizationsForPicker,
  listVehicles,
  updateVehicleStatus,
  type Vehicle,
  type VehicleStatus,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./VehiclesPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
  { id: "maintenance", label: "Under maintenance", tone: "warning" },
];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/**
 * `/platform/vehicles` and `/org/vehicles` (API Contracts §4.2: "Org Admin (+RAAD in scope)") —
 * one shared page component reused at both routes (`app/router.tsx`'s `PLATFORM_BUILT_ROUTES` and
 * `ORGANIZATION_BUILT_ROUTES`), the same way `fleet_device.api.routers` itself has no separate
 * platform-vs-org endpoint — a single `GET/POST /vehicles` surface, gated by `require_permission`
 * only. Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder`/`org_admin`
 * hold `fleet_device.vehicles.create`/`.update` — `regional_manager`/`support_staff` hold
 * `.read` only (view, no register/status-change), and `finance_staff`/`driver`/`parent` hold
 * none of the three at all. `canManage` below is a presentation-layer hint only
 * (`.claude/rules/frontend.md` #2); the backend's own `require_permission` is the real gate — a
 * direct visit by a role with no `.read` permission renders the honest error state below from the
 * backend's own 403, not a fabricated empty list.
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap — see `./api.ts`'s
 * `listVehicles` docstring), so every viewer who can reach this route currently sees every
 * vehicle across every organization, including an Org Admin on `/org/vehicles`.
 */
export function VehiclesPage() {
  usePageHeader("Vehicles", "Buses on the platform, their status, and their assigned devices");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
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
    queryKey: ["vehicles", "list"],
    fetcher: listVehicles,
    initialSort: { field: "plate_no", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Read-only organization-name lookup: `Vehicle.organizationId` has no join, only an opaque id,
  // so a friendly name in the table/drawer needs a separate `GET /organizations` read — the same
  // pattern `OrganizationsPage`'s own `regionsLookup`/`UsersPage`'s own `organizationsLookup`
  // establish.
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
    mutationFn: (input: { id: string; status: VehicleStatus }) => updateVehicleStatus(input.id, input.status),
    onSuccess: (vehicle) => {
      queryClient.invalidateQueries({ queryKey: ["vehicles", "list"] });
      setSelectedVehicle(vehicle);
      toast.success("Vehicle updated", `${vehicle.plateNo} is now ${statusLabel(vehicle.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the vehicle.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: VehicleStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedVehicle?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<Vehicle, unknown>[]>(
    () => [
      {
        id: "plateNo",
        header: "Vehicle",
        meta: { sortField: "plate_no" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <LeadCell
            icon={<Truck size={15} />}
            title={row.original.plateNo}
            subtitle={row.original.label ?? "No label"}
            iconTint="var(--color-brand-primary-tint)"
            iconColor="var(--color-brand-primary)"
          />
        ),
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
        id: "capacity",
        header: "Capacity",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{row.original.capacity ?? "—"}</span>,
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
        id: "createdAt",
        header: "Created",
        meta: { sortField: "created_at", align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{formatDate(row.original.createdAt)}</span>,
      },
    ],
    [organizationNameById],
  );

  const activeStatusFilter = filters.status ?? "all";

  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — see this component's
  // own docstring for the exact RBAC citation.
  const canManage = principal?.role === "founder" || principal?.role === "org_admin";

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
            placeholder="Search vehicles…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search vehicles"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Vehicle
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Truck size={22} />}
          title="Could not load vehicles"
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
            onRowClick={setSelectedVehicle}
            emptyState={
              <EmptyState
                icon={<Truck size={22} />}
                title="No vehicles yet"
                description="Vehicles you register will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Vehicle
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
        open={selectedVehicle !== null}
        onClose={() => setSelectedVehicle(null)}
        icon={<Truck size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedVehicle?.plateNo}
        subtitle={selectedVehicle?.label ?? undefined}
        status={
          selectedVehicle && (
            <Badge variant={statusTone(selectedVehicle.status)} dot>
              {statusLabel(selectedVehicle.status)}
            </Badge>
          )
        }
        rows={
          selectedVehicle
            ? [
                {
                  key: "Organization",
                  value: organizationNameById.get(selectedVehicle.organizationId) ?? selectedVehicle.organizationId,
                },
                { key: "Capacity", value: selectedVehicle.capacity ?? "Not set" },
                { key: "Vehicle ID", value: <MonoText>{selectedVehicle.id}</MonoText> },
                { key: "Created", value: formatDate(selectedVehicle.createdAt) },
                { key: "Updated", value: formatDate(selectedVehicle.updatedAt) },
              ]
            : []
        }
        footer={
          selectedVehicle &&
          canManage && (
            <div className={styles.drawerActions}>
              {selectedVehicle.status !== "active" && (
                <Button
                  variant="secondary"
                  loading={isPendingFor("active")}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedVehicle.id, status: "active" })}
                >
                  Activate
                </Button>
              )}
              {selectedVehicle.status !== "maintenance" && (
                <Button
                  variant="secondary"
                  loading={isPendingFor("maintenance")}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedVehicle.id, status: "maintenance" })}
                >
                  Mark under maintenance
                </Button>
              )}
              {selectedVehicle.status !== "inactive" && (
                <Button
                  variant="danger"
                  loading={isPendingFor("inactive")}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedVehicle.id, status: "inactive" })}
                >
                  Deactivate
                </Button>
              )}
            </div>
          )
        }
      />

      <CreateVehicleForm open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
