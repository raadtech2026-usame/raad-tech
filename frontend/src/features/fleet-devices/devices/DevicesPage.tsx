import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Cpu, Link2, Plus, Search } from "lucide-react";
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
import { RegisterDeviceWizard } from "./RegisterDeviceWizard";
import { AssignDeviceForm, type AssignDeviceMode } from "./AssignDeviceForm";
import {
  activateDevice,
  listDevices,
  listOrganizationsForPicker,
  unassignDevice,
  updateDeviceLifecycle,
  type Device,
  type VehicleOption,
} from "./api";
import { lifecycleLabel, lifecycleTone } from "./labels";
import styles from "./DevicesPage.module.css";

const LIFECYCLE_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "registered", label: "Registered", tone: "neutral" },
  { id: "activated", label: "Activated", tone: "info" },
  { id: "assigned", label: "Assigned", tone: "success" },
  { id: "suspended", label: "Suspended", tone: "warning" },
  { id: "retired", label: "Retired", tone: "danger" },
];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type LifecycleAction = "activate" | "suspend" | "reactivate" | "retire";

/**
 * `/platform/devices` only (Device Domain Overhaul architecture review) — **not** `/org/devices`
 * anymore. RAAD owns and manages all GPS/MDVR hardware; schools never register, configure, or
 * even view raw device records. Per the corrected RBAC matrix (migration `22e94bc4e924`):
 * `founder`/`support_staff` hold the full `fleet_device.devices.*` set — create/update/activate
 * (`canManageLifecycle`) and assign/reassign/unassign (`canAssign`), both identical sets now
 * that "RAAD technician" maps to `support_staff`. `regional_manager` holds `.read` only (view,
 * no actions); `org_admin`/`finance_staff`/`driver`/`parent` hold none of
 * `fleet_device.devices.*` at all. Both flags are presentation-layer hints only
 * (`.claude/rules/frontend.md` #2) — the backend's own `require_permission` is the real,
 * unbypassable gate. An Org Admin's own device-connectivity visibility is served instead by
 * `VehiclesPage`'s "Tracking" drawer section, which carries no device identifier.
 *
 * New device registration goes through `RegisterDeviceWizard` (register → activate → assign as
 * one guided flow), not a plain create-modal — see that component's own docstring for the full
 * onboarding-workflow design. `AssignDeviceForm` stays here for reassigning an *existing*
 * device from this page's own detail drawer.
 *
 * **Camera management is deliberately not built here.** `fleet_device.api.routers`'s own module
 * docstring: "Camera registration has an application use-case but no approved endpoint — API
 * Contracts §4.2 lists no camera route, so none is exposed." `DeviceResponse.cameras` is still
 * read and shown (an honest reflection of whatever the backend actually returns — currently
 * always empty, since there is no way to add one through this API), but no "add camera"
 * affordance exists, matching this project's "never fake a capability the backend doesn't have"
 * discipline (the same posture F1 took for billing-model editing).
 *
 * **Why a device's current vehicle assignment cannot be shown after a page reload:**
 * `DeviceResponse` carries no `vehicle_id`/assignment field at all, and there is no
 * `GET /devices/{id}/assignment`-equivalent read route anywhere in this backend — the *only*
 * place this frontend ever learns which vehicle a device is bound to is the response of
 * `assign`/`reassign` themselves (`DeviceAssignmentResponse`). `recentAssignments` below tracks
 * that, keyed by device id, for the lifetime of this page only — a real, flagged limitation, not
 * a bug: a `lifecycle_state === "assigned"` device this page didn't itself just bind shows
 * "Assigned" with no vehicle name, honestly, rather than a fabricated one.
 *
 * Not yet scope-filtered server-side (the same system-wide, already-flagged gap every list
 * endpoint in this codebase carries — see `./api.ts`'s `listDevices` docstring).
 */
export function DevicesPage() {
  usePageHeader("Devices", "GPS/MDVR terminals, their lifecycle, and their vehicle binding");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [assignMode, setAssignMode] = useState<AssignDeviceMode | null>(null);
  const [searchInput, setSearchInput] = useState("");
  // See this component's own docstring — session-only, not a persistent read model.
  const [recentAssignments, setRecentAssignments] = useState<Map<string, VehicleOption>>(new Map());

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
    queryKey: ["devices", "list"],
    fetcher: listDevices,
    initialSort: { field: "terminal_id", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

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

  const lifecycleMutation = useMutation({
    mutationFn: (input: { id: string; action: LifecycleAction }) => {
      if (input.action === "activate") {
        return activateDevice(input.id);
      }
      const lifecycleState = input.action === "reactivate" ? "activated" : input.action;
      return updateDeviceLifecycle(input.id, lifecycleState as "activated" | "suspended" | "retired");
    },
    onSuccess: (device) => {
      queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
      setSelectedDevice(device);
      toast.success("Device updated", `${device.terminalId} is now ${lifecycleLabel(device.lifecycleState).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the device.";
      toast.error("Update failed", message);
    },
  });

  const unassignMutation = useMutation({
    mutationFn: (deviceId: string) => unassignDevice(deviceId),
    onSuccess: (_assignment, deviceId) => {
      queryClient.invalidateQueries({ queryKey: ["devices", "list"] });
      setRecentAssignments((prev) => {
        const next = new Map(prev);
        next.delete(deviceId);
        return next;
      });
      // `unassign_device` returns a `DeviceAssignmentResponse`, not a `DeviceResponse` — the
      // resulting lifecycle state is hardcoded here rather than guessed, matching
      // `entities.Device.mark_unassigned`'s deterministic Assigned→Activated edge exactly.
      setSelectedDevice((prev) => (prev && prev.id === deviceId ? { ...prev, lifecycleState: "activated" } : prev));
      toast.success("Device unassigned", "The device is now unbound from its vehicle.");
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not unassign the device.";
      toast.error("Unassign failed", message);
    },
  });

  function isLifecyclePendingFor(action: LifecycleAction): boolean {
    return (
      lifecycleMutation.isPending &&
      lifecycleMutation.variables?.id === selectedDevice?.id &&
      lifecycleMutation.variables?.action === action
    );
  }

  function handleAssigned(deviceId: string, vehicle: VehicleOption): void {
    setRecentAssignments((prev) => new Map(prev).set(deviceId, vehicle));
    // `assign`/`reassign` return a `DeviceAssignmentResponse`, not a `DeviceResponse` — the
    // resulting lifecycle state is hardcoded here, matching `entities.Device.mark_assigned`'s
    // deterministic Activated→Assigned edge exactly.
    setSelectedDevice((prev) => (prev && prev.id === deviceId ? { ...prev, lifecycleState: "assigned" } : prev));
  }

  const columns = useMemo<ColumnDef<Device, unknown>[]>(
    () => [
      {
        id: "terminalId",
        header: "Device",
        meta: { sortField: "terminal_id" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <LeadCell
            icon={<Cpu size={15} />}
            title={row.original.terminalId}
            subtitle={[row.original.vendor, row.original.model].filter(Boolean).join(" · ") || "No model info"}
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
        id: "lifecycleState",
        header: "Lifecycle",
        meta: { sortField: "lifecycle_state" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={lifecycleTone(row.original.lifecycleState)} dot>
            {lifecycleLabel(row.original.lifecycleState)}
          </Badge>
        ),
      },
      {
        id: "lastSeen",
        header: "Last seen",
        cell: ({ row }) => <span>{row.original.lastSeenAt ? formatDateTime(row.original.lastSeenAt) : "Never"}</span>,
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

  const activeLifecycleFilter = filters.lifecycle_state ?? "all";

  // Coarse, presentation-only role gating — see this component's own docstring for the exact
  // RBAC citation.
  const canManageLifecycle = principal?.role === "founder" || principal?.role === "support_staff";
  const canAssign = principal?.role === "founder" || principal?.role === "support_staff";

  const selectedAssignment = selectedDevice ? recentAssignments.get(selectedDevice.id) : undefined;

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <FilterChips
          options={LIFECYCLE_FILTERS}
          activeId={activeLifecycleFilter}
          onSelect={(id) => setFilter("lifecycle_state", id === "all" ? null : id)}
        />
        <div className={styles.toolbarActions}>
          <Input
            icon={<Search size={14} />}
            placeholder="Search devices…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search devices"
          />
          {canManageLifecycle && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Device
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Cpu size={22} />}
          title="Could not load devices"
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
            onRowClick={setSelectedDevice}
            emptyState={
              <EmptyState
                icon={<Cpu size={22} />}
                title="No devices yet"
                description="Devices you register will appear here."
                action={
                  canManageLifecycle ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Device
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
        open={selectedDevice !== null}
        onClose={() => setSelectedDevice(null)}
        icon={<Cpu size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedDevice?.terminalId}
        subtitle={[selectedDevice?.vendor, selectedDevice?.model].filter(Boolean).join(" · ") || undefined}
        status={
          selectedDevice && (
            <Badge variant={lifecycleTone(selectedDevice.lifecycleState)} dot>
              {lifecycleLabel(selectedDevice.lifecycleState)}
            </Badge>
          )
        }
        rows={
          selectedDevice
            ? [
                {
                  key: "Organization",
                  value: organizationNameById.get(selectedDevice.organizationId) ?? selectedDevice.organizationId,
                },
                { key: "Model", value: selectedDevice.model ?? "Not set" },
                { key: "Vendor", value: selectedDevice.vendor ?? "Not set" },
                ...(selectedDevice.lifecycleState === "assigned"
                  ? [
                      {
                        key: "Current assignment",
                        value: selectedAssignment
                          ? `${selectedAssignment.plateNo}${selectedAssignment.label ? ` — ${selectedAssignment.label}` : ""}`
                          : "Assigned (vehicle not shown — no read endpoint exists for an existing assignment)",
                      },
                    ]
                  : []),
                { key: "Cameras", value: selectedDevice.cameras.length },
                {
                  key: "Last seen",
                  value: selectedDevice.lastSeenAt ? formatDateTime(selectedDevice.lastSeenAt) : "Never",
                },
                { key: "Device ID", value: <MonoText>{selectedDevice.id}</MonoText> },
                { key: "Created", value: formatDate(selectedDevice.createdAt) },
                { key: "Updated", value: formatDate(selectedDevice.updatedAt) },
              ]
            : []
        }
        footer={
          selectedDevice &&
          (canManageLifecycle || canAssign) && (
            <div className={styles.drawerActions}>
              {selectedDevice.lifecycleState === "registered" && canManageLifecycle && (
                <Button
                  variant="secondary"
                  loading={isLifecyclePendingFor("activate")}
                  disabled={lifecycleMutation.isPending}
                  onClick={() => lifecycleMutation.mutate({ id: selectedDevice.id, action: "activate" })}
                >
                  Activate
                </Button>
              )}
              {selectedDevice.lifecycleState === "activated" && canManageLifecycle && (
                <Button
                  variant="secondary"
                  loading={isLifecyclePendingFor("suspend")}
                  disabled={lifecycleMutation.isPending}
                  onClick={() => lifecycleMutation.mutate({ id: selectedDevice.id, action: "suspend" })}
                >
                  Suspend
                </Button>
              )}
              {selectedDevice.lifecycleState === "activated" && canAssign && (
                <Button leadingIcon={<Link2 size={15} />} onClick={() => setAssignMode("assign")}>
                  Assign to vehicle
                </Button>
              )}
              {selectedDevice.lifecycleState === "suspended" && canManageLifecycle && (
                <Button
                  variant="secondary"
                  loading={isLifecyclePendingFor("reactivate")}
                  disabled={lifecycleMutation.isPending}
                  onClick={() => lifecycleMutation.mutate({ id: selectedDevice.id, action: "reactivate" })}
                >
                  Reactivate
                </Button>
              )}
              {selectedDevice.lifecycleState === "assigned" && canAssign && (
                <>
                  <Button leadingIcon={<Link2 size={15} />} onClick={() => setAssignMode("reassign")}>
                    Reassign
                  </Button>
                  <Button
                    variant="secondary"
                    loading={unassignMutation.isPending}
                    disabled={unassignMutation.isPending}
                    onClick={() => unassignMutation.mutate(selectedDevice.id)}
                  >
                    Unassign
                  </Button>
                </>
              )}
              {(selectedDevice.lifecycleState === "activated" || selectedDevice.lifecycleState === "assigned") &&
                canManageLifecycle && (
                  <Button
                    variant="danger"
                    loading={isLifecyclePendingFor("retire")}
                    disabled={lifecycleMutation.isPending}
                    onClick={() => lifecycleMutation.mutate({ id: selectedDevice.id, action: "retire" })}
                  >
                    Retire
                  </Button>
                )}
            </div>
          )
        }
      />

      <RegisterDeviceWizard open={createOpen} onClose={() => setCreateOpen(false)} />

      <AssignDeviceForm
        open={assignMode !== null}
        onClose={() => setAssignMode(null)}
        device={selectedDevice}
        mode={assignMode ?? "assign"}
        onAssigned={(vehicle) => {
          if (selectedDevice) {
            handleAssigned(selectedDevice.id, vehicle);
          }
        }}
      />
    </div>
  );
}
