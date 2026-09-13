import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Contact, Navigation, Pencil, Plus, Receipt, Search, UserMinus, UserPlus, Wallet } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { DataTable, type DataTableColumnMeta } from "../../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../../shared/components/Table/FilterChips";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { MonoText } from "../../../shared/components/Table/cells";
import { DetailDrawer, type DrawerStat } from "../../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { IconButton } from "../../../shared/components/IconButton/IconButton";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { BillingProfileForm } from "./BillingProfileForm";
import { CreateParentForm } from "./CreateParentForm";
import { EditParentForm } from "./EditParentForm";
import { FamilyTransportationForm } from "./FamilyTransportationForm";
import { SetInvoicePaymentStatusForm } from "./SetInvoicePaymentStatusForm";
import {
  formatParentAmount,
  getParent,
  getParentBillingProfile,
  getParentFinancialSummary,
  linkStudentToParent,
  listOrganizationsForPicker,
  listParentInvoices,
  listParents,
  listStudentsForParent,
  unlinkStudentFromParent,
  updateParentStatus,
  type LinkedStudent,
  type ParentFinancialSummary,
  type ParentInvoiceSummary,
  type ParentPaymentStatus,
  type ParentStatus,
  type ParentSummary,
} from "./api";
import { invoiceStatusLabel, invoiceStatusTone } from "./labels";
import { paymentStatusLabel, paymentStatusTone, statusLabel, statusTone } from "./labels";
// `students/labels.ts`'s own `statusLabel`/`statusTone` describe `StudentStatus` — aliased to
// avoid colliding with this file's own `ParentStatus`-shaped pair above. A tiny, already-tested
// labels module import, the same narrow "component/label import, not a duplicated data read"
// exception `LinkGuardianForm.tsx`'s own `ParentSearchSelect` import already establishes.
import { statusLabel as studentStatusLabel, statusTone as studentStatusTone } from "../students/labels";
import { CreateStudentForm } from "../students/CreateStudentForm";
import { EditStudentForm } from "../students/EditStudentForm";
import { getStudent, type Student, type StudentStatus } from "../students/api";
import { StudentAssignmentSection } from "../student-assignments/StudentAssignmentSection";
import styles from "./ParentsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const PAYMENT_FILTERS: { id: ParentPaymentStatus | "all"; label: string }[] = [
  { id: "all", label: "Any payment status" },
  { id: "unpaid", label: "Unpaid" },
  { id: "partially_paid", label: "Partially paid" },
  { id: "paid", label: "Paid" },
  { id: "no_invoices", label: "No fees due" },
];

const ALL_STATUSES: ParentStatus[] = ["active", "inactive"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateOfBirth(iso: string | null): string {
  if (!iso) return "DOB not set";
  return `DOB ${new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}`;
}

/** One child row — collapsed by default (name, DOB, status, relationship, Edit/Unlink), and
 * expandable into its own `StudentAssignmentSection`. **Read-only for vehicle/route** here
 * (`hideAssignAction`, 2026-09-12 business-model correction) — a family's transportation is set
 * once, for every child at once, from `LinkedStudentsSection`'s own header action
 * (`FamilyTransportationForm`), never per child; this section still shows each child's own
 * current assignment (identical across siblings by construction) and still allows ending one
 * child's own assignment individually (a real per-student lifecycle event, e.g. leaving the
 * school). Lazy: the assignment/route/vehicle queries only fire once a row is actually
 * expanded, not for every child the moment the drawer opens. */
function ChildRow({
  child,
  organizationId,
  canManage,
  expanded,
  onToggleExpanded,
  onEdit,
  onUnlink,
  unlinkPending,
}: {
  child: LinkedStudent;
  organizationId: string;
  canManage: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onEdit: () => void;
  onUnlink: () => void;
  unlinkPending: boolean;
}) {
  return (
    <div className={styles.childCard}>
      <button type="button" className={styles.childCardHeader} onClick={onToggleExpanded}>
        <div className={styles.childCardIdentity}>
          <div className={styles.linkedStudentName}>
            {child.fullName}
            {child.isPrimary ? " · Primary guardian" : ""}
          </div>
          <div className={styles.linkedStudentMeta}>
            {formatDateOfBirth(child.dateOfBirth)} · {child.relationship ?? "Guardian"}
          </div>
        </div>
        <Badge variant={studentStatusTone(child.status as StudentStatus)} dot>
          {studentStatusLabel(child.status as StudentStatus)}
        </Badge>
      </button>

      {canManage && (
        <div className={styles.childCardActions}>
          <Button variant="ghost" size="sm" leadingIcon={<Pencil size={12} />} onClick={onEdit}>
            Edit
          </Button>
          <IconButton
            icon={<UserMinus size={14} />}
            size="sm"
            aria-label={`Unlink ${child.fullName}`}
            disabled={unlinkPending}
            onClick={onUnlink}
          />
        </div>
      )}

      {expanded && (
        <StudentAssignmentSection
          studentId={child.studentId}
          organizationId={organizationId}
          canManage={canManage}
          onAssign={() => {}}
          hideAssignAction
        />
      )}
    </div>
  );
}

/** The "Children" section of the parent detail drawer — the mirror image of
 * `features/transport-ops/students/StudentsPage.tsx`'s `GuardiansSection`, extended (ADR-0041
 * §2, 2026-09-10) with an `[Add student]` header action: a parent registering a second/third
 * child later attaches to this *same* parent (`linkStudentToParent`), never creating a
 * duplicate. Each child row shows DOB/status/relationship and expands into its own read-only
 * `StudentAssignmentSection`. **Vehicle/route/stop assignment is a header-level "Family
 * transportation" action (2026-09-12 business-model correction), not a per-child one** —
 * `FamilyTransportationForm` applies the chosen route/stops/vehicle to every child here at
 * once, the structural fix for RAAD's "one Parent/family = one bus" rule. */
function LinkedStudentsSection({
  parentId,
  parentName,
  organizationId,
  canManage,
}: {
  parentId: string;
  parentName: string;
  organizationId: string;
  canManage: boolean;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [expandedChildId, setExpandedChildId] = useState<string | null>(null);
  const [addStudentOpen, setAddStudentOpen] = useState(false);
  const [editingChildId, setEditingChildId] = useState<string | null>(null);
  const [transportationOpen, setTransportationOpen] = useState(false);

  const linkedStudentsQuery = useQuery({
    queryKey: ["parents", "linked-students", parentId],
    queryFn: () => listStudentsForParent(parentId),
  });

  const editingStudentQuery = useQuery({
    queryKey: ["students", "detail", editingChildId],
    queryFn: () => getStudent(editingChildId!),
    enabled: editingChildId !== null,
  });

  const unlinkMutation = useMutation({
    mutationFn: (studentId: string) => unlinkStudentFromParent(parentId, studentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parents", "linked-students", parentId] });
      toast.success("Student unlinked", "The parent-student link has been removed.");
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not unlink the student.";
      toast.error("Unlink failed", message);
    },
  });

  const linkNewChildMutation = useMutation({
    mutationFn: (student: Student) => linkStudentToParent(student.id, parentId, { isPrimary: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parents", "linked-students", parentId] });
      toast.success("Student added", "The new student has been linked to this parent.");
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Student created, but linking to this parent failed.";
      toast.error("Link failed", message);
    },
  });

  const students = linkedStudentsQuery.data ?? [];

  return (
    <div className={styles.linkedStudents}>
      <div className={styles.linkedStudentsHeader}>
        <span className={styles.linkedStudentsTitle}>
          Children {students.length > 0 ? `(${students.length})` : ""}
        </span>
        {canManage && (
          <div className={styles.childCardActions}>
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={<Navigation size={13} />}
              onClick={() => setTransportationOpen(true)}
            >
              Family transportation
            </Button>
            <Button variant="secondary" size="sm" leadingIcon={<UserPlus size={13} />} onClick={() => setAddStudentOpen(true)}>
              Add student
            </Button>
          </div>
        )}
      </div>

      {linkedStudentsQuery.isLoading && <Skeleton height={36} />}
      {linkedStudentsQuery.isError && (
        <span className={styles.linkedStudentsEmpty}>Could not load linked students.</span>
      )}
      {linkedStudentsQuery.isSuccess && students.length === 0 && (
        <span className={styles.linkedStudentsEmpty}>No students linked yet.</span>
      )}
      {students.map((child) => (
        <ChildRow
          key={child.studentId}
          child={child}
          organizationId={organizationId}
          canManage={canManage}
          expanded={expandedChildId === child.studentId}
          onToggleExpanded={() =>
            setExpandedChildId((current) => (current === child.studentId ? null : child.studentId))
          }
          onEdit={() => setEditingChildId(child.studentId)}
          onUnlink={() => unlinkMutation.mutate(child.studentId)}
          unlinkPending={unlinkMutation.isPending}
        />
      ))}

      <FamilyTransportationForm
        open={transportationOpen}
        onClose={() => setTransportationOpen(false)}
        parentId={parentId}
        parentName={parentName}
        organizationId={organizationId}
      />
      <EditStudentForm
        open={editingChildId !== null}
        onClose={() => setEditingChildId(null)}
        student={editingStudentQuery.data ?? null}
      />
      <CreateStudentForm
        open={addStudentOpen}
        onClose={() => setAddStudentOpen(false)}
        onCreated={(student) => linkNewChildMutation.mutate(student)}
      />
    </div>
  );
}

/** "Billing" section (Part 16 of the directive) — the family's own `ParentBillingProfile`:
 * monthly fee, billing start, due day, status. `onEdit` opens `BillingProfileForm`, the same
 * create-or-update surface `CreateParentForm`'s own Billing step uses at registration time. */
function BillingProfileSection({
  parentId,
  canManage,
  onEdit,
}: {
  parentId: string;
  canManage: boolean;
  onEdit: () => void;
}) {
  const profileQuery = useQuery({
    queryKey: ["parents", "billing-profile", parentId],
    queryFn: () => getParentBillingProfile(parentId),
  });

  const profile = profileQuery.data ?? null;

  return (
    <div className={styles.linkedStudents}>
      <div>
        <span className={styles.linkedStudentsTitle}>Billing</span>
      </div>
      {profileQuery.isLoading && <Skeleton height={36} />}
      {profileQuery.isSuccess && !profile && (
        <span className={styles.linkedStudentsEmpty}>
          No monthly fee configured yet.{" "}
          {canManage && (
            <Button variant="ghost" onClick={onEdit}>
              Set up billing
            </Button>
          )}
        </span>
      )}
      {profile && (
        <div className={styles.linkedStudentRow}>
          <div>
            <div className={styles.linkedStudentName}>
              {formatParentAmount(profile.monthlyFee, profile.currency)} / month
            </div>
            <div className={styles.linkedStudentMeta}>
              Billing start {profile.billingStartPeriod} · Due day {profile.dueDay} ·{" "}
              {profile.status === "active" ? "Active" : "Inactive"}
            </div>
          </div>
          {canManage && (
            <Button variant="ghost" leadingIcon={<Receipt size={13} />} onClick={onEdit}>
              Edit
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** "Current invoice" section (Part 16 of the directive) — this family's most recent Parent
 * Invoice, with the "[Update Payment Status]" action right beside it, exactly where the
 * directive's own mockup places it (not a generic drawer-footer button, since the action applies
 * to one specific invoice). */
function CurrentInvoiceSection({
  parentId,
  canManage,
  onUpdateStatus,
}: {
  parentId: string;
  canManage: boolean;
  onUpdateStatus: (invoice: ParentInvoiceSummary) => void;
}) {
  const invoiceQuery = useQuery({
    queryKey: ["parents", "current-invoice", parentId],
    queryFn: async () => {
      const page = await listParentInvoices({ page: 1, pageSize: 1, parentId });
      return page.data[0] ?? null;
    },
  });

  const invoice = invoiceQuery.data ?? null;

  return (
    <div className={styles.linkedStudents}>
      <div>
        <span className={styles.linkedStudentsTitle}>Current invoice</span>
      </div>
      {invoiceQuery.isLoading && <Skeleton height={36} />}
      {invoiceQuery.isSuccess && !invoice && (
        <span className={styles.linkedStudentsEmpty}>No Parent Invoice generated yet.</span>
      )}
      {invoice && (
        <div className={styles.linkedStudentRow}>
          <div>
            <div className={styles.linkedStudentName}>
              {invoice.period} — {formatParentAmount(invoice.amount, invoice.currency)}
            </div>
            <div className={styles.linkedStudentMeta}>
              Paid {formatParentAmount(invoice.amountPaid, invoice.currency)} · Receivable{" "}
              {formatParentAmount(invoice.balanceDue, invoice.currency)}
            </div>
          </div>
          <Badge variant={invoiceStatusTone(invoice.status)} dot>
            {invoiceStatusLabel(invoice.status)}
          </Badge>
          {canManage && invoice.status !== "cancelled" && (
            <Button variant="ghost" leadingIcon={<Wallet size={13} />} onClick={() => onUpdateStatus(invoice)}>
              Update Payment Status
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * `/org/parents` only (`app/router.tsx`'s `ORGANIZATION_BUILT_ROUTES`) — RAAD Platform staff no
 * longer reach this page at all: migration `c4d9a2e6f813` revoked founder/regional_manager/
 * support_staff's `transport_ops.parents.*` grants entirely, per CLAUDE.md's own Business Model
 * ("RAAD does not manage students or parents directly"). Only `org_admin` holds any
 * `transport_ops.parents.*`/`.student_parents.*` permission now (full CRUD, seeded matrix
 * `5437a5d1651b`). `canManage` below is a presentation-layer hint only
 * (`.claude/rules/frontend.md` #2).
 *
 * **The list table shows only Name + Status** — `GET /parents` returns `ParentSummaryResponse`
 * (`id`/`full_name`/`status` only), not the full `Parent` shape. Opening the detail drawer issues
 * a second `GET /parents/{id}` for the richer fields.
 *
 * **Financial columns (2026-09-10, Parent & Student Domain Restructure) are fetched per visible
 * row, not embedded in `ParentSummaryResponse`.** `GET /parents` deliberately stays thin (see
 * above); `useQueries` fires one `GET /school-finance/parents/{id}/summary` per row on the
 * *current page only* (bounded by the page size, never the whole table) — the same "N independent
 * instances of a single-item primitive" shape ADR-0031's own Fleet Overview and
 * `MultiCameraVideoPanel` already establish as an acceptable bounded burst in this codebase. The
 * "Payment status" filter below is consequently **page-local**, not a server-side query — labeled
 * as such rather than presented as more than it is.
 *
 * **Tenant-scoped server-side** (ADR-0021's `_apply_scope`, verified against the running
 * repository code) — an Org Admin only ever sees their own organization's parents and financial
 * data here, never another school's.
 */
export function ParentsPage() {
  usePageHeader("Parents", "Parents and guardians linked to students in your organization");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedParent, setSelectedParent] = useState<ParentSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [billingOpen, setBillingOpen] = useState(false);
  const [invoiceForPaymentStatus, setInvoiceForPaymentStatus] = useState<ParentInvoiceSummary | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [paymentFilter, setPaymentFilter] = useState<ParentPaymentStatus | "all">("all");

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
    queryKey: ["parents", "list"],
    fetcher: listParents,
    initialSort: { field: "full_name", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const detailQuery = useQuery({
    queryKey: ["parents", "detail", selectedParent?.id],
    queryFn: () => getParent(selectedParent!.id),
    enabled: selectedParent !== null,
  });

  const financialSummaryQuery = useQuery({
    queryKey: ["parents", "financial-summary", selectedParent?.id],
    queryFn: () => getParentFinancialSummary(selectedParent!.id),
    enabled: selectedParent !== null,
  });

  const billingProfileQuery = useQuery({
    queryKey: ["parents", "billing-profile", selectedParent?.id],
    queryFn: () => getParentBillingProfile(selectedParent!.id),
    enabled: selectedParent !== null,
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

  // Bounded to the current page's rows only — see this component's own docstring.
  const financialQueries = useQueries({
    queries: rows.map((row) => ({
      queryKey: ["parents", "financial-summary", row.id],
      queryFn: () => getParentFinancialSummary(row.id),
      staleTime: 15_000,
    })),
  });

  const financialByParentId = useMemo(() => {
    const map = new Map<string, ParentFinancialSummary>();
    rows.forEach((row, index) => {
      const data = financialQueries[index]?.data;
      if (data) {
        map.set(row.id, data);
      }
    });
    return map;
  }, [rows, financialQueries]);

  const visibleRows = useMemo(() => {
    if (paymentFilter === "all") {
      return rows;
    }
    return rows.filter((row) => financialByParentId.get(row.id)?.status === paymentFilter);
  }, [rows, paymentFilter, financialByParentId]);

  const statusMutation = useMutation({
    mutationFn: (input: { id: string; status: ParentStatus }) => updateParentStatus(input.id, input.status),
    onSuccess: (parent) => {
      queryClient.invalidateQueries({ queryKey: ["parents", "list"] });
      queryClient.invalidateQueries({ queryKey: ["parents", "detail", parent.id] });
      setSelectedParent({ id: parent.id, fullName: parent.fullName, status: parent.status });
      toast.success("Parent updated", `${parent.fullName} is now ${statusLabel(parent.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message = mutationError instanceof ApiError ? mutationError.message : "Could not update the parent.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: ParentStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedParent?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<ParentSummary, unknown>[]>(
    () => [
      {
        id: "fullName",
        header: "Parent",
        meta: { sortField: "full_name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span>{row.original.fullName}</span>,
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
        id: "children",
        header: "Children",
        cell: ({ row }) => {
          const summary = financialByParentId.get(row.original.id);
          return summary ? <span>{summary.children.length}</span> : <Skeleton width={20} height={14} />;
        },
      },
      {
        id: "outstanding",
        header: "Outstanding",
        cell: ({ row }) => {
          const summary = financialByParentId.get(row.original.id);
          return summary ? (
            <span>{formatParentAmount(summary.outstanding, summary.currency)}</span>
          ) : (
            <Skeleton width={60} height={14} />
          );
        },
      },
      {
        id: "paymentStatus",
        header: "Payment status",
        cell: ({ row }) => {
          const summary = financialByParentId.get(row.original.id);
          return summary ? (
            <Badge variant={paymentStatusTone(summary.status)} dot>
              {paymentStatusLabel(summary.status)}
            </Badge>
          ) : (
            <Skeleton width={70} height={14} />
          );
        },
      },
    ],
    [financialByParentId],
  );

  const activeStatusFilter = filters.status ?? "all";

  // Coarse, presentation-only role gating — see this component's own docstring for the exact
  // RBAC citation.
  const canManage = principal?.role === "founder" || principal?.role === "org_admin";

  const detail = detailQuery.data;
  const financialSummary = financialSummaryQuery.data ?? null;

  const drawerStats: DrawerStat[] | undefined = financialSummary
    ? [
        { key: "Total due", value: formatParentAmount(financialSummary.totalDue, financialSummary.currency) },
        { key: "Total paid", value: formatParentAmount(financialSummary.totalPaid, financialSummary.currency) },
        {
          key: "Outstanding",
          value: formatParentAmount(financialSummary.outstanding, financialSummary.currency),
          color: financialSummary.outstanding !== "0.00" ? "var(--color-danger)" : undefined,
        },
        { key: "Payment status", value: paymentStatusLabel(financialSummary.status) },
      ]
    : undefined;

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
            placeholder="Search by name or phone…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search parents"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Parent
            </Button>
          )}
        </div>
      </div>

      <div className={styles.toolbar}>
        <label className={styles.paymentFilterLabel}>
          Payment status (this page)
          <select
            className={styles.paymentFilterSelect}
            value={paymentFilter}
            onChange={(event) => setPaymentFilter(event.target.value as ParentPaymentStatus | "all")}
          >
            {PAYMENT_FILTERS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isError ? (
        <EmptyState
          icon={<Contact size={22} />}
          title="Could not load parents"
          description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            data={visibleRows}
            getRowId={(row) => row.id}
            isLoading={isLoading}
            sort={sort}
            onSortChange={toggleSort}
            onRowClick={setSelectedParent}
            emptyState={
              <EmptyState
                icon={<Contact size={22} />}
                title="No parents yet"
                description="Parents you register will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Parent
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
        open={selectedParent !== null}
        onClose={() => setSelectedParent(null)}
        icon={<Contact size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedParent?.fullName}
        status={
          selectedParent && (
            <Badge variant={statusTone(selectedParent.status)} dot>
              {statusLabel(selectedParent.status)}
            </Badge>
          )
        }
        stats={drawerStats}
        mapSlot={
          selectedParent && (
            <>
              {detail ? (
                <LinkedStudentsSection
                  parentId={selectedParent.id}
                  parentName={selectedParent.fullName}
                  organizationId={detail.organizationId}
                  canManage={canManage}
                />
              ) : (
                <Skeleton height={72} />
              )}
              <BillingProfileSection
                parentId={selectedParent.id}
                canManage={canManage}
                onEdit={() => setBillingOpen(true)}
              />
              <CurrentInvoiceSection
                parentId={selectedParent.id}
                canManage={canManage}
                onUpdateStatus={setInvoiceForPaymentStatus}
              />
            </>
          )
        }
        rows={
          selectedParent
            ? detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !detail
                ? [{ key: "Details", value: "Could not load details." }]
                : [
                    {
                      key: "Organization",
                      value: organizationNameById.get(detail.organizationId) ?? detail.organizationId,
                    },
                    { key: "Phone", value: detail.phone ?? "Not set" },
                    { key: "Alternative phone", value: detail.alternatePhone ?? "Not set" },
                    { key: "Address", value: detail.address ?? "Not set" },
                    { key: "Emergency contact", value: detail.emergencyContactName ?? "Not set" },
                    { key: "Emergency contact phone", value: detail.emergencyContactPhone ?? "Not set" },
                    { key: "Notes", value: detail.notes ?? "Not set" },
                    { key: "Linked user ID", value: <MonoText>{detail.userId}</MonoText> },
                    { key: "Parent ID", value: <MonoText>{detail.id}</MonoText> },
                    { key: "Created", value: formatDate(detail.createdAt) },
                    { key: "Updated", value: formatDate(detail.updatedAt) },
                  ]
            : []
        }
        footer={
          selectedParent &&
          canManage && (
            <div className={styles.drawerActions}>
              <Button variant="secondary" leadingIcon={<Pencil size={13} />} onClick={() => setEditOpen(true)}>
                Edit
              </Button>
              {ALL_STATUSES.filter((status) => status !== selectedParent.status).map((status) => (
                <Button
                  key={status}
                  variant={status === "inactive" ? "danger" : "secondary"}
                  loading={isPendingFor(status)}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedParent.id, status })}
                >
                  {status === "active" ? "Activate" : "Deactivate"}
                </Button>
              ))}
            </div>
          )
        }
      />

      <CreateParentForm
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onOpenExisting={(parent) => setSelectedParent(parent)}
      />
      <EditParentForm open={editOpen} onClose={() => setEditOpen(false)} parent={detail ?? null} />
      <BillingProfileForm
        open={billingOpen}
        onClose={() => setBillingOpen(false)}
        parentId={selectedParent?.id ?? null}
        parentName={selectedParent?.fullName}
        existing={billingProfileQuery.data ?? null}
      />
      <SetInvoicePaymentStatusForm
        open={invoiceForPaymentStatus !== null}
        onClose={() => setInvoiceForPaymentStatus(null)}
        invoice={invoiceForPaymentStatus}
      />
    </div>
  );
}
