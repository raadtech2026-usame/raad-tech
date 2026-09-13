import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `transport_ops.domain.value_objects.ParentStatus` (Database Design §6.3 gives `parents.status`
 * with no enumerated values at all, unlike §6.2's fully-spelled-out `students.status ENUM(...)` —
 * `value_objects.py`'s own docstring: "flagged, not guessed"). A flat active/inactive toggle,
 * mirroring `organization.domain.value_objects.RegionStatus`'s identical situation. Both values
 * transport via `PATCH /parents/{id}`'s `status` field, folded in alongside the profile fields
 * since no dedicated behavioral status sub-route is documented for `/parents` (unlike
 * `/students/{id}/status`). */
export type ParentStatus = "active" | "inactive";

/** Full `ParentResponse` shape (`transport_ops.api.schemas`) — returned by `GET /parents/{id}`
 * only. See `ParentSummary` below for why `GET /parents` (the list route) cannot return this
 * shape. Fields after `updatedAt` are the additive profile fields (2026-09-10, Parent & Student
 * Domain Restructure) — not in Database Design §6.3, all optional. */
export interface Parent {
  id: string;
  organizationId: string;
  userId: string;
  fullName: string;
  phone: string | null;
  status: ParentStatus;
  createdAt: string;
  updatedAt: string;
  alternatePhone: string | null;
  address: string | null;
  emergencyContactName: string | null;
  emergencyContactPhone: string | null;
  notes: string | null;
}

/** `ParentSummaryResponse` (`transport_ops/api/schemas.py`) — the *only* shape `GET /parents`
 * returns (`routers.py`'s `list_parents`,
 * `response_model=OffsetPageResponse[ParentSummaryResponse]`). Deliberately thin: no
 * `organization_id`, no `user_id`, no `phone`, no `created_at`/`updated_at` — see
 * `features/transport-ops/students/api.ts`'s `StudentSummary` docstring for the identical, real
 * `transport_ops`-wide reasoning. */
export interface ParentSummary {
  id: string;
  fullName: string;
  status: ParentStatus;
}

/** Wire shape of `ParentResponse` — snake_case, exactly as the backend serializes it. */
interface ParentWire {
  id: string;
  organization_id: string;
  user_id: string;
  full_name: string;
  phone: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  alternate_phone: string | null;
  address: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  notes: string | null;
}

/** Wire shape of `ParentSummaryResponse`. */
interface ParentSummaryWire {
  id: string;
  full_name: string;
  status: string;
}

function toParent(wire: ParentWire): Parent {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    userId: wire.user_id,
    fullName: wire.full_name,
    phone: wire.phone,
    status: wire.status as ParentStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    alternatePhone: wire.alternate_phone,
    address: wire.address,
    emergencyContactName: wire.emergency_contact_name,
    emergencyContactPhone: wire.emergency_contact_phone,
    notes: wire.notes,
  };
}

function toParentSummary(wire: ParentSummaryWire): ParentSummary {
  return { id: wire.id, fullName: wire.full_name, status: wire.status as ParentStatus };
}

/** `GET /parents` (API Contracts §4.3's `/parents` row; `transport_ops.api.routers.list_parents`)
 * — paginated/filterable/sortable via `usePaginatedQuery`. Whitelist confirmed against
 * `modules/transport_ops/infra/repositories.py`'s `SqlAlchemyParentRepository`: filterable
 * `status`/`phone`, sortable `full_name`/`status`, searchable `full_name`/`phone` (2026-09-10:
 * `phone` added to both, backing duplicate-parent detection and "search by name or phone").
 * Tenant-scoped server-side (ADR-0021's `_apply_scope`, applied to `list_page` at the shared
 * `SqlAlchemyRepositoryBase` layer) — an Org Admin only ever sees their own organization's
 * parents here. */
export async function listParents(params: OffsetListParams): Promise<OffsetPage<ParentSummary>> {
  const wire = await apiRequest<OffsetPageWire<ParentSummaryWire>>(`/parents?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toParentSummary);
}

/** `GET /parents/count` (RAAD business model realignment) — `transport_ops.parents.count`,
 * held by founder/regional_manager/support_staff, distinct from `.list` (which those roles no
 * longer hold, migration `c4d9a2e6f813`). Backs the RAAD Platform's "Total parents (count
 * only)" KPI tile without exposing individual parent rows — `org_admin`'s own `ParentsPage`
 * still uses `listParents` above; this is platform-only. */
export async function countParents(organizationId?: string): Promise<number> {
  const query = organizationId
    ? `?organization_id=${encodeURIComponent(organizationId)}`
    : "";
  const wire = await apiRequest<{ total: number }>(`/parents/count${query}`);
  return wire.total;
}

/** `GET /parents/{id}` — the only route returning the full `Parent` shape. `ParentsPage`'s
 * detail drawer calls this on row selection rather than reusing the list row alone. */
export async function getParent(id: string): Promise<Parent> {
  const wire = await apiRequest<ParentWire>(`/parents/${id}`);
  return toParent(wire);
}

/** One child inside `RegisterParentInput.children` (ADR-0041 §2) — the same shape
 * `features/transport-ops/students/api.ts`'s own `CreateStudentInput` carries, minus
 * `organizationId` (the parent's own), plus the `student_parents` link fields a separate
 * `POST /students/{id}/parents` call would otherwise need. Duplicated here rather than
 * cross-imported from `students/api.ts` — the same "a small amount of duplication beats coupling
 * two otherwise-independent feature folders" precedent this file's own docstring already
 * establishes for `unlinkStudentFromParent`/`ParentOption`. */
export interface ChildEnrollmentInput {
  fullName: string;
  externalRef?: string | null;
  dateOfBirth?: string | null;
  gender?: string | null;
  notes?: string | null;
  relationship?: string | null;
  isPrimary?: boolean;
}

export interface RegisterParentInput {
  organizationId: string;
  fullName: string;
  email?: string | null;
  phone?: string | null;
  alternatePhone?: string | null;
  address?: string | null;
  emergencyContactName?: string | null;
  emergencyContactPhone?: string | null;
  notes?: string | null;
  /** ADR-0041 §2 — when given (even `[]`), the Parent and every listed child are created and
   * linked in one backend transaction (`POST /parents`'s own `children` field). Omit entirely
   * to register a parent with no children yet, unchanged from the original single-parent flow. */
  children?: ChildEnrollmentInput[];
  /** 2026-09-12 business-model correction — the family's *one* Vehicle/Route/Stop pair,
   * applied identically to every child in `children` in the same backend transaction. Only
   * consumed when `children` is also given; `pickupStopId`/`dropoffStopId` are required
   * together with `routeId` (`vehicleId` alone stays optional). Omit all four to register a
   * parent (and children) with no transportation yet — assignable later via
   * `setFamilyTransportation`. */
  routeId?: string | null;
  pickupStopId?: string | null;
  dropoffStopId?: string | null;
  vehicleId?: string | null;
}

/** One row of `ParentCreatedResponse.children` — just enough of `StudentResponse` to confirm
 * what was created and show it in the post-save summary; the full `Student` shape is only ever
 * needed on the Students page itself. */
export interface RegisteredChild {
  id: string;
  fullName: string;
  dateOfBirth: string | null;
  gender: string | null;
  status: string;
}

interface RegisteredChildWire {
  id: string;
  full_name: string;
  date_of_birth: string | null;
  gender: string | null;
  status: string;
}

function toRegisteredChild(wire: RegisteredChildWire): RegisteredChild {
  return {
    id: wire.id,
    fullName: wire.full_name,
    dateOfBirth: wire.date_of_birth,
    gender: wire.gender,
    status: wire.status,
  };
}

export interface RegisterParentResult {
  parent: Parent;
  /** The generated one-time login password for the linked `iam.User` (role=parent) — surfaced
   * exactly once, here, for hand-off. Never re-derivable via `GET /parents/{id}`. */
  temporaryPassword: string;
  /** Populated exactly when `RegisterParentInput.children` was given. */
  children: RegisteredChild[];
}

/** `POST /parents` (`RegisterParentRequest`, `transport_ops.api.schemas`) — ADR-0003: the
 * caller no longer supplies a `user_id`. The backend provisions the linked `iam.User`
 * (role=parent) itself from `full_name`/`email`/`phone` (at least one of `email`/`phone` is
 * required — `iam.User`'s own invariant) and returns `{parent, temporary_password}`
 * (`ParentCreatedResponse`), not a bare `Parent`.
 *
 * **`input.children` (ADR-0041 §2)** — the primary "Add Parent -> add children -> Save" flow:
 * the Parent and every child are created and linked in one backend transaction
 * (`ParentApplicationService.register_parent_with_children`), never a separate per-child
 * `POST /students` + `POST /students/{id}/parents` round trip from this form. */
export async function registerParent(input: RegisterParentInput): Promise<RegisterParentResult> {
  const wire = await apiRequest<{
    parent: ParentWire;
    temporary_password: string;
    children: RegisteredChildWire[];
  }>("/parents", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      full_name: input.fullName,
      email: input.email ?? null,
      phone: input.phone ?? null,
      alternate_phone: input.alternatePhone ?? null,
      address: input.address ?? null,
      emergency_contact_name: input.emergencyContactName ?? null,
      emergency_contact_phone: input.emergencyContactPhone ?? null,
      notes: input.notes ?? null,
      children:
        input.children === undefined
          ? undefined
          : input.children.map((child) => ({
              full_name: child.fullName,
              external_ref: child.externalRef ?? null,
              date_of_birth: child.dateOfBirth ?? null,
              gender: child.gender ?? null,
              notes: child.notes ?? null,
              relationship: child.relationship ?? null,
              is_primary: child.isPrimary ?? false,
            })),
      route_id: input.routeId ?? null,
      pickup_stop_id: input.pickupStopId ?? null,
      dropoff_stop_id: input.dropoffStopId ?? null,
      vehicle_id: input.vehicleId ?? null,
    },
  });
  return {
    parent: toParent(wire.parent),
    temporaryPassword: wire.temporary_password,
    children: (wire.children ?? []).map(toRegisteredChild),
  };
}

/** `PATCH /parents/{id}` sending `status` only — dispatches to `activate_parent`/
 * `disable_parent` (`routers.py`'s `update_parent`), leaving every other field untouched since
 * the router only processes fields actually present in the body. */
export async function updateParentStatus(id: string, status: ParentStatus): Promise<Parent> {
  const wire = await apiRequest<ParentWire>(`/parents/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toParent(wire);
}

export interface UpdateParentInput {
  fullName: string;
  phone?: string | null;
  alternatePhone?: string | null;
  address?: string | null;
  emergencyContactName?: string | null;
  emergencyContactPhone?: string | null;
  notes?: string | null;
}

/** `PATCH /parents/{id}` sending the editable profile fields (never `status`, which has its own
 * dedicated `updateParentStatus` action in the drawer footer — editing a parent's contact
 * details is a materially different, lower-stakes action than activating/deactivating their
 * profile). Protects relationships/financial history structurally: this route has no way to
 * touch `student_parents` links or `erp_student_payments` rows at all. */
export async function updateParent(id: string, input: UpdateParentInput): Promise<Parent> {
  const wire = await apiRequest<ParentWire>(`/parents/${id}`, {
    method: "PATCH",
    body: {
      full_name: input.fullName,
      phone: input.phone ?? null,
      alternate_phone: input.alternatePhone ?? null,
      address: input.address ?? null,
      emergency_contact_name: input.emergencyContactName ?? null,
      emergency_contact_phone: input.emergencyContactPhone ?? null,
      notes: input.notes ?? null,
    },
  });
  return toParent(wire);
}

/** `StudentForParentResponse` (`transport_ops/api/schemas.py`) — one row of `GET /parents/
 * {parent_id}/students`. */
export interface LinkedStudent {
  studentId: string;
  fullName: string;
  status: string;
  relationship: string | null;
  isPrimary: boolean;
  /** ADR-0041 §2 — lets the Parent detail page's children list show date of birth without a
   * second `GET /students/{id}` per child. */
  dateOfBirth: string | null;
}

interface LinkedStudentWire {
  student_id: string;
  full_name: string;
  status: string;
  relationship: string | null;
  is_primary: boolean;
  date_of_birth: string | null;
}

function toLinkedStudent(wire: LinkedStudentWire): LinkedStudent {
  return {
    studentId: wire.student_id,
    fullName: wire.full_name,
    status: wire.status,
    relationship: wire.relationship,
    isPrimary: wire.is_primary,
    dateOfBirth: wire.date_of_birth,
  };
}

/** `GET /parents/{parent_id}/students` — a parent's linked students, a raw JSON array
 * (`response_model=list[StudentForParentResponse]`, not paginated). Backs the "Linked students"
 * section of the parent detail drawer, and — via `ParentSearchSelect.tsx` — the "Existing
 * children: N" count shown after picking a parent during student registration. */
export async function listStudentsForParent(parentId: string): Promise<LinkedStudent[]> {
  const wire = await apiRequest<LinkedStudentWire[]>(`/parents/${parentId}/students`);
  return wire.map(toLinkedStudent);
}

/** `POST /students/{student_id}/parents` (`LinkParentToStudentRequest`) — the identical route
 * `features/transport-ops/students/api.ts`'s `linkGuardianToStudent` calls, duplicated here with
 * the parameter order the Parent detail page's own "Add student" action naturally has on hand
 * (the parent is already known; only the newly-created student id varies) — the same "a small
 * amount of duplication beats coupling two otherwise-independent feature folders" precedent this
 * file's own `unlinkStudentFromParent` above already establishes. */
export async function linkStudentToParent(
  studentId: string,
  parentId: string,
  options: { relationship?: string | null; isPrimary?: boolean } = {},
): Promise<void> {
  await apiRequest(`/students/${studentId}/parents`, {
    method: "POST",
    body: {
      parent_id: parentId,
      relationship: options.relationship ?? null,
      is_primary: options.isPrimary ?? false,
    },
  });
}

/** `DELETE /students/{student_id}/parents/{parent_id}` — the identical unlink route
 * `features/transport-ops/students/api.ts`'s `unlinkGuardianFromStudent` calls, duplicated here
 * with the parameter order the parent detail drawer naturally has on hand. */
export async function unlinkStudentFromParent(parentId: string, studentId: string): Promise<void> {
  await apiRequest<void>(`/students/${studentId}/parents/${parentId}`, { method: "DELETE" });
}

export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup — see `features/fleet-devices/vehicles/api.ts`'s
 * identical function for why this is deliberately its own self-contained copy. */
export async function listOrganizationsForPicker(search: string): Promise<OrganizationOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<OrganizationOptionWire>>(`/organizations?${query}`);
  return wire.data.map((org) => ({ id: org.id, name: org.name }));
}

export interface ParentOption {
  id: string;
  fullName: string;
  status: string;
}

interface ParentOptionWire {
  id: string;
  full_name: string;
  status: string;
}

/** Read-only `GET /parents` lookup backing `ParentSearchSelect` (and `LinkGuardianForm`'s own
 * picker before it) — searches by **name or phone** (2026-09-10: `phone` joined `full_name` in
 * the backend's own `searchable_fields`), capped at 100 matches like every other picker in this
 * codebase. Tenant-scoped server-side exactly like `listParents` above. */
export async function listParentsForPicker(search: string): Promise<ParentOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "full_name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<ParentOptionWire>>(`/parents?${query}`);
  return wire.data.map((parent) => ({ id: parent.id, fullName: parent.full_name, status: parent.status }));
}

/** Duplicate-parent check (2026-09-10): an **exact** phone match within the caller's own
 * organization, via the same `filter[phone]` whitelist entry `listParentsForPicker`'s own search
 * uses as a substring. Returns the first match, or `null` if the phone is not already in use —
 * `CreateParentForm` uses this to warn before registering a second parent for a family that
 * already has one, rather than letting the attempt fail later with a generic conflict from
 * `iam.users.phone`'s own global unique constraint. */
export async function findParentByExactPhone(phone: string): Promise<ParentSummary | null> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 1,
    sort: { field: "full_name", direction: "asc" },
    filters: { phone },
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<ParentSummaryWire>>(`/parents?${query}`);
  return wire.data.length > 0 ? toParentSummary(wire.data[0]) : null;
}

// ---- Parent financial summary (2026-09-10, "Parent & Student Domain Restructure + Parent
// Payments") — `/school-finance/parents/*`, owned by the `school_erp` backend module. Kept here
// rather than in `features/school-erp/api.ts` since every caller of these three functions is a
// Parent-page component in *this* folder — the same "duplicate a small amount rather than couple
// two otherwise-independent feature folders" precedent this codebase's own `api.ts` modules
// already establish for cross-cutting reads (`.claude/rules/frontend.md` #1). ----------------

export type ParentPaymentStatus = "paid" | "partially_paid" | "unpaid" | "no_invoices";

export interface ParentChildFinancial {
  studentId: string;
  fullName: string;
  status: string;
  totalDue: string;
  totalPaid: string;
  outstanding: string;
  invoiceCount: number;
}

export interface ParentFinancialSummary {
  parentId: string;
  currency: string;
  totalDue: string;
  totalPaid: string;
  outstanding: string;
  status: ParentPaymentStatus;
  children: ParentChildFinancial[];
}

interface ParentChildFinancialWire {
  student_id: string;
  full_name: string;
  status: string;
  total_due: string;
  total_paid: string;
  outstanding: string;
  invoice_count: number;
}

interface ParentFinancialSummaryWire {
  parent_id: string;
  currency: string;
  total_due: string;
  total_paid: string;
  outstanding: string;
  status: string;
  children: ParentChildFinancialWire[];
}

function toParentFinancialSummary(wire: ParentFinancialSummaryWire): ParentFinancialSummary {
  return {
    parentId: wire.parent_id,
    currency: wire.currency,
    totalDue: wire.total_due,
    totalPaid: wire.total_paid,
    outstanding: wire.outstanding,
    status: wire.status as ParentPaymentStatus,
    children: wire.children.map((child) => ({
      studentId: child.student_id,
      fullName: child.full_name,
      status: child.status,
      totalDue: child.total_due,
      totalPaid: child.total_paid,
      outstanding: child.outstanding,
      invoiceCount: child.invoice_count,
    })),
  };
}

/** `GET /school-finance/parents/{parent_id}/summary` — the family-level sum across every one of
 * this parent's children's non-cancelled invoices. `status` is one of `paid`/`partially_paid`/
 * `unpaid`/`no_invoices` — the fourth value means "no fee has been billed to this family yet",
 * never rendered as a debt. */
export async function getParentFinancialSummary(parentId: string): Promise<ParentFinancialSummary> {
  const wire = await apiRequest<ParentFinancialSummaryWire>(`/school-finance/parents/${parentId}/summary`);
  return toParentFinancialSummary(wire);
}

/** Same two-place-decimal-string formatting as `features/school-erp/api.ts`'s own `formatAmount`
 * — duplicated rather than cross-imported, matching this file's own precedent above. */
export function formatParentAmount(amount: string, currency: string): string {
  return `${currency} ${amount}`;
}

// ---- ParentBillingProfile / ParentInvoice — real aggregates (ADR-0042, 2026-09-11) -----------
// Supersedes ADR-0041 §1's grouped-read-model bindings below. The old family-payment quick-action
// (`recordParentPayment`/`listParentPayments`) is removed outright, not kept alongside the real
// thing — payment status now lives directly on one Parent Invoice
// (`setParentInvoicePaymentStatus`), with no allocation and no payment history in the UI.

export interface ParentBillingProfile {
  id: string;
  organizationId: string;
  parentId: string;
  monthlyFee: string;
  currency: string;
  billingStartPeriod: string;
  dueDay: number;
  status: "active" | "inactive";
  createdAt: string;
  updatedAt: string;
}

interface ParentBillingProfileWire {
  id: string;
  organization_id: string;
  parent_id: string;
  monthly_fee: string;
  currency: string;
  billing_start_period: string;
  due_day: number;
  status: string;
  created_at: string;
  updated_at: string;
}

function toParentBillingProfile(wire: ParentBillingProfileWire): ParentBillingProfile {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    parentId: wire.parent_id,
    monthlyFee: wire.monthly_fee,
    currency: wire.currency,
    billingStartPeriod: wire.billing_start_period,
    dueDay: wire.due_day,
    status: wire.status as "active" | "inactive",
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

/** `GET /school-finance/parents/{parent_id}/billing-profile` — the family's actual recurring
 * transportation charge, or `null` if none has been entered yet. */
export async function getParentBillingProfile(parentId: string): Promise<ParentBillingProfile | null> {
  const wire = await apiRequest<ParentBillingProfileWire | null>(
    `/school-finance/parents/${parentId}/billing-profile`,
  );
  return wire ? toParentBillingProfile(wire) : null;
}

export interface SaveParentBillingProfileInput {
  monthlyFee: string;
  currency: string;
  billingStartPeriod: string;
  dueDay: number;
}

/** `PUT /school-finance/parents/{parent_id}/billing-profile` — creates the profile if the parent
 * has none yet, otherwise edits the existing one in place. Editing never rewrites an
 * already-generated invoice, which froze its own amount at generation time. */
export async function saveParentBillingProfile(
  parentId: string,
  input: SaveParentBillingProfileInput,
): Promise<ParentBillingProfile> {
  const wire = await apiRequest<ParentBillingProfileWire>(
    `/school-finance/parents/${parentId}/billing-profile`,
    {
      method: "PUT",
      body: {
        monthly_fee: input.monthlyFee,
        currency: input.currency,
        billing_start_period: input.billingStartPeriod,
        due_day: input.dueDay,
      },
    },
  );
  return toParentBillingProfile(wire);
}

/** `PATCH /school-finance/parent-billing-profiles/{id}/status` — deactivating stops future
 * monthly generation from picking this family up, without deleting its own billing history. */
export async function setParentBillingProfileStatus(
  billingProfileId: string,
  isActive: boolean,
): Promise<ParentBillingProfile> {
  const wire = await apiRequest<ParentBillingProfileWire>(
    `/school-finance/parent-billing-profiles/${billingProfileId}/status`,
    { method: "PATCH", body: { is_active: isActive } },
  );
  return toParentBillingProfile(wire);
}

/** The three, and only three, user-facing payment states a Parent Invoice can be in. */
export type ParentInvoiceStatus = "unpaid" | "partial" | "paid" | "cancelled";

export interface ParentInvoiceSummary {
  id: string;
  parentId: string;
  parentName: string;
  period: string;
  invoiceNumber: string;
  childrenCount: number;
  amount: string;
  amountPaid: string;
  balanceDue: string;
  status: ParentInvoiceStatus;
  invoiceDate: string;
  dueDate: string;
  currency: string;
}

interface ParentInvoiceSummaryWire {
  id: string;
  parent_id: string;
  parent_name: string;
  period: string;
  invoice_number: string;
  children_count: number;
  amount: string;
  amount_paid: string;
  balance_due: string;
  status: string;
  invoice_date: string;
  due_date: string;
  currency: string;
}

function toParentInvoiceSummary(wire: ParentInvoiceSummaryWire): ParentInvoiceSummary {
  return {
    id: wire.id,
    parentId: wire.parent_id,
    parentName: wire.parent_name,
    period: wire.period,
    invoiceNumber: wire.invoice_number,
    childrenCount: wire.children_count,
    amount: wire.amount,
    amountPaid: wire.amount_paid,
    balanceDue: wire.balance_due,
    status: wire.status as ParentInvoiceStatus,
    invoiceDate: wire.invoice_date,
    dueDate: wire.due_date,
    currency: wire.currency,
  };
}

export interface ListParentInvoicesParams {
  page: number;
  pageSize: number;
  period?: string | null;
  status?: ParentInvoiceStatus | null;
  parentId?: string | null;
  vehicleId?: string | null;
  /** ISO `YYYY-MM-DD`, inclusive — the Finance page's own From/To date-range picker (Finance UI
   * cleanup, 2026-09-12), filtering on `invoice_date`. Independent of `period`: a caller may pass
   * either, both, or neither. */
  dateFrom?: string | null;
  dateTo?: string | null;
}

/** `GET /school-finance/parent-invoices` — the Finance page's primary listing (ADR-0042): every
 * real `ParentInvoice` in scope, never a grouping of per-student rows. */
export async function listParentInvoices(
  params: ListParentInvoicesParams,
): Promise<OffsetPage<ParentInvoiceSummary>> {
  const qs = new URLSearchParams({ page: String(params.page), page_size: String(params.pageSize) });
  if (params.period) qs.set("period", params.period);
  if (params.status) qs.set("status", params.status);
  if (params.parentId) qs.set("parent_id", params.parentId);
  if (params.vehicleId) qs.set("vehicle_id", params.vehicleId);
  if (params.dateFrom) qs.set("date_from", params.dateFrom);
  if (params.dateTo) qs.set("date_to", params.dateTo);
  const wire = await apiRequest<OffsetPageWire<ParentInvoiceSummaryWire>>(
    `/school-finance/parent-invoices?${qs}`,
  );
  return toOffsetPage(wire, toParentInvoiceSummary);
}

export interface ParentInvoiceLine {
  studentId: string;
  fullName: string;
  amount: string;
  vehicleId: string | null;
  routeId: string | null;
}

interface ParentInvoiceLineWire {
  student_id: string;
  full_name: string;
  amount: string;
  vehicle_id: string | null;
  route_id: string | null;
}

export interface ParentInvoiceDetail {
  id: string;
  parentId: string;
  parentName: string;
  period: string;
  invoiceNumber: string;
  amount: string;
  amountPaid: string;
  balanceDue: string;
  status: ParentInvoiceStatus;
  currency: string;
  invoiceDate: string;
  dueDate: string;
  notes: string | null;
  lines: ParentInvoiceLine[];
}

interface ParentInvoiceDetailWire {
  id: string;
  parent_id: string;
  parent_name: string;
  period: string;
  invoice_number: string;
  amount: string;
  amount_paid: string;
  balance_due: string;
  status: string;
  currency: string;
  invoice_date: string;
  due_date: string;
  notes: string | null;
  lines: ParentInvoiceLineWire[];
}

function toParentInvoiceDetail(wire: ParentInvoiceDetailWire): ParentInvoiceDetail {
  return {
    id: wire.id,
    parentId: wire.parent_id,
    parentName: wire.parent_name,
    period: wire.period,
    invoiceNumber: wire.invoice_number,
    amount: wire.amount,
    amountPaid: wire.amount_paid,
    balanceDue: wire.balance_due,
    status: wire.status as ParentInvoiceStatus,
    currency: wire.currency,
    invoiceDate: wire.invoice_date,
    dueDate: wire.due_date,
    notes: wire.notes,
    lines: wire.lines.map((line) => ({
      studentId: line.student_id,
      fullName: line.full_name,
      amount: line.amount,
      vehicleId: line.vehicle_id,
      routeId: line.route_id,
    })),
  };
}

/** `GET /school-finance/parent-invoices/{id}` — one Parent Invoice's own child line items. */
export async function getParentInvoiceDetail(invoiceId: string): Promise<ParentInvoiceDetail> {
  const wire = await apiRequest<ParentInvoiceDetailWire>(`/school-finance/parent-invoices/${invoiceId}`);
  return toParentInvoiceDetail(wire);
}

/** `POST /school-finance/parent-invoices/generate` — the monthly billing run (Part 18): every
 * `active` Billing Profile whose billing has started is picked up automatically. Idempotent —
 * re-running for a period a parent was already billed for skips that parent, never double-charges. */
export async function generateParentInvoices(period: string): Promise<ParentInvoiceDetail[]> {
  const wire = await apiRequest<ParentInvoiceDetailWire[]>(`/school-finance/parent-invoices/generate`, {
    method: "POST",
    body: { period },
  });
  return wire.map(toParentInvoiceDetail);
}

export interface SetParentInvoicePaymentStatusInput {
  status: ParentInvoiceStatus;
  /** Required only when `status === "partial"`; ignored (resolved server-side) for `paid`/`unpaid`. */
  amountPaid?: string | null;
}

/** `PATCH /school-finance/parent-invoices/{id}/payment-status` — the entire user-facing payment
 * workflow (Part 9): Unpaid/Partial/Paid, set directly on the invoice. No payment method,
 * reference or history — the database recalculates amount paid, balance, Receivables and
 * Collected on save. */
export async function setParentInvoicePaymentStatus(
  invoiceId: string,
  input: SetParentInvoicePaymentStatusInput,
): Promise<ParentInvoiceSummary> {
  const wire = await apiRequest<ParentInvoiceSummaryWire>(
    `/school-finance/parent-invoices/${invoiceId}/payment-status`,
    {
      method: "PATCH",
      body: { status: input.status, amount_paid: input.amountPaid ?? null },
    },
  );
  return toParentInvoiceSummary(wire);
}

/** `POST /school-finance/parent-invoices/{id}/cancel` — voids an invoice issued in error.
 * Rejected server-side if the invoice has already received any payment. */
export async function cancelParentInvoice(
  invoiceId: string,
  reason?: string | null,
): Promise<ParentInvoiceSummary> {
  const wire = await apiRequest<ParentInvoiceSummaryWire>(
    `/school-finance/parent-invoices/${invoiceId}/cancel`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toParentInvoiceSummary(wire);
}

// ---- Family transportation (2026-09-12 business-model correction) --------------------------
// RAAD's "one Parent/family = one bus" rule: the Vehicle/Route/Stop pair is a *family* property,
// assigned once here (at registration, or later via `setFamilyTransportation`) rather than per
// child. Route/stop/vehicle picker helpers below are duplicated from `student-assignments/api.ts`
// rather than cross-imported — the same "a small amount of duplication beats coupling two
// otherwise-independent feature folders" precedent this file's own `ChildEnrollmentInput`
// docstring already establishes for `students/api.ts`.

export interface RouteOption {
  id: string;
  name: string;
}

interface RouteOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /routes` lookup for `CreateParentForm`'s/`FamilyTransportationForm`'s
 * route picker. **Not organization-scoped** — `SqlAlchemyRouteRepository`'s `filterable_fields`
 * whitelists only `status` (confirmed in `infra/repositories.py`); a cross-organization pick
 * still surfaces the backend's real `DomainError` verbatim via a toast on submit. */
export async function listRoutesForPicker(search: string): Promise<RouteOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<RouteOptionWire>>(`/routes?${query}`);
  return wire.data.map((route) => ({ id: route.id, name: route.name }));
}

export interface StopOption {
  id: string;
  name: string;
  sequenceNo: number;
}

export interface RouteWithStops {
  id: string;
  name: string;
  stops: StopOption[];
}

interface RouteWithStopsWire {
  id: string;
  name: string;
  stops: { id: string; name: string; sequence_no: number }[];
}

/** Minimal, read-only `GET /routes/{id}` read — its embedded, pre-ordered `stops` list backs the
 * pickup/dropoff stop pickers once a route is chosen. */
export async function getRouteWithStops(routeId: string): Promise<RouteWithStops> {
  const wire = await apiRequest<RouteWithStopsWire>(`/routes/${routeId}`);
  return {
    id: wire.id,
    name: wire.name,
    stops: wire.stops.map((stop) => ({ id: stop.id, name: stop.name, sequenceNo: stop.sequence_no })),
  };
}

export interface VehicleOption {
  id: string;
  plateNo: string;
  label: string | null;
}

interface VehicleOptionWire {
  id: string;
  plate_no: string;
  label: string | null;
}

/** Minimal, read-only `GET /vehicles` lookup for the optional family vehicle picker —
 * `fleet_device`'s repository does whitelist `organization_id`, so this stays genuinely
 * organization-scoped. */
export async function listVehiclesForPicker(organizationId: string, search: string): Promise<VehicleOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters: { organization_id: organizationId, status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehicleOptionWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({ id: vehicle.id, plateNo: vehicle.plate_no, label: vehicle.label }));
}

export interface SetFamilyTransportationInput {
  routeId: string;
  pickupStopId: string;
  dropoffStopId: string;
  vehicleId?: string | null;
}

/** `PUT /parents/{id}/transportation` (2026-09-12 business-model correction) — the one place an
 * admin assigns or changes a family's transportation. Ends every one of this Parent's currently
 * linked children's active `StudentAssignment` (if any) and creates a fresh one for each,
 * sharing this exact route/stops/vehicle, in one backend transaction: a family can never end up
 * split across two buses, because there is no path that assigns one child without assigning all
 * of them identically. A Parent with no linked children yet is a legal no-op. Response body
 * (the resulting assignments) is not consumed here — callers invalidate the affected queries and
 * re-fetch instead of reshaping this response, since `StudentAssignmentSection`'s own read
 * (`findActiveAssignmentForStudent`) is already the single source of truth for what's shown. */
export async function setFamilyTransportation(
  parentId: string,
  input: SetFamilyTransportationInput,
): Promise<void> {
  await apiRequest<unknown>(`/parents/${parentId}/transportation`, {
    method: "PUT",
    body: {
      route_id: input.routeId,
      pickup_stop_id: input.pickupStopId,
      dropoff_stop_id: input.dropoffStopId,
      vehicle_id: input.vehicleId ?? null,
    },
  });
}
