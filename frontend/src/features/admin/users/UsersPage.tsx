import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, UsersRound } from "lucide-react";
import { usePageHeader } from "../../../app/layout/PageHeaderContext";
import { usePaginatedQuery } from "../../../shared/hooks/usePaginatedQuery";
import { useAuthStore } from "../../../shared/stores/authStore";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { getRoleDisplay } from "../../../shared/auth/roleDisplay";
import { DataTable, type DataTableColumnMeta } from "../../../shared/components/Table/DataTable";
import { FilterChips, type FilterChipOption } from "../../../shared/components/Table/FilterChips";
import { Pagination } from "../../../shared/components/Table/Pagination";
import { MonoText } from "../../../shared/components/Table/cells";
import { DetailDrawer } from "../../../shared/components/Drawer/DetailDrawer";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Input } from "../../../shared/components/Input/Input";
import { Avatar } from "../../../shared/components/Avatar/Avatar";
import { InviteUserForm } from "./InviteUserForm";
import { ResetUserPasswordForm } from "./ResetUserPasswordForm";
import {
  listOrganizationsForPicker,
  listUsers,
  updateUserMfa,
  updateUserStatus,
  type User,
  type UserStatus,
} from "./api";
import { avatarInitials, roleTone, statusLabel, statusTone } from "./labels";
import styles from "./UsersPage.module.css";

const STATUS_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All statuses", tone: "neutral" },
  { id: "active", label: "Active", tone: "success" },
  { id: "invited", label: "Invited", tone: "warning" },
  { id: "disabled", label: "Disabled", tone: "danger" },
];

/** Every `Role` value, matching `api.ts`'s `ASSIGNABLE_ROLES` — the same whitelist the create
 * form's role picker offers, reused here so the filter row never lists a role the backend
 * couldn't have assigned in the first place. */
const ROLE_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All roles", tone: "neutral" },
  { id: "founder", label: "Founder", tone: "purple" },
  { id: "regional_manager", label: "Regional Manager", tone: "info" },
  { id: "support_staff", label: "Support Staff", tone: "info" },
  { id: "finance_staff", label: "Finance Staff", tone: "info" },
  { id: "org_admin", label: "Org Admin", tone: "success" },
  { id: "driver", label: "Driver", tone: "warning" },
  { id: "parent", label: "Parent", tone: "neutral" },
];

const SEARCH_DEBOUNCE_MS = 300;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
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

/**
 * `/platform/users` (API Contracts §4.1: `GET/POST /users` "in-scope admin... role-restricted
 * creation") — the nav entry named "Users & Roles" (`app/layout/navConfig.ts`'s `platformNav`).
 * Founder/Regional Manager/Support Staff land here per `RouteGuard`'s `PLATFORM_ROLES`
 * (`app/router.tsx`); Finance Staff can reach the *route* (same guard) but has no nav link to it
 * (`navConfig.ts`'s `FINANCE_ALLOWED_PATHS` excludes `/platform/users`) and, per the deployed
 * RBAC matrix, holds none of `iam.users.*` — a direct visit renders the honest error state below
 * from the backend's own `403`, not a fabricated empty list. Org Admin never reaches this route
 * at all (`organizationNav` has a *separate* `/org/users` entry this phase does not build — see
 * this module's own docstring gap note below).
 *
 * Not yet scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap — see `./api.ts`'s
 * `listUsers` docstring), so every viewer who can reach this route currently sees every user.
 *
 * **Known gap, flagged rather than silently worked around:** `organizationNav` (`navConfig.ts`)
 * has its own "Users & Roles" entry at `/org/users` for Org Admin, still a `PlaceholderPage` —
 * out of this phase's scope per the roadmap (`docs/architecture/frontend-flutter-master-roadmap.md`
 * §"Phase F2" only names `/platform/users`). Wiring it to this same `/users` endpoint later would
 * be a no-op for every Org Admin today regardless: the seeded RBAC matrix
 * (`migrations/versions/20260721_0900_5437a5d1651b_iam_create_role_permissions_table.py`) grants
 * `org_admin` none of `iam.users.read`/`create`/`update` — only `founder` has create/update, and
 * `founder`/`regional_manager`/`support_staff` have read.
 */
export function UsersPage() {
  usePageHeader("Users & Roles", "Platform accounts, roles, and status across every organization");

  const principal = useAuthStore((s) => s.principal);
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [resetPasswordOpen, setResetPasswordOpen] = useState(false);
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
    queryKey: ["users", "list"],
    fetcher: listUsers,
    initialSort: { field: "full_name", direction: "asc" },
  });

  // Debounces the free-text `?q=` search so it doesn't fire a request on every keystroke —
  // matches `OrganizationsPage`'s identical convention.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // Read-only organization-name lookup: `User.organizationId` has no join, only an opaque id
  // (present for org_admin/driver/parent, absent otherwise), so a friendly name in the
  // table/drawer needs a separate `GET /organizations` read — the same pattern
  // `OrganizationsPage`'s own `regionsLookup` establishes for `Organization.regionId`. Up to 100
  // organizations resolve to a name; beyond that this falls back to the raw id rather than
  // fabricating a name.
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
    mutationFn: (input: { id: string; status: UserStatus }) =>
      updateUserStatus(input.id, input.status as Extract<UserStatus, "active" | "disabled">),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ["users", "list"] });
      setSelectedUser(user);
      toast.success("User updated", `${user.fullName} is now ${statusLabel(user.status).toLowerCase()}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update the user.";
      toast.error("Update failed", message);
    },
  });

  const mfaMutation = useMutation({
    mutationFn: (input: { id: string; mfaEnabled: boolean }) => updateUserMfa(input.id, input.mfaEnabled),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ["users", "list"] });
      setSelectedUser(user);
      toast.success("User updated", `MFA is now ${user.mfaEnabled ? "enabled" : "disabled"} for ${user.fullName}.`);
    },
    onError: (mutationError) => {
      const message =
        mutationError instanceof ApiError ? mutationError.message : "Could not update MFA.";
      toast.error("Update failed", message);
    },
  });

  function isStatusPendingFor(status: UserStatus): boolean {
    return (
      statusMutation.isPending &&
      statusMutation.variables?.id === selectedUser?.id &&
      statusMutation.variables?.status === status
    );
  }

  function isMfaPendingFor(mfaEnabled: boolean): boolean {
    return (
      mfaMutation.isPending &&
      mfaMutation.variables?.id === selectedUser?.id &&
      mfaMutation.variables?.mfaEnabled === mfaEnabled
    );
  }

  const columns = useMemo<ColumnDef<User, unknown>[]>(
    () => [
      {
        id: "fullName",
        header: "User",
        meta: { sortField: "full_name" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className={styles.leadCell}>
            <Avatar
              initials={avatarInitials(row.original.fullName)}
              color={getRoleDisplay(row.original.role).color}
              size="sm"
            />
            <div className={styles.leadText}>
              <div className={styles.leadTitle}>{row.original.fullName}</div>
              <div className={styles.leadSubtitle}>
                {row.original.email ?? row.original.phone ?? "—"}
              </div>
            </div>
          </div>
        ),
      },
      {
        id: "role",
        header: "Role",
        cell: ({ row }) => (
          <Badge variant={roleTone(row.original.role)}>{getRoleDisplay(row.original.role).label}</Badge>
        ),
      },
      {
        id: "organization",
        header: "Organization",
        cell: ({ row }) => {
          if (!row.original.organizationId) {
            return <span className={styles.muted}>—</span>;
          }
          const name = organizationNameById.get(row.original.organizationId);
          return name ? <span>{name}</span> : <MonoText>{row.original.organizationId}</MonoText>;
        },
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
  const activeRoleFilter = filters.role ?? "all";

  // Coarse, presentation-only role gating (`.claude/rules/frontend.md` #2) — per the seeded RBAC
  // matrix (see this module's own docstring), only `founder` currently holds
  // `iam.users.create`/`iam.users.update`; every management action (invite, status, MFA) is
  // hidden for anyone else, exactly mirroring `OrganizationsPage`'s identical `canCreate`
  // precedent. The backend's own `require_permission` remains the real, unbypassable gate.
  const canManage = principal?.role === "founder";
  // `iam.users.reset_password` (ADR-0017 Amendment migration `b8e2f4a91c67`) is granted more
  // widely than `iam.users.update` — founder, regional_manager, and support_staff, matching an
  // existing grant shape rather than a new access-control decision (see that migration's own
  // docstring) — so this hint is deliberately its own, wider check, not a reuse of `canManage`.
  const canResetPassword =
    principal?.role === "founder" ||
    principal?.role === "regional_manager" ||
    principal?.role === "support_staff";

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <div className={styles.filterRows}>
          <FilterChips
            options={STATUS_FILTERS}
            activeId={activeStatusFilter}
            onSelect={(id) => setFilter("status", id === "all" ? null : id)}
          />
          <FilterChips
            options={ROLE_FILTERS}
            activeId={activeRoleFilter}
            onSelect={(id) => setFilter("role", id === "all" ? null : id)}
          />
        </div>
        <div className={styles.toolbarActions}>
          <Input
            icon={<Search size={14} />}
            placeholder="Search users…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Search users"
          />
          {canManage && (
            <Button leadingIcon={<Plus size={15} />} onClick={() => setInviteOpen(true)}>
              Invite user
            </Button>
          )}
        </div>
      </div>

      {isError ? (
        <EmptyState
          icon={<UsersRound size={22} />}
          title="Could not load users"
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
            onRowClick={setSelectedUser}
            emptyState={
              <EmptyState
                icon={<UsersRound size={22} />}
                title="No users yet"
                description="Users you invite will appear here."
                action={
                  canManage ? (
                    <Button
                      variant="secondary"
                      leadingIcon={<Plus size={15} />}
                      onClick={() => setInviteOpen(true)}
                    >
                      Invite user
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
        open={selectedUser !== null}
        onClose={() => setSelectedUser(null)}
        icon={<UsersRound size={22} />}
        iconTint="var(--color-brand-primary-tint)"
        iconColor="var(--color-brand-primary)"
        title={selectedUser?.fullName}
        subtitle={selectedUser ? getRoleDisplay(selectedUser.role).label : undefined}
        status={
          selectedUser && (
            <Badge variant={statusTone(selectedUser.status)} dot>
              {statusLabel(selectedUser.status)}
            </Badge>
          )
        }
        rows={
          selectedUser
            ? [
                { key: "Role", value: getRoleDisplay(selectedUser.role).label },
                ...(selectedUser.organizationId
                  ? [
                      {
                        key: "Organization",
                        value: organizationNameById.get(selectedUser.organizationId) ?? selectedUser.organizationId,
                      },
                    ]
                  : []),
                { key: "Email", value: selectedUser.email ?? "—" },
                { key: "Phone", value: selectedUser.phone ?? "—" },
                {
                  key: "MFA",
                  value: (
                    <Badge variant={selectedUser.mfaEnabled ? "success" : "neutral"}>
                      {selectedUser.mfaEnabled ? "Enabled" : "Disabled"}
                    </Badge>
                  ),
                },
                {
                  key: "Last login",
                  value: selectedUser.lastLoginAt ? formatDateTime(selectedUser.lastLoginAt) : "Never",
                },
                { key: "User ID", value: <MonoText>{selectedUser.id}</MonoText> },
                { key: "Created", value: formatDate(selectedUser.createdAt) },
                { key: "Updated", value: formatDate(selectedUser.updatedAt) },
              ]
            : []
        }
        footer={
          selectedUser &&
          (canManage || canResetPassword) && (
            <div className={styles.drawerActions}>
              {canManage && selectedUser.status !== "active" && (
                <Button
                  variant="secondary"
                  loading={isStatusPendingFor("active")}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedUser.id, status: "active" })}
                >
                  Activate
                </Button>
              )}
              {canManage && selectedUser.status !== "disabled" && (
                <Button
                  variant="danger"
                  loading={isStatusPendingFor("disabled")}
                  disabled={statusMutation.isPending}
                  onClick={() => statusMutation.mutate({ id: selectedUser.id, status: "disabled" })}
                >
                  Disable
                </Button>
              )}
              {canManage &&
                (selectedUser.mfaEnabled ? (
                  <Button
                    variant="secondary"
                    loading={isMfaPendingFor(false)}
                    disabled={mfaMutation.isPending}
                    onClick={() => mfaMutation.mutate({ id: selectedUser.id, mfaEnabled: false })}
                  >
                    Disable MFA
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    loading={isMfaPendingFor(true)}
                    disabled={mfaMutation.isPending}
                    onClick={() => mfaMutation.mutate({ id: selectedUser.id, mfaEnabled: true })}
                  >
                    Enable MFA
                  </Button>
                ))}
              {canResetPassword && (
                <Button variant="secondary" onClick={() => setResetPasswordOpen(true)}>
                  Reset password
                </Button>
              )}
            </div>
          )
        }
      />

      <InviteUserForm open={inviteOpen} onClose={() => setInviteOpen(false)} />
      <ResetUserPasswordForm
        open={resetPasswordOpen}
        user={selectedUser}
        onClose={() => setResetPasswordOpen(false)}
      />
    </div>
  );
}
