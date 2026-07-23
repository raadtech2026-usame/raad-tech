import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Contact, Plus, Search, UserMinus } from "lucide-react";
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
import { CreateParentForm } from "./CreateParentForm";
import {
  getParent,
  listOrganizationsForPicker,
  listParents,
  listStudentsForParent,
  unlinkStudentFromParent,
  updateParentStatus,
  type ParentStatus,
  type ParentSummary,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./ParentsPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "inactive", label: "Inactive", tone: "neutral" },
];

const ALL_STATUSES: ParentStatus[] = ["active", "inactive"];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** The "Linked students" section of the parent detail drawer — the mirror image of
 * `features/transport-ops/students/StudentsPage.tsx`'s `GuardiansSection`. Lists a parent's
 * linked students via `GET /parents/{id}/students` and, for `canManage` roles, a per-row unlink
 * action. **Read-only otherwise** — there is deliberately no "add student" action here; link
 * *creation* is initiated from the Student side only (`LinkGuardianForm.tsx`), so this section
 * satisfies the roadmap's "bidirectionally visible" requirement without building two divergent
 * forms for the identical `POST /students/{student_id}/parents` operation. */
function LinkedStudentsSection({ parentId, canManage }: { parentId: string; canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const linkedStudentsQuery = useQuery({
    queryKey: ["parents", "linked-students", parentId],
    queryFn: () => listStudentsForParent(parentId),
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

  return (
    <div className={styles.linkedStudents}>
      <div>
        <span className={styles.linkedStudentsTitle}>Linked students</span>
      </div>

      {linkedStudentsQuery.isLoading && <Skeleton height={36} />}
      {linkedStudentsQuery.isError && (
        <span className={styles.linkedStudentsEmpty}>Could not load linked students.</span>
      )}
      {linkedStudentsQuery.data && linkedStudentsQuery.data.length === 0 && (
        <span className={styles.linkedStudentsEmpty}>No students linked yet.</span>
      )}
      {linkedStudentsQuery.data?.map((student) => (
        <div key={student.studentId} className={styles.linkedStudentRow}>
          <div>
            <div className={styles.linkedStudentName}>
              {student.fullName}
              {student.isPrimary ? " · Primary guardian" : ""}
            </div>
            <div className={styles.linkedStudentMeta}>{student.relationship ?? "Guardian"}</div>
          </div>
          {canManage && (
            <IconButton
              icon={<UserMinus size={14} />}
              size="sm"
              aria-label={`Unlink ${student.fullName}`}
              disabled={unlinkMutation.isPending}
              onClick={() => unlinkMutation.mutate(student.studentId)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * `/platform/parents` and `/org/parents` (API Contracts §4.3's `/parents` row: "Org Admin") — one
 * shared page component reused at both routes, mirroring `StudentsPage`'s identical posture.
 * Per the seeded RBAC matrix, only `founder`/`org_admin` hold `transport_ops.parents.create`/
 * `.update`/`.student_parents.create`/`.student_parents.delete` — `regional_manager`/
 * `support_staff` hold `.list`/`.read`/`.student_parents.list` only, and `finance_staff`/
 * `driver`/`parent` hold none at all. `canManage` below is a presentation-layer hint only
 * (`.claude/rules/frontend.md` #2).
 *
 * **The list table shows only Name + Status** — `GET /parents` returns `ParentSummaryResponse`
 * (`id`/`full_name`/`status` only), not the full `Parent` shape. Opening the detail drawer issues
 * a second `GET /parents/{id}` for organization/user/phone/timestamp fields — see
 * `StudentsPage.tsx`'s identical docstring note for the full reasoning (this is a `transport_ops`
 * -wide list-route shape, not specific to either aggregate).
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap).
 */
export function ParentsPage() {
  usePageHeader("Parents", "Parents and guardians linked to students across the platform");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedParent, setSelectedParent] = useState<ParentSummary | null>(null);
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
    ],
    [],
  );

  const activeStatusFilter = filters.status ?? "all";

  // Coarse, presentation-only role gating — see this component's own docstring for the exact
  // RBAC citation.
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
            placeholder="Search parents…"
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
            data={rows}
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
        mapSlot={selectedParent && <LinkedStudentsSection parentId={selectedParent.id} canManage={canManage} />}
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

      <CreateParentForm open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
