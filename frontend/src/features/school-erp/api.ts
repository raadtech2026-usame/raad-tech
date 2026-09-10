import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/**
 * `school_erp` (C11) — the Organization → Student money flow (ADR-0038 §2, ADR-0040 §2).
 *
 * **This file never touches `/billing`.** That is the RAAD → Organization flow, a separate
 * bounded context with separate aggregates and a separate permission namespace, and ADR-0038 §2
 * makes keeping them apart a security boundary rather than a modelling preference. The Org
 * Billing page (`features/billing/OrgBillingPage.tsx`) owns that side; this file owns school
 * finance, and neither imports the other.
 *
 * **Every monetary value is a `string`, both directions.** The backend deliberately serialises
 * `Decimal` as an exact decimal string, because JSON's only numeric type is a float and
 * `{"amount": 12.10}` is already `12.099999999999999` by the time `JSON.parse` returns. Parsing
 * these to `Number` for display is fine; parsing them to `Number` and then *summing* them is how
 * a school's ledger drifts by a cent. `sumAmounts` below exists so no component has to decide.
 */

export type StudentInvoiceStatus =
  | "draft"
  | "issued"
  | "partially_paid"
  | "paid"
  | "overdue"
  | "cancelled";

export type StudentPaymentMethod =
  | "cash"
  | "bank_transfer"
  | "mobile_money"
  | "cheque"
  | "card"
  | "other";

export type CategoryKind = "income" | "expense";

export interface FeePlan {
  id: string;
  organizationId: string;
  name: string;
  amount: string;
  currency: string;
  defaultDiscountAmount: string;
  description: string | null;
  status: "active" | "inactive";
}

export interface StudentInvoice {
  id: string;
  organizationId: string;
  studentId: string;
  feePlanId: string | null;
  period: string;
  amount: string;
  discountAmount: string;
  /** `amount - discountAmount`, computed server-side so no client re-derives it. */
  netAmount: string;
  amountPaid: string;
  balanceDue: string;
  currency: string;
  dueDate: string;
  status: StudentInvoiceStatus;
  routeId: string | null;
  vehicleId: string | null;
  driverId: string | null;
  notes: string | null;
  issuedAt: string | null;
  paidAt: string | null;
}

export interface StudentPayment {
  id: string;
  organizationId: string;
  invoiceId: string;
  studentId: string;
  amount: string;
  currency: string;
  method: StudentPaymentMethod;
  reference: string | null;
  receivedOn: string;
  notes: string | null;
  isVoided: boolean;
  voidedReason: string | null;
}

export interface FinancialCategory {
  id: string;
  organizationId: string;
  name: string;
  kind: CategoryKind;
  parentCategoryId: string | null;
  description: string | null;
  status: "active" | "inactive";
}

export interface LedgerEntry {
  id: string;
  organizationId: string;
  categoryId: string | null;
  amount: string;
  currency: string;
  occurredOn: string;
  description: string | null;
  reference: string | null;
  vehicleId?: string | null;
  isVoided: boolean;
}

export interface FinanceSummary {
  billedAmount: string;
  collectedAmount: string;
  outstandingAmount: string;
  invoiceCount: number;
  paidInvoiceCount: number;
  overdueInvoiceCount: number;
  currency: string;
}

export interface VehicleFinance {
  /** `null` groups invoices issued before the student was assigned to a bus — a real case,
   * surfaced as its own row rather than dropped so the rows still add up to the total. */
  vehicleId: string | null;
  studentCount: number;
  invoiceCount: number;
  billedAmount: string;
  collectedAmount: string;
  outstandingAmount: string;
  paidStudentCount: number;
  unpaidStudentCount: number;
  expenseAmount: string;
  netAmount: string;
  currency: string;
}

export interface ProfitAndLoss {
  start: string;
  end: string;
  studentRevenue: string;
  otherIncome: string;
  totalIncome: string;
  totalExpenses: string;
  netProfit: string;
  incomeByCategory: Record<string, string>;
  expensesByCategory: Record<string, string>;
  currency: string;
}

/* ---- Wire shapes (snake_case, exactly as the backend serialises them) --------------------- */

interface FeePlanWire {
  id: string;
  organization_id: string;
  name: string;
  amount: string;
  currency: string;
  default_discount_amount: string;
  description: string | null;
  status: string;
}

interface StudentInvoiceWire {
  id: string;
  organization_id: string;
  student_id: string;
  fee_plan_id: string | null;
  period: string;
  amount: string;
  discount_amount: string;
  net_amount: string;
  amount_paid: string;
  balance_due: string;
  currency: string;
  due_date: string;
  status: string;
  route_id: string | null;
  vehicle_id: string | null;
  driver_id: string | null;
  notes: string | null;
  issued_at: string | null;
  paid_at: string | null;
}

interface StudentPaymentWire {
  id: string;
  organization_id: string;
  invoice_id: string;
  student_id: string;
  amount: string;
  currency: string;
  method: string;
  reference: string | null;
  received_on: string;
  notes: string | null;
  is_voided: boolean;
  voided_reason: string | null;
}

interface CategoryWire {
  id: string;
  organization_id: string;
  name: string;
  kind: string;
  parent_category_id: string | null;
  description: string | null;
  status: string;
}

interface LedgerWire {
  id: string;
  organization_id: string;
  category_id: string | null;
  amount: string;
  currency: string;
  occurred_on: string;
  description: string | null;
  reference: string | null;
  vehicle_id?: string | null;
  is_voided: boolean;
}

function toFeePlan(w: FeePlanWire): FeePlan {
  return {
    id: w.id,
    organizationId: w.organization_id,
    name: w.name,
    amount: w.amount,
    currency: w.currency,
    defaultDiscountAmount: w.default_discount_amount,
    description: w.description,
    status: w.status as FeePlan["status"],
  };
}

function toStudentInvoice(w: StudentInvoiceWire): StudentInvoice {
  return {
    id: w.id,
    organizationId: w.organization_id,
    studentId: w.student_id,
    feePlanId: w.fee_plan_id,
    period: w.period,
    amount: w.amount,
    discountAmount: w.discount_amount,
    netAmount: w.net_amount,
    amountPaid: w.amount_paid,
    balanceDue: w.balance_due,
    currency: w.currency,
    dueDate: w.due_date,
    status: w.status as StudentInvoiceStatus,
    routeId: w.route_id,
    vehicleId: w.vehicle_id,
    driverId: w.driver_id,
    notes: w.notes,
    issuedAt: w.issued_at,
    paidAt: w.paid_at,
  };
}

function toStudentPayment(w: StudentPaymentWire): StudentPayment {
  return {
    id: w.id,
    organizationId: w.organization_id,
    invoiceId: w.invoice_id,
    studentId: w.student_id,
    amount: w.amount,
    currency: w.currency,
    method: w.method as StudentPaymentMethod,
    reference: w.reference,
    receivedOn: w.received_on,
    notes: w.notes,
    isVoided: w.is_voided,
    voidedReason: w.voided_reason,
  };
}

function toCategory(w: CategoryWire): FinancialCategory {
  return {
    id: w.id,
    organizationId: w.organization_id,
    name: w.name,
    kind: w.kind as CategoryKind,
    parentCategoryId: w.parent_category_id,
    description: w.description,
    status: w.status as FinancialCategory["status"],
  };
}

function toLedgerEntry(w: LedgerWire): LedgerEntry {
  return {
    id: w.id,
    organizationId: w.organization_id,
    categoryId: w.category_id,
    amount: w.amount,
    currency: w.currency,
    occurredOn: w.occurred_on,
    description: w.description,
    reference: w.reference,
    vehicleId: w.vehicle_id ?? null,
    isVoided: w.is_voided,
  };
}

/* ---- Reads -------------------------------------------------------------------------------- */

export async function getFinanceSummary(period?: string): Promise<FinanceSummary> {
  const qs = period ? `?period=${encodeURIComponent(period)}` : "";
  const wire = await apiRequest<{
    billed_amount: string;
    collected_amount: string;
    outstanding_amount: string;
    invoice_count: number;
    paid_invoice_count: number;
    overdue_invoice_count: number;
    currency: string;
  }>(`/school-finance/summary${qs}`);
  return {
    billedAmount: wire.billed_amount,
    collectedAmount: wire.collected_amount,
    outstandingAmount: wire.outstanding_amount,
    invoiceCount: wire.invoice_count,
    paidInvoiceCount: wire.paid_invoice_count,
    overdueInvoiceCount: wire.overdue_invoice_count,
    currency: wire.currency,
  };
}

export async function listVehicleFinance(period?: string): Promise<VehicleFinance[]> {
  const qs = period ? `?period=${encodeURIComponent(period)}` : "";
  const wire = await apiRequest<
    {
      vehicle_id: string | null;
      student_count: number;
      invoice_count: number;
      billed_amount: string;
      collected_amount: string;
      outstanding_amount: string;
      paid_student_count: number;
      unpaid_student_count: number;
      expense_amount: string;
      net_amount: string;
      currency: string;
    }[]
  >(`/school-finance/vehicles${qs}`);
  return wire.map((v) => ({
    vehicleId: v.vehicle_id,
    studentCount: v.student_count,
    invoiceCount: v.invoice_count,
    billedAmount: v.billed_amount,
    collectedAmount: v.collected_amount,
    outstandingAmount: v.outstanding_amount,
    paidStudentCount: v.paid_student_count,
    unpaidStudentCount: v.unpaid_student_count,
    expenseAmount: v.expense_amount,
    netAmount: v.net_amount,
    currency: v.currency,
  }));
}

export async function getProfitAndLoss(start: string, end: string): Promise<ProfitAndLoss> {
  const wire = await apiRequest<{
    start: string;
    end: string;
    student_revenue: string;
    other_income: string;
    total_income: string;
    total_expenses: string;
    net_profit: string;
    income_by_category: Record<string, string>;
    expenses_by_category: Record<string, string>;
    currency: string;
  }>(`/school-finance/profit-and-loss?start=${start}&end=${end}`);
  return {
    start: wire.start,
    end: wire.end,
    studentRevenue: wire.student_revenue,
    otherIncome: wire.other_income,
    totalIncome: wire.total_income,
    totalExpenses: wire.total_expenses,
    netProfit: wire.net_profit,
    incomeByCategory: wire.income_by_category,
    expensesByCategory: wire.expenses_by_category,
    currency: wire.currency,
  };
}

export async function listStudentInvoices(
  params: OffsetListParams,
): Promise<OffsetPage<StudentInvoice>> {
  const wire = await apiRequest<OffsetPageWire<StudentInvoiceWire>>(
    `/school-finance/student-invoices?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toStudentInvoice);
}

export async function listStudentPayments(
  params: OffsetListParams,
): Promise<OffsetPage<StudentPayment>> {
  const wire = await apiRequest<OffsetPageWire<StudentPaymentWire>>(
    `/school-finance/student-payments?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toStudentPayment);
}

export async function listFeePlans(params: OffsetListParams): Promise<OffsetPage<FeePlan>> {
  const wire = await apiRequest<OffsetPageWire<FeePlanWire>>(
    `/school-finance/fee-plans?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toFeePlan);
}

export async function listCategories(
  params: OffsetListParams,
): Promise<OffsetPage<FinancialCategory>> {
  const wire = await apiRequest<OffsetPageWire<CategoryWire>>(
    `/school-finance/categories?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toCategory);
}

export async function listIncome(params: OffsetListParams): Promise<OffsetPage<LedgerEntry>> {
  const wire = await apiRequest<OffsetPageWire<LedgerWire>>(
    `/school-finance/income?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toLedgerEntry);
}

export async function listExpenses(params: OffsetListParams): Promise<OffsetPage<LedgerEntry>> {
  const wire = await apiRequest<OffsetPageWire<LedgerWire>>(
    `/school-finance/expenses?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toLedgerEntry);
}

export async function listInvoicesForVehicle(
  vehicleId: string,
  period?: string,
): Promise<StudentInvoice[]> {
  const qs = period ? `?period=${encodeURIComponent(period)}` : "";
  const wire = await apiRequest<StudentInvoiceWire[]>(
    `/school-finance/vehicles/${encodeURIComponent(vehicleId)}/invoices${qs}`,
  );
  return wire.map(toStudentInvoice);
}

/* ---- Writes ------------------------------------------------------------------------------- */

export interface IssueStudentInvoiceInput {
  studentId: string;
  period: string;
  dueDate: string;
  feePlanId?: string | null;
  amount?: string | null;
  currency?: string | null;
  discountAmount?: string | null;
  notes?: string | null;
}

export async function issueStudentInvoice(
  input: IssueStudentInvoiceInput,
): Promise<StudentInvoice> {
  const wire = await apiRequest<StudentInvoiceWire>("/school-finance/student-invoices", {
    method: "POST",
    body: {
      student_id: input.studentId,
      period: input.period,
      due_date: input.dueDate,
      fee_plan_id: input.feePlanId ?? null,
      amount: input.amount ?? null,
      currency: input.currency ?? null,
      discount_amount: input.discountAmount ?? null,
      notes: input.notes ?? null,
    },
  });
  return toStudentInvoice(wire);
}

export async function generateStudentInvoices(input: {
  period: string;
  dueDate: string;
  feePlanId: string;
  studentIds: string[];
}): Promise<StudentInvoice[]> {
  const wire = await apiRequest<StudentInvoiceWire[]>(
    "/school-finance/student-invoices/generate",
    {
      method: "POST",
      body: {
        period: input.period,
        due_date: input.dueDate,
        fee_plan_id: input.feePlanId,
        student_ids: input.studentIds,
      },
    },
  );
  return wire.map(toStudentInvoice);
}

export async function cancelStudentInvoice(
  invoiceId: string,
  reason?: string | null,
): Promise<StudentInvoice> {
  const wire = await apiRequest<StudentInvoiceWire>(
    `/school-finance/student-invoices/${encodeURIComponent(invoiceId)}/cancel`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toStudentInvoice(wire);
}

export async function recordStudentPayment(
  invoiceId: string,
  input: {
    amount: string;
    currency: string;
    method: StudentPaymentMethod;
    receivedOn: string;
    reference?: string | null;
    notes?: string | null;
  },
): Promise<StudentPayment> {
  const wire = await apiRequest<StudentPaymentWire>(
    `/school-finance/student-invoices/${encodeURIComponent(invoiceId)}/payments`,
    {
      method: "POST",
      body: {
        amount: input.amount,
        currency: input.currency,
        method: input.method,
        received_on: input.receivedOn,
        reference: input.reference ?? null,
        notes: input.notes ?? null,
      },
    },
  );
  return toStudentPayment(wire);
}

export async function createFeePlan(input: {
  name: string;
  amount: string;
  currency: string;
  defaultDiscountAmount?: string;
  description?: string | null;
}): Promise<FeePlan> {
  const wire = await apiRequest<FeePlanWire>("/school-finance/fee-plans", {
    method: "POST",
    body: {
      name: input.name,
      amount: input.amount,
      currency: input.currency,
      default_discount_amount: input.defaultDiscountAmount ?? "0.00",
      description: input.description ?? null,
    },
  });
  return toFeePlan(wire);
}

export async function updateFeePlan(
  feePlanId: string,
  input: {
    name: string;
    amount: string;
    currency: string;
    defaultDiscountAmount?: string;
    description?: string | null;
  },
): Promise<FeePlan> {
  const wire = await apiRequest<FeePlanWire>(
    `/school-finance/fee-plans/${encodeURIComponent(feePlanId)}`,
    {
      method: "PATCH",
      body: {
        name: input.name,
        amount: input.amount,
        currency: input.currency,
        default_discount_amount: input.defaultDiscountAmount ?? "0.00",
        description: input.description ?? null,
      },
    },
  );
  return toFeePlan(wire);
}

export async function archiveFeePlan(feePlanId: string): Promise<FeePlan> {
  const wire = await apiRequest<FeePlanWire>(
    `/school-finance/fee-plans/${encodeURIComponent(feePlanId)}/archive`,
    { method: "POST" },
  );
  return toFeePlan(wire);
}

export async function createCategory(input: {
  name: string;
  kind: CategoryKind;
  parentCategoryId?: string | null;
  description?: string | null;
}): Promise<FinancialCategory> {
  const wire = await apiRequest<CategoryWire>("/school-finance/categories", {
    method: "POST",
    body: {
      name: input.name,
      kind: input.kind,
      parent_category_id: input.parentCategoryId ?? null,
      description: input.description ?? null,
    },
  });
  return toCategory(wire);
}

export async function updateCategory(
  categoryId: string,
  input: { name: string; description?: string | null },
): Promise<FinancialCategory> {
  const wire = await apiRequest<CategoryWire>(
    `/school-finance/categories/${encodeURIComponent(categoryId)}`,
    {
      method: "PATCH",
      body: {
        name: input.name,
        description: input.description ?? null,
      },
    },
  );
  return toCategory(wire);
}

export async function archiveCategory(categoryId: string): Promise<FinancialCategory> {
  const wire = await apiRequest<CategoryWire>(
    `/school-finance/categories/${encodeURIComponent(categoryId)}/archive`,
    { method: "POST" },
  );
  return toCategory(wire);
}

export async function voidStudentPayment(
  paymentId: string,
  reason: string | null,
): Promise<StudentPayment> {
  const wire = await apiRequest<StudentPaymentWire>(
    `/school-finance/student-payments/${encodeURIComponent(paymentId)}/void`,
    { method: "POST", body: { reason } },
  );
  return toStudentPayment(wire);
}

export async function recordExpense(input: {
  amount: string;
  currency: string;
  occurredOn: string;
  categoryId?: string | null;
  description?: string | null;
  reference?: string | null;
  vehicleId?: string | null;
}): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>("/school-finance/expenses", {
    method: "POST",
    body: {
      amount: input.amount,
      currency: input.currency,
      occurred_on: input.occurredOn,
      category_id: input.categoryId ?? null,
      description: input.description ?? null,
      reference: input.reference ?? null,
      vehicle_id: input.vehicleId ?? null,
    },
  });
  return toLedgerEntry(wire);
}

export async function voidIncome(
  incomeId: string,
  reason?: string | null,
): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>(
    `/school-finance/income/${encodeURIComponent(incomeId)}/void`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toLedgerEntry(wire);
}

export async function voidExpense(
  expenseId: string,
  reason?: string | null,
): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>(
    `/school-finance/expenses/${encodeURIComponent(expenseId)}/void`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toLedgerEntry(wire);
}

export async function recordIncome(input: {
  amount: string;
  currency: string;
  occurredOn: string;
  categoryId?: string | null;
  description?: string | null;
  reference?: string | null;
}): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>("/school-finance/income", {
    method: "POST",
    body: {
      amount: input.amount,
      currency: input.currency,
      occurred_on: input.occurredOn,
      category_id: input.categoryId ?? null,
      description: input.description ?? null,
      reference: input.reference ?? null,
    },
  });
  return toLedgerEntry(wire);
}

/* ---- Cross-context lookups ---------------------------------------------------------------- */

/**
 * Student and vehicle names for the finance surfaces.
 *
 * **Why this module reads `/students` and `/vehicles` itself.** A `StudentInvoice` carries
 * `student_id`/`vehicle_id` and nothing else — deliberately: ADR-0040 §3 denormalises the *ids*
 * onto the bill at issue time so the record stays historically true, and
 * `.claude/rules/backend.md` #3 forbids `school_erp` joining another module's tables to fetch
 * their names. So the display name has to be resolved client-side, and it is resolved here
 * rather than by importing another feature's `api.ts` — the same shape
 * `fleet-devices/devices/api.ts` already uses for its own `listVehiclesForPicker` against
 * `/vehicles`.
 *
 * These are lookup *maps*, fetched once per page and cached, not a request per row: a hundred
 * invoices must not become a hundred name lookups.
 */
export interface NamedOption {
  id: string;
  label: string;
}

interface StudentPickerWire {
  id: string;
  full_name: string;
  status: string;
}

export async function listStudentsForPicker(search = ""): Promise<NamedOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "full_name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<StudentPickerWire>>(`/students?${query}`);
  return wire.data.map((student) => ({ id: student.id, label: student.full_name }));
}

interface VehiclePickerWire {
  id: string;
  plate_no: string;
  label: string | null;
}

export async function listVehiclesForPicker(search = ""): Promise<NamedOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters: {},
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehiclePickerWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({
    id: vehicle.id,
    label: vehicle.label ? `${vehicle.plate_no} · ${vehicle.label}` : vehicle.plate_no,
  }));
}

/** Turns a lookup list into an id→label map, with the raw id as the honest fallback. */
export function toLabelMap(options: NamedOption[] | undefined): Map<string, string> {
  return new Map((options ?? []).map((option) => [option.id, option.label]));
}

/* ---- Formatting helpers ------------------------------------------------------------------- */

/**
 * Formats a backend decimal string as currency.
 *
 * Takes the string, never a `number`, so the value that reaches `Intl.NumberFormat` is the exact
 * one the server sent. `Number()` here is safe because it is the *last* step before display —
 * the danger is arithmetic on floats, not rendering one.
 */
export function formatAmount(amount: string, currency: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(value);
  } catch {
    return `${amount} ${currency}`;
  }
}

/** The current month as `YYYY-MM`, the period shape every school-finance endpoint accepts. */
export function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
