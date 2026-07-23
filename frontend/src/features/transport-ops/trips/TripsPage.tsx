import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { CalendarClock, Plus, UserRound } from "lucide-react";
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
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { ScheduleTripForm } from "./ScheduleTripForm";
import { ChangeTripDriverForm } from "./ChangeTripDriverForm";
import {
  endTrip,
  getTrip,
  listDriversForPicker,
  listOrganizationsForPicker,
  listRoutesForPicker,
  listTrips,
  listVehiclesForPicker,
  startTrip,
  type TripSummary,
} from "./api";
import { statusLabel, statusTone, tripTypeLabel } from "./labels";
import styles from "./TripsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "scheduled", label: "Scheduled", tone: "info" },
  { id: "in_progress", label: "In progress", tone: "success" },
  { id: "interrupted", label: "Interrupted", tone: "warning" },
  { id: "completed", label: "Completed", tone: "neutral" },
];

const TYPE_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All trip types", tone: "neutral" },
  { id: "morning", label: "Morning", tone: "info" },
  { id: "afternoon", label: "Afternoon", tone: "purple" },
];

function formatScheduledDate(isoDate: string): string {
  // `scheduled_date` is a plain `date` (`YYYY-MM-DD`, no time/zone component) — parsed as UTC
  // midnight so it never shifts a day backward in a negative-offset timezone.
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/**
 * `/platform/trips` and `/org/trips` (API Contracts §4.3 line 129: "Org Admin") — one shared page
 * component reused at both routes, mirroring `RoutesPage`/`DriversPage`'s identical posture. Per
 * the seeded RBAC matrix, only `founder`/`org_admin` hold `transport_ops.trips.create`/
 * `.change_driver` — `regional_manager`/`support_staff` hold `.list`/`.read` only (view, no
 * schedule/start/end/change-driver), and `finance_staff`/`parent` hold none at all. `driver` holds
 * `.list`/`.read`/`.start`/`.end` but has no web dashboard at all (`.claude/rules/flutter.md` #1),
 * so this page never needs to render a Driver-facing start/end control. `canManage` below is a
 * presentation-layer hint only (`.claude/rules/frontend.md` #2).
 *
 * **The list table shows only vehicle/driver/route *ids*** — `GET /trips` returns
 * `TripSummaryResponse` (no names, see `./api.ts`'s `TripSummary` docstring). Names are resolved
 * via three best-effort, page-wide id->name lookups (`listVehiclesForPicker`/`listDriversForPicker`/
 * `listRoutesForPicker`, each capped at 100 rows) rather than a per-row detail fetch — the same
 * `organizationNameById` pattern `RoutesPage`/`StudentsPage` already establish, extended to three
 * lookups since a trip references three other aggregates. Opening the detail drawer issues a
 * second `GET /trips/{id}` for `organizationId`/`startedAt`/`endedAt`/timestamps.
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap).
 */
export function TripsPage() {
  usePageHeader("Trips", "Scheduled and in-progress trips across the platform");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedTrip, setSelectedTrip] = useState<TripSummary | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [changeDriverOpen, setChangeDriverOpen] = useState(false);

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
  } = usePaginatedQuery({
    queryKey: ["trips", "list"],
    fetcher: listTrips,
    initialSort: { field: "scheduled_date", direction: "desc" },
  });

  // Full-detail fetch for the drawer — see this component's own docstring for why the list row
  // alone (`TripSummary`) can't supply organization/started-at/ended-at/timestamp fields.
  const detailQuery = useQuery({
    queryKey: ["trips", "detail", selectedTrip?.id],
    queryFn: () => getTrip(selectedTrip!.id),
    enabled: selectedTrip !== null,
  });

  const organizationsLookup = useQuery({
    queryKey: ["organizations", "picker-lookup"],
    queryFn: () => listOrganizationsForPicker(""),
    staleTime: 60_000,
  });

  const vehiclesLookup = useQuery({
    queryKey: ["vehicles", "trips-page-lookup"],
    queryFn: () => listVehiclesForPicker("", ""),
    staleTime: 60_000,
  });

  const driversLookup = useQuery({
    queryKey: ["drivers", "trips-page-lookup"],
    queryFn: () => listDriversForPicker(""),
    staleTime: 60_000,
  });

  const routesLookup = useQuery({
    queryKey: ["routes", "trips-page-lookup"],
    queryFn: () => listRoutesForPicker(""),
    staleTime: 60_000,
  });

  const organizationNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const org of organizationsLookup.data ?? []) {
      map.set(org.id, org.name);
    }
    return map;
  }, [organizationsLookup.data]);

  const vehiclePlateById = useMemo(() => {
    const map = new Map<string, string>();
    for (const vehicle of vehiclesLookup.data ?? []) {
      map.set(vehicle.id, vehicle.plateNo);
    }
    return map;
  }, [vehiclesLookup.data]);

  const driverLicenseById = useMemo(() => {
    const map = new Map<string, string>();
    for (const driver of driversLookup.data ?? []) {
      map.set(driver.id, driver.licenseNo);
    }
    return map;
  }, [driversLookup.data]);

  const routeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const route of routesLookup.data ?? []) {
      map.set(route.id, route.name);
    }
    return map;
  }, [routesLookup.data]);

  const startMutation = useMutation({
    mutationFn: (id: string) => startTrip(id),
    onSuccess: (trip) => {
      queryClient.invalidateQueries({ queryKey: ["trips", "list"] });
      queryClient.invalidateQueries({ queryKey: ["trips", "detail", trip.id] });
      setSelectedTrip({
        id: trip.id,
        vehicleId: trip.vehicleId,
        driverId: trip.driverId,
        routeId: trip.routeId,
        tripType: trip.tripType,
        status: trip.status,
        scheduledDate: trip.scheduledDate,
      });
      toast.success("Trip started", "The trip is now in progress.");
    },
    onError: (mutationError) => {
      const message = mutationError instanceof ApiError ? mutationError.message : "Could not start the trip.";
      toast.error("Start failed", message);
    },
  });

  const endMutation = useMutation({
    mutationFn: (id: string) => endTrip(id),
    onSuccess: (trip) => {
      queryClient.invalidateQueries({ queryKey: ["trips", "list"] });
      queryClient.invalidateQueries({ queryKey: ["trips", "detail", trip.id] });
      setSelectedTrip({
        id: trip.id,
        vehicleId: trip.vehicleId,
        driverId: trip.driverId,
        routeId: trip.routeId,
        tripType: trip.tripType,
        status: trip.status,
        scheduledDate: trip.scheduledDate,
      });
      toast.success("Trip ended", "The trip has been marked completed.");
    },
    onError: (mutationError) => {
      const message = mutationError instanceof ApiError ? mutationError.message : "Could not end the trip.";
      toast.error("End failed", message);
    },
  });

  const columns = useMemo<ColumnDef<TripSummary, unknown>[]>(
    () => [
      {
        id: "route",
        header: "Trip",
        meta: { sortField: "scheduled_date" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <LeadCell
            icon={<CalendarClock size={15} />}
            iconTint="var(--color-brand-primary-tint)"
            iconColor="var(--color-brand-primary)"
            title={routeNameById.get(row.original.routeId) ?? row.original.routeId}
            subtitle={`${tripTypeLabel(row.original.tripType)} · ${formatScheduledDate(row.original.scheduledDate)}`}
          />
        ),
      },
      {
        id: "driver",
        header: "Driver",
        cell: ({ row }) => <span>{driverLicenseById.get(row.original.driverId) ?? row.original.driverId}</span>,
      },
      {
        id: "vehicle",
        header: "Vehicle",
        cell: ({ row }) => <span>{vehiclePlateById.get(row.original.vehicleId) ?? row.original.vehicleId}</span>,
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
    [routeNameById, driverLicenseById, vehiclePlateById],
  );

  const activeStatusFilter = filters.status ?? "all";
  const activeTypeFilter = filters.trip_type ?? "all";

  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — see this
  // component's own docstring for the exact RBAC citation.
  const canManage = principal?.role === "founder" || principal?.role === "org_admin";

  const detail = detailQuery.data;

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          <FilterChips
            options={STATUS_FILTERS}
            activeId={activeStatusFilter}
            onSelect={(id) => setFilter("status", id === "all" ? null : id)}
          />
          <FilterChips
            options={TYPE_FILTERS}
            activeId={activeTypeFilter}
            onSelect={(id) => setFilter("trip_type", id === "all" ? null : id)}
          />
        </div>
        <div className={styles.toolbarActions}>
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setScheduleOpen(true)}>
              Schedule Trip
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<CalendarClock size={22} />}
          title="Could not load trips"
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
            onRowClick={setSelectedTrip}
            emptyState={
              <EmptyState
                icon={<CalendarClock size={22} />}
                title="No trips yet"
                description="Trips you schedule will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setScheduleOpen(true)}>
                      Schedule Trip
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
        open={selectedTrip !== null}
        onClose={() => setSelectedTrip(null)}
        icon={<CalendarClock size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedTrip ? routeNameById.get(selectedTrip.routeId) ?? selectedTrip.routeId : undefined}
        subtitle={selectedTrip ? tripTypeLabel(selectedTrip.tripType) : undefined}
        status={
          selectedTrip && (
            <Badge variant={statusTone(selectedTrip.status)} dot>
              {statusLabel(selectedTrip.status)}
            </Badge>
          )
        }
        rows={
          selectedTrip
            ? detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !detail
                ? [{ key: "Details", value: "Could not load details." }]
                : [
                    {
                      key: "Organization",
                      value: organizationNameById.get(detail.organizationId) ?? detail.organizationId,
                    },
                    { key: "Vehicle", value: vehiclePlateById.get(detail.vehicleId) ?? detail.vehicleId },
                    { key: "Driver", value: driverLicenseById.get(detail.driverId) ?? detail.driverId },
                    { key: "Route", value: routeNameById.get(detail.routeId) ?? detail.routeId },
                    { key: "Scheduled date", value: formatScheduledDate(detail.scheduledDate) },
                    { key: "Started", value: detail.startedAt ? formatDateTime(detail.startedAt) : "Not started" },
                    { key: "Ended", value: detail.endedAt ? formatDateTime(detail.endedAt) : "Not ended" },
                    { key: "Trip ID", value: <MonoText>{detail.id}</MonoText> },
                  ]
            : []
        }
        footer={
          selectedTrip &&
          canManage && (
            <div className={styles.drawerActions}>
              {selectedTrip.status === "scheduled" && (
                <Button
                  variant="primary"
                  loading={startMutation.isPending}
                  disabled={startMutation.isPending}
                  onClick={() => startMutation.mutate(selectedTrip.id)}
                >
                  Start trip
                </Button>
              )}
              {(selectedTrip.status === "in_progress" || selectedTrip.status === "interrupted") && (
                <Button
                  variant="secondary"
                  loading={endMutation.isPending}
                  disabled={endMutation.isPending}
                  onClick={() => endMutation.mutate(selectedTrip.id)}
                >
                  End trip
                </Button>
              )}
              <Button
                variant="secondary"
                leadingIcon={<UserRound size={14} />}
                onClick={() => setChangeDriverOpen(true)}
              >
                Change driver
              </Button>
            </div>
          )
        }
      />

      <ScheduleTripForm open={scheduleOpen} onClose={() => setScheduleOpen(false)} />

      <ChangeTripDriverForm
        open={changeDriverOpen}
        onClose={() => setChangeDriverOpen(false)}
        trip={detail ?? null}
      />
    </div>
  );
}
