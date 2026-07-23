import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, UserMinus, UserPlus, Users } from "lucide-react";
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
import { IconButton } from "../../../shared/components/IconButton/IconButton";
import { Input } from "../../../shared/components/Input/Input";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { CreateStudentForm } from "./CreateStudentForm";
import { LinkGuardianForm } from "./LinkGuardianForm";
import { AssignStudentForm } from "../student-assignments/AssignStudentForm";
import { StudentAssignmentSection } from "../student-assignments/StudentAssignmentSection";
import {
  getStudent,
  listGuardiansForStudent,
  listOrganizationsForPicker,
  listStudents,
  unlinkGuardianFromStudent,
  updateStudentStatus,
  type StudentStatus,
  type StudentSummary,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./StudentsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "disabled", label: "Disabled", tone: "neutral" },
  { id: "graduated", label: "Graduated", tone: "info" },
  { id: "transferred", label: "Transferred", tone: "warning" },
];

const ALL_STATUSES: StudentStatus[] = ["active", "disabled", "graduated", "transferred"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** The "Guardians" section of the student detail drawer (roadmap's own "first genuinely
 * relational UI") — lists linked parents via `GET /students/{id}/parents` and, for
 * `canManage` roles, an "Add guardian" action (opens `LinkGuardianForm`) plus a per-row unlink
 * action (`DELETE /students/{id}/parents/{parentId}`). Rendered through `DetailDrawer`'s own
 * `mapSlot` — a generic "extra content before stats/rows" slot, reused here rather than adding a
 * new prop to the shared component. */
function GuardiansSection({
  studentId,
  canManage,
  onAddGuardian,
}: {
  studentId: string;
  canManage: boolean;
  onAddGuardian: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const guardiansQuery = useQuery({
    queryKey: ["students", "guardians", studentId],
    queryFn: () => listGuardiansForStudent(studentId),
  });

  const unlinkMutation = useMutation({
    mutationFn: (parentId: string) => unlinkGuardianFromStudent(studentId, parentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["students", "guardians", studentId] });
      toast.success("Guardian unlinked", "The parent-student link has been removed.");
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not unlink the guardian.";
      toast.error("Unlink failed", message);
    },
  });

  return (
    <div className={styles.guardians}>
      <div className={styles.guardiansHeader}>
        <span className={styles.guardiansTitle}>Guardians</span>
        {canManage && (
          <Button size="sm" variant="secondary" leadingIcon={<UserPlus size={13} />} onClick={onAddGuardian}>
            Add guardian
          </Button>
        )}
      </div>

      {guardiansQuery.isLoading && <Skeleton height={36} />}
      {guardiansQuery.isError && <span className={styles.guardiansEmpty}>Could not load guardians.</span>}
      {guardiansQuery.data && guardiansQuery.data.length === 0 && (
        <span className={styles.guardiansEmpty}>No guardians linked yet.</span>
      )}
      {guardiansQuery.data?.map((guardian) => (
        <div key={guardian.parentId} className={styles.guardianRow}>
          <div>
            <div className={styles.guardianName}>
              {guardian.fullName}
              {guardian.isPrimary ? " · Primary" : ""}
            </div>
            <div className={styles.guardianMeta}>
              {guardian.relationship ?? "Guardian"}
              {guardian.phone ? ` · ${guardian.phone}` : ""}
            </div>
          </div>
          {canManage && (
            <IconButton
              icon={<UserMinus size={14} />}
              size="sm"
              aria-label={`Unlink ${guardian.fullName}`}
              disabled={unlinkMutation.isPending}
              onClick={() => unlinkMutation.mutate(guardian.parentId)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * `/platform/students` and `/org/students` (API Contracts §4.3's `/students` row: "Org Admin") —
 * one shared page component reused at both routes, mirroring `VehiclesPage`/`DevicesPage`'s
 * identical posture (`app/router.tsx`'s `PLATFORM_BUILT_ROUTES`/`ORGANIZATION_BUILT_ROUTES`).
 * Per the seeded RBAC matrix (`migrations/versions/
 * 20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`), only `founder`/`org_admin`
 * hold `transport_ops.students.create`/`.update`/`.update_status`/`.student_parents.create`/
 * `.student_parents.delete` — `regional_manager`/`support_staff` hold `.list`/`.read`/
 * `.student_parents.list` only (view, no enroll/status-change/link), and `finance_staff`/
 * `driver`/`parent` hold none of the `transport_ops.students.*`/`.student_parents.*` permissions
 * at all. `canManage` below is a presentation-layer hint only (`.claude/rules/frontend.md` #2);
 * the backend's own `require_permission` is the real gate.
 *
 * **The list table shows only Name + Status** — `GET /students` returns `StudentSummaryResponse`
 * (`id`/`full_name`/`status` only, see `./api.ts`'s `StudentSummary` docstring), not the full
 * `Student` shape `fleet_device`'s list routes return. Opening the detail drawer issues a second
 * `GET /students/{id}` for the organization/external-reference/timestamp fields, shown once that
 * request resolves (a `Skeleton` placeholder covers the gap, never a fabricated value).
 *
 * **`Student` carries no `route_id`/`stop_id`/`parent_id` field at all** — confirmed against
 * `transport_ops.domain.entities`'s own module docstring: the student↔route↔stop↔vehicle CR-1
 * gate lives in the separate `StudentAssignment` aggregate, and the parent link lives in the
 * separate `StudentParent` aggregate (this page's own "Guardians" section). Phase F6 adds the
 * former as a second `mapSlot` section, `StudentAssignmentSection` — imported from the sibling
 * `features/transport-ops/student-assignments/` folder rather than inlined here (unlike
 * `GuardiansSection` above), since the roadmap names it as its own deliverable and it's reused
 * nowhere else; this is a component import across two feature folders of the *same* bounded
 * context, not the cross-folder `api.ts` data-fetching duplication `.claude/rules/frontend.md`
 * #1 guards against — flagged here as a deliberate, narrow exception. There is still no dedicated
 * "Student Assignments" nav page — see `router.tsx`'s own Phase F6 note for why.
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap), so every viewer
 * who can reach this route currently sees every student, not just their own organization's.
 */
export function StudentsPage() {
  usePageHeader("Students", "Students enrolled across the platform");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedStudent, setSelectedStudent] = useState<StudentSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [linkGuardianOpen, setLinkGuardianOpen] = useState(false);
  const [assignRouteOpen, setAssignRouteOpen] = useState(false);
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
    queryKey: ["students", "list"],
    fetcher: listStudents,
    initialSort: { field: "full_name", direction: "asc" },
  });

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Full-detail fetch for the drawer — see this component's own docstring for why the list row
  // alone (`StudentSummary`) can't supply organization/external-reference/timestamp fields.
  const detailQuery = useQuery({
    queryKey: ["students", "detail", selectedStudent?.id],
    queryFn: () => getStudent(selectedStudent!.id),
    enabled: selectedStudent !== null,
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
    mutationFn: (input: { id: string; status: StudentStatus }) => updateStudentStatus(input.id, input.status),
    onSuccess: (student) => {
      queryClient.invalidateQueries({ queryKey: ["students", "list"] });
      queryClient.invalidateQueries({ queryKey: ["students", "detail", student.id] });
      setSelectedStudent({ id: student.id, fullName: student.fullName, status: student.status });
      toast.success("Student updated", `${student.fullName} is now ${statusLabel(student.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the student.";
      toast.error("Update failed", message);
    },
  });

  function isPendingFor(status: StudentStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedStudent?.id &&
      statusMutation.variables?.status === status
    );
  }

  const columns = useMemo<ColumnDef<StudentSummary, unknown>[]>(
    () => [
      {
        id: "fullName",
        header: "Student",
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
    ],
    [],
  );

  const activeStatusFilter = filters.status ?? "all";

  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — see this
  // component's own docstring for the exact RBAC citation. Reused for both the entity-status
  // actions and the guardian link/unlink actions: both permission sets are granted to the exact
  // same two roles in the seeded matrix.
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
            placeholder="Search students…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search students"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
              New Student
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<Users size={22} />}
          title="Could not load students"
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
            onRowClick={setSelectedStudent}
            emptyState={
              <EmptyState
                icon={<Users size={22} />}
                title="No students yet"
                description="Students you enroll will appear here."
                action={
                  canManage ? (
                    <Button variant="secondary" leadingIcon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
                      New Student
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
        open={selectedStudent !== null}
        onClose={() => setSelectedStudent(null)}
        icon={<Users size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedStudent?.fullName}
        status={
          selectedStudent && (
            <Badge variant={statusTone(selectedStudent.status)} dot>
              {statusLabel(selectedStudent.status)}
            </Badge>
          )
        }
        mapSlot={
          selectedStudent && (
            <>
              {detail ? (
                <StudentAssignmentSection
                  studentId={detail.id}
                  organizationId={detail.organizationId}
                  canManage={canManage}
                  onAssign={() => setAssignRouteOpen(true)}
                />
              ) : (
                <Skeleton height={72} />
              )}
              <GuardiansSection
                studentId={selectedStudent.id}
                canManage={canManage}
                onAddGuardian={() => setLinkGuardianOpen(true)}
              />
            </>
          )
        }
        rows={
          selectedStudent
            ? detailQuery.isLoading
              ? [{ key: "Details", value: <Skeleton height={16} /> }]
              : detailQuery.isError || !detail
                ? [{ key: "Details", value: "Could not load details." }]
                : [
                    {
                      key: "Organization",
                      value: organizationNameById.get(detail.organizationId) ?? detail.organizationId,
                    },
                    { key: "External reference", value: detail.externalRef ?? "Not set" },
                    { key: "Student ID", value: <MonoText>{detail.id}</MonoText> },
                    { key: "Created", value: formatDate(detail.createdAt) },
                    { key: "Updated", value: formatDate(detail.updatedAt) },
                  ]
            : []
        }
        footer={
          selectedStudent &&
          canManage && (
            <div className={styles.drawerActions}>
              {ALL_STATUSES.filter((status) => status !== selectedStudent.status).map((status) => (
                <Button
                  key={status}
                  variant={status === "disabled" ? "danger" : "secondary"}
                  loading={isPendingFor(status)}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedStudent.id, status })}
                >
                  {status === "active"
                    ? "Activate"
                    : status === "disabled"
                      ? "Disable"
                      : status === "graduated"
                        ? "Mark graduated"
                        : "Mark transferred"}
                </Button>
              ))}
            </div>
          )
        }
      />

      <CreateStudentForm open={createOpen} onClose={() => setCreateOpen(false)} />

      <LinkGuardianForm
        open={linkGuardianOpen}
        onClose={() => setLinkGuardianOpen(false)}
        studentId={selectedStudent?.id ?? null}
        studentName={selectedStudent?.fullName}
      />

      <AssignStudentForm
        open={assignRouteOpen}
        onClose={() => setAssignRouteOpen(false)}
        studentId={selectedStudent?.id ?? null}
        studentName={selectedStudent?.fullName}
        organizationId={detail?.organizationId ?? null}
      />
    </div>
  );
}
