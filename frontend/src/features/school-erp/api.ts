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

/** ADR-0047 §6 — `daily_vehicle` is one bus's collection on one day; `other` is any other
 * income. Student income is never a ledger entry: it comes from recorded parent payments. */
export type IncomeType = "daily_vehicle" | "other";

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
  /** Income entries only. */
  incomeType?: IncomeType;
  isVoided: boolean;
  /** Why the entry was voided; null for live entries and for voids recorded before reasons were stored. */
  voidedReason: string | null;
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

/** One bus for a date window (ADR-0047 §7). Three income sources, never one unexplained total. */
export interface VehicleFinance {
  /** `null` = student money from invoices generated before the student had a bus. */
  vehicleId: string | null;
  studentCount: number;
  billedAmount: string;
  outstandingAmount: string;
  studentIncome: string;
  dailyIncome: string;
  otherIncome: string;
  totalIncome: string;
  expenseAmount: string;
  netAmount: string;
  currency: string;
}

export interface VehicleFinanceReport {
  vehicleId: string;
  start: string;
  end: string;
  currency: string;
  studentIncome: string;
  dailyIncome: string;
  otherIncome: string;
  totalIncome: string;
  totalExpenses: string;
  netAmount: string;
  billedAmount: string;
  outstandingAmount: string;
  incomeByStudent: { studentId: string; fullName: string; parentId: string; parentName: string; amount: string }[];
  incomeByParent: { parentId: string; fullName: string; amount: string }[];
  dailyEntries: LedgerEntry[];
  otherEntries: LedgerEntry[];
  /** Keyed by category id; `""` holds uncategorised expenses. */
  expensesByCategory: Record<string, string>;
  expenseEntries: LedgerEntry[];
}

export interface ProfitAndLoss {
  start: string;
  end: string;
  /** Student income: allocations of payments received in the window (cash basis). */
  studentRevenue: string;
  dailyVehicleIncome: string;
  otherIncome: string;
  totalIncome: string;
  totalExpenses: string;
  netProfit: string;
  incomeByCategory: Record<string, string>;
  expensesByCategory: Record<string, string>;
  currency: string;
}

/* ---- Wire shapes (snake_case, exactly as the backend serialises them) --------------------- */

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
  income_type?: string;
  is_voided: boolean;
  voided_reason: string | null;
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
    incomeType: w.income_type as IncomeType | undefined,
    isVoided: w.is_voided,
    voidedReason: w.voided_reason ?? null,
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

interface VehicleFinanceWire {
  vehicle_id: string | null;
  student_count: number;
  billed_amount: string;
  outstanding_amount: string;
  student_income: string;
  daily_income: string;
  other_income: string;
  total_income: string;
  expense_amount: string;
  net_amount: string;
  currency: string;
}

/** `GET /school-finance/vehicles?start&end` — every bus's income by source, cost and net. */
export async function listVehicleFinance(start: string, end: string): Promise<VehicleFinance[]> {
  const wire = await apiRequest<VehicleFinanceWire[]>(
    `/school-finance/vehicles?start=${start}&end=${end}`,
  );
  return wire.map((v) => ({
    vehicleId: v.vehicle_id,
    studentCount: v.student_count,
    billedAmount: v.billed_amount,
    outstandingAmount: v.outstanding_amount,
    studentIncome: v.student_income,
    dailyIncome: v.daily_income,
    otherIncome: v.other_income,
    totalIncome: v.total_income,
    expenseAmount: v.expense_amount,
    netAmount: v.net_amount,
    currency: v.currency,
  }));
}

/** `GET /school-finance/vehicles/{id}/report?start&end` — one bus, with the rows behind each figure. */
export async function getVehicleFinanceReport(
  vehicleId: string,
  start: string,
  end: string,
): Promise<VehicleFinanceReport> {
  const w = await apiRequest<{
    vehicle_id: string;
    start: string;
    end: string;
    currency: string;
    student_income: string;
    daily_income: string;
    other_income: string;
    total_income: string;
    total_expenses: string;
    net_amount: string;
    billed_amount: string;
    outstanding_amount: string;
    income_by_student: { student_id: string; full_name: string; parent_id: string; parent_name: string; amount: string }[];
    income_by_parent: { parent_id: string; full_name: string; amount: string }[];
    daily_entries: LedgerWire[];
    other_entries: LedgerWire[];
    expenses_by_category: Record<string, string>;
    expense_entries: LedgerWire[];
  }>(`/school-finance/vehicles/${encodeURIComponent(vehicleId)}/report?start=${start}&end=${end}`);
  return {
    vehicleId: w.vehicle_id,
    start: w.start,
    end: w.end,
    currency: w.currency,
    studentIncome: w.student_income,
    dailyIncome: w.daily_income,
    otherIncome: w.other_income,
    totalIncome: w.total_income,
    totalExpenses: w.total_expenses,
    netAmount: w.net_amount,
    billedAmount: w.billed_amount,
    outstandingAmount: w.outstanding_amount,
    incomeByStudent: w.income_by_student.map((r) => ({
      studentId: r.student_id,
      fullName: r.full_name,
      parentId: r.parent_id,
      parentName: r.parent_name,
      amount: r.amount,
    })),
    incomeByParent: w.income_by_parent.map((r) => ({ parentId: r.parent_id, fullName: r.full_name, amount: r.amount })),
    dailyEntries: w.daily_entries.map(toLedgerEntry),
    otherEntries: w.other_entries.map(toLedgerEntry),
    expensesByCategory: w.expenses_by_category,
    expenseEntries: w.expense_entries.map(toLedgerEntry),
  };
}

export async function getProfitAndLoss(start: string, end: string): Promise<ProfitAndLoss> {
  const wire = await apiRequest<{
    start: string;
    end: string;
    student_revenue: string;
    daily_vehicle_income: string;
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
    dailyVehicleIncome: wire.daily_vehicle_income,
    otherIncome: wire.other_income,
    totalIncome: wire.total_income,
    totalExpenses: wire.total_expenses,
    netProfit: wire.net_profit,
    incomeByCategory: wire.income_by_category,
    expensesByCategory: wire.expenses_by_category,
    currency: wire.currency,
  };
}

/** Legacy per-student invoices (before ADR-0042, 2026-09-11) — read-only history, used by the
 * platform Organization Details page. New billing is Parent Invoices. */
export async function listStudentInvoices(
  params: OffsetListParams,
): Promise<OffsetPage<StudentInvoice>> {
  const wire = await apiRequest<OffsetPageWire<StudentInvoiceWire>>(
    `/school-finance/student-invoices?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toStudentInvoice);
}

/** Legacy per-student payments — read-only history, see `listStudentInvoices`. */
export async function listStudentPayments(
  params: OffsetListParams,
): Promise<OffsetPage<StudentPayment>> {
  const wire = await apiRequest<OffsetPageWire<StudentPaymentWire>>(
    `/school-finance/student-payments?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toStudentPayment);
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

/* ---- Writes ------------------------------------------------------------------------------- */

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
  reason: string,
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
  reason: string,
): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>(
    `/school-finance/income/${encodeURIComponent(incomeId)}/void`,
    { method: "POST", body: { reason } },
  );
  return toLedgerEntry(wire);
}

export async function voidExpense(
  expenseId: string,
  reason: string,
): Promise<LedgerEntry> {
  const wire = await apiRequest<LedgerWire>(
    `/school-finance/expenses/${encodeURIComponent(expenseId)}/void`,
    { method: "POST", body: { reason } },
  );
  return toLedgerEntry(wire);
}

export async function recordIncome(input: {
  amount: string;
  currency: string;
  occurredOn: string;
  incomeType: IncomeType;
  vehicleId?: string | null;
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
      income_type: input.incomeType,
      vehicle_id: input.vehicleId ?? null,
      category_id: input.categoryId ?? null,
      description: input.description ?? null,
      reference: input.reference ?? null,
    },
  });
  return toLedgerEntry(wire);
}

/* ---- Student-level finance (ADR-0047 §2) ------------------------------------------------- */

export interface StudentCharge {
  invoiceId: string;
  invoiceNumber: string;
  lineId: string;
  period: string;
  parentId: string;
  parentName: string;
  amount: string;
  amountPaid: string;
  balanceDue: string;
  invoiceStatus: "unpaid" | "partial" | "paid" | "cancelled";
  dueDate: string;
  vehicleId: string | null;
  currency: string;
}

export interface StudentPaymentEntry {
  paymentId: string;
  invoiceId: string;
  invoiceNumber: string;
  period: string;
  receivedOn: string;
  method: StudentPaymentMethod;
  reference: string | null;
  /** The part of the family payment allocated to this student. */
  amount: string;
  paymentTotal: string;
  currency: string;
  isVoided: boolean;
  voidedReason: string | null;
}

export interface StudentFinance {
  studentId: string;
  fullName: string;
  status: string;
  parents: { parentId: string; fullName: string; isPrimary: boolean }[];
  currency: string;
  totalCharged: string;
  totalPaid: string;
  balanceDue: string;
  charges: StudentCharge[];
  payments: StudentPaymentEntry[];
  /** Pre-2026-09-11 per-student invoices — read-only history, never added to the totals. */
  legacyInvoices: StudentInvoice[];
  legacyPayments: StudentPayment[];
}

/** `GET /school-finance/students/{id}/finance` — one student's charges, payments and balance. */
export async function getStudentFinance(studentId: string): Promise<StudentFinance> {
  const w = await apiRequest<{
    student_id: string;
    full_name: string;
    status: string;
    parents: { parent_id: string; full_name: string; is_primary: boolean }[];
    currency: string;
    total_charged: string;
    total_paid: string;
    balance_due: string;
    charges: {
      invoice_id: string;
      invoice_number: string;
      line_id: string;
      period: string;
      parent_id: string;
      parent_name: string;
      amount: string;
      amount_paid: string;
      balance_due: string;
      invoice_status: string;
      due_date: string;
      vehicle_id: string | null;
      currency: string;
    }[];
    payments: {
      payment_id: string;
      invoice_id: string;
      invoice_number: string;
      period: string;
      received_on: string;
      method: string;
      reference: string | null;
      amount: string;
      payment_total: string;
      currency: string;
      is_voided: boolean;
      voided_reason: string | null;
    }[];
    legacy_invoices: StudentInvoiceWire[];
    legacy_payments: StudentPaymentWire[];
  }>(`/school-finance/students/${encodeURIComponent(studentId)}/finance`);
  return {
    studentId: w.student_id,
    fullName: w.full_name,
    status: w.status,
    parents: w.parents.map((p) => ({ parentId: p.parent_id, fullName: p.full_name, isPrimary: p.is_primary })),
    currency: w.currency,
    totalCharged: w.total_charged,
    totalPaid: w.total_paid,
    balanceDue: w.balance_due,
    charges: w.charges.map((c) => ({
      invoiceId: c.invoice_id,
      invoiceNumber: c.invoice_number,
      lineId: c.line_id,
      period: c.period,
      parentId: c.parent_id,
      parentName: c.parent_name,
      amount: c.amount,
      amountPaid: c.amount_paid,
      balanceDue: c.balance_due,
      invoiceStatus: c.invoice_status as StudentCharge["invoiceStatus"],
      dueDate: c.due_date,
      vehicleId: c.vehicle_id,
      currency: c.currency,
    })),
    payments: w.payments.map((p) => ({
      paymentId: p.payment_id,
      invoiceId: p.invoice_id,
      invoiceNumber: p.invoice_number,
      period: p.period,
      receivedOn: p.received_on,
      method: p.method as StudentPaymentMethod,
      reference: p.reference,
      amount: p.amount,
      paymentTotal: p.payment_total,
      currency: p.currency,
      isVoided: p.is_voided,
      voidedReason: p.voided_reason,
    })),
    legacyInvoices: w.legacy_invoices.map(toStudentInvoice),
    legacyPayments: w.legacy_payments.map(toStudentPayment),
  };
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
