import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, UsersRound } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { DataTable, type DataTableColumnMeta } from "../../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../../shared/components/Table/FilterChips";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { DetailDrawer } from "../../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { Tabs } from "../../../shared/components/Tabs/Tabs";
import { AssignToBusForm } from "./AssignToBusForm";
import { CompliancePanel, ComplianceSummary } from "./CompliancePanel";
import { ExpiringDocumentsPanel } from "./ExpiringDocumentsPanel";
import { GrantDriverAccessForm } from "./GrantDriverAccessForm";
import { RecordDocumentForm } from "./RecordDocumentForm";
import { StaffForm } from "./StaffForm";
import { StaffBusesSection, StaffDocumentsSection } from "./StaffSections";
import { StaffSetupPanel } from "./StaffSetupPanel";
import { StaffUnavailabilitySection } from "../operations/StaffUnavailabilitySection";
import { changeStaffStatus, getStaff, listStaff, type StaffDocument, type StaffStatus, type StaffSummary } from "./api";
import { complianceLabel, complianceTone, formatDay, staffStatusLabel, staffStatusTone } from "./labels";
import styles from "./Staff.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
  { id: "left", label: "Left", tone: "danger" },
];

const SEARCH_DEBOUNCE_MS = 300;

const STATUS_ACTIONS: Record<StaffStatus, { label: string; variant: "secondary" | "danger" }> = {
  active: { label: "Mark active", variant: "secondary" },
  inactive: { label: "Mark inactive", variant: "secondary" },
  left: { label: "Mark as left", variant: "danger" },
};

/**
 * `/org/staff` and `/platform/staff` — everyone who works on the organization's buses
 * (ADR-0049): drivers, attendants, conductors and whatever else the school calls them.
 *
 * Only the Org Admin edits (`transport_ops.staff.*.manage` is theirs alone). Founder, Regional
 * Manager and Support Staff read, without emergency contacts or document numbers — the server
 * leaves those out and says so. `canManage` is presentation only (`.claude/rules/frontend.md`
 * #2).
 *
 * `?staff=<id>` opens that profile, so the Drivers page and the documents list can link here.
 */
export function TransportStaffPage() {
  usePageHeader("Transport Staff", "Drivers, attendants and everyone else on your buses");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const canManage = principal?.role === "org_admin";

  const [tab, setTab] = useState("staff");
  const [searchInput, setSearchInput] = useState("");
  const [formOpen, setFormOpen] = useState<"new" | "edit" | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [documentForm, setDocumentForm] = useState<{ renewing: StaffDocument | null } | null>(null);
  const [driverAccessOpen, setDriverAccessOpen] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<StaffStatus | null>(null);

  const selectedId = searchParams.get("staff");
  function openStaff(id: string | null) {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("staff", id);
    else next.delete("staff");
    setSearchParams(next, { replace: true });
  }

  const { rows, total, page, pageSize, sort, filters, isLoading, isError, error, setPage, toggleSort, setFilter, setSearch } =
    usePaginatedQuery({
      queryKey: ["transport-staff", "list"],
      fetcher: listStaff,
      initialSort: { field: "full_name", direction: "asc" },
    });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const detailQuery = useQuery({
    queryKey: ["transport-staff", "detail", selectedId],
    queryFn: () => getStaff(selectedId!),
    enabled: selectedId !== null,
  });
  const staff = detailQuery.data;

  const statusMutation = useMutation({
    mutationFn: (status: StaffStatus) => changeStaffStatus(selectedId!, status),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff"] });
      queryClient.invalidateQueries({ queryKey: ["drivers"] });
      setPendingStatus(null);
      toast.success("Status updated", `${updated.fullName} is now ${staffStatusLabel(updated.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      toast.error("Could not update the status", mutationError instanceof ApiError ? mutationError.message : "Please try again.");
    },
  });

  const columns = useMemo<ColumnDef<StaffSummary, unknown>[]>(
    () => [
      {
        id: "fullName",
        header: "Name",
        meta: { sortField: "full_name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className={styles.nameCell}>
            <span>{row.original.fullName}</span>
            {row.original.employeeRef && <span className={styles.nameMeta}>{row.original.employeeRef}</span>}
          </div>
        ),
      },
      {
        id: "role",
        header: "Job title",
        cell: ({ row }) => (
          <span>
            {row.original.roleName ?? "—"}
            {row.original.isDriver && (
              <>
                {" "}
                <Badge variant="info">Driver access</Badge>
              </>
            )}
          </span>
        ),
      },
      {
        id: "compliance",
        header: "Documents",
        cell: ({ row }) =>
          row.original.complianceStatus && row.original.complianceStatus !== "compliant" ? (
            <Badge variant={complianceTone(row.original.complianceStatus)}>
              {complianceLabel(row.original.complianceStatus)}
            </Badge>
          ) : (
            "—"
          ),
      },
      { id: "phone", header: "Phone", cell: ({ row }) => row.original.phone ?? "—" },
      {
        id: "status",
        header: "Status",
        meta: { sortField: "status" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <Badge variant={staffStatusTone(row.original.status)} dot>
            {staffStatusLabel(row.original.status)}
          </Badge>
        ),
      },
    ],
    [],
  );

  const tabs = [
    { id: "staff", label: "Staff" },
    { id: "documents", label: "Documents due" },
    ...(canManage ? [{ id: "setup", label: "Setup" }] : []),
  ];

  // A "Driver" title without driver access (or the reverse) is allowed — the title is only a
  // label — but it is worth pointing out (ADR-0049 §2).
  const titleMismatch =
    staff && staff.roleName?.trim().toLowerCase() === "driver" && !staff.driver
      ? "Titled Driver, but has no driver access yet."
      : staff && staff.driver && staff.roleName && staff.roleName.trim().toLowerCase() !== "driver"
        ? `Has driver access, but is titled ${staff.roleName}.`
        : null;

  function privateValue(value: string | null): string {
    if (!staff?.privateFieldsVisible) return "Visible to Org Admins only";
    return value ?? "—";
  }

  return (
    <div className={styles.page}>
      <Tabs options={tabs} activeId={tab} onSelect={setTab} />

      {tab === "documents" && (
        <>
          <CompliancePanel onOpenStaff={openStaff} />
          <ExpiringDocumentsPanel onOpenStaff={openStaff} />
        </>
      )}
      {tab === "setup" && canManage && <StaffSetupPanel canManage={canManage} />}

      {tab === "staff" && (
        <>
          <div className={styles.toolbar}>
            <FilterChips
              options={STATUS_FILTERS}
              activeId={filters.status ?? "all"}
              onSelect={(id) => setFilter("status", id === "all" ? null : id)}
            />
            <div className={styles.toolbarActions}>
              <Input
                icon={<Search size={14} />}
                placeholder="Search by name, reference or phone…"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                aria-label="Search staff"
              />
              {canManage && (
                <Button leadingIcon={<Plus size={15} />} onClick={() => setFormOpen("new")}>
                  New staff member
                </Button>
              )}
            </div>
          </div>
          {isError ? (
            <EmptyState
              icon={<UsersRound size={22} />}
              title="Could not load staff"
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
                onRowClick={(row) => openStaff(row.id)}
                emptyState={
                  <EmptyState
                    icon={<UsersRound size={22} />}
                    title="No staff yet"
                    description="Add the drivers, attendants and others who work on your buses."
                    action={
                      canManage ? (
                        <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setFormOpen("new")}>
                          New staff member
                        </Button>
                      ) : undefined
                    }
                  />
                }
              />
              <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
            </>
          )}
        </>
      )}

      <DetailDrawer
        open={selectedId !== null}
        onClose={() => openStaff(null)}
        icon={<UsersRound size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={staff?.fullName ?? (detailQuery.isLoading ? "Loading…" : "Staff member")}
        subtitle={staff?.roleName ?? undefined}
        status={
          staff && (
            <Badge variant={staffStatusTone(staff.status)} dot>
              {staffStatusLabel(staff.status)}
            </Badge>
          )
        }
        mapSlot={
          staff && (
            <>
              {titleMismatch && <p className={styles.warning}>{titleMismatch}</p>}
              <ComplianceSummary compliance={staff.compliance} />
              <StaffBusesSection
                staffId={staff.id}
                organizationId={staff.organizationId}
                canManage={canManage && staff.status === "active"}
                onAssign={() => setAssignOpen(true)}
              />
              <StaffUnavailabilitySection
                staffId={staff.id}
                staffName={staff.fullName}
                canManage={canManage && staff.status !== "left"}
              />
              <StaffDocumentsSection
                staffId={staff.id}
                canManage={canManage}
                onAdd={() => setDocumentForm({ renewing: null })}
                onRenew={(document) => setDocumentForm({ renewing: document })}
              />
            </>
          )
        }
        rows={
          selectedId === null
            ? []
            : detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !staff
                ? [{ key: "Details", value: "Could not load this staff member." }]
                : [
                    { key: "Phone", value: staff.phone ?? "—" },
                    { key: "Alternate phone", value: staff.alternatePhone ?? "—" },
                    { key: "Employee reference", value: staff.employeeRef ?? "—" },
                    { key: "Start date", value: formatDay(staff.startDate) },
                    ...(staff.leftOn ? [{ key: "Left on", value: formatDay(staff.leftOn) }] : []),
                    {
                      key: "Driver access",
                      value: staff.driver
                        ? `Licence ${staff.driver.licenseNo} · ${staff.driver.status === "active" ? "active" : "inactive"}`
                        : "None",
                    },
                    { key: "Emergency contact", value: privateValue(staff.emergencyContactName) },
                    { key: "Emergency phone", value: privateValue(staff.emergencyContactPhone) },
                    { key: "Notes", value: staff.notes ?? "—" },
                  ]
        }
        footer={
          staff &&
          canManage && (
            <div className={styles.drawerActions}>
              <Button variant="secondary" onClick={() => setFormOpen("edit")}>
                Edit
              </Button>
              {!staff.driver && staff.status === "active" && (
                <Button variant="secondary" onClick={() => setDriverAccessOpen(true)}>
                  Give driver access
                </Button>
              )}
              {(Object.keys(STATUS_ACTIONS) as StaffStatus[])
                .filter((status) => status !== staff.status)
                .map((status) => (
                  <Button key={status} variant={STATUS_ACTIONS[status].variant} onClick={() => setPendingStatus(status)}>
                    {STATUS_ACTIONS[status].label}
                  </Button>
                ))}
            </div>
          )
        }
      />

      <ConfirmDialog
        open={pendingStatus !== null}
        title={pendingStatus === "left" ? `Mark ${staff?.fullName ?? "this person"} as left?` : "Change status?"}
        description={
          pendingStatus === "left"
            ? "Their bus assignments end today and their driver login is disabled. Their history is kept."
            : `They will be marked ${pendingStatus ? staffStatusLabel(pendingStatus).toLowerCase() : ""}.`
        }
        confirmLabel={pendingStatus ? STATUS_ACTIONS[pendingStatus].label : "Confirm"}
        tone={pendingStatus === "left" ? "danger" : "primary"}
        loading={statusMutation.isPending}
        onConfirm={() => pendingStatus && statusMutation.mutate(pendingStatus)}
        onCancel={() => setPendingStatus(null)}
      />

      <StaffForm
        open={formOpen !== null}
        onClose={() => setFormOpen(null)}
        staff={formOpen === "edit" ? staff : null}
        onSaved={(saved) => openStaff(saved.id)}
      />
      {staff && (
        <>
          <AssignToBusForm
            open={assignOpen}
            onClose={() => setAssignOpen(false)}
            staffId={staff.id}
            staffName={staff.fullName}
            organizationId={staff.organizationId}
          />
          <RecordDocumentForm
            open={documentForm !== null}
            onClose={() => setDocumentForm(null)}
            staffId={staff.id}
            staffName={staff.fullName}
            renewing={documentForm?.renewing ?? null}
          />
          <GrantDriverAccessForm open={driverAccessOpen} onClose={() => setDriverAccessOpen(false)} staff={staff} />
        </>
      )}
    </div>
  );
}
