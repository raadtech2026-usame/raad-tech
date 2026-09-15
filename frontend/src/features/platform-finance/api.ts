import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/**
 * `platform_finance` (C12) — the Vendor/Employee → RAAD money flow (ADR-0040 §1).
 *
 * RAAD's own operating costs and non-subscription income. This is the third and last financial
 * domain, and it is neither of the other two:
 *
 *     billing          RAAD   → Organization   (SaaS revenue)
 *     school_erp       Org    → Student        (school finance)
 *     platform_finance Vendor → RAAD           (operating cost)   ← this file
 *
 * **Only `founder` and `finance_staff` can reach any of these endpoints.** These tables carry no
 * `organization_id`, so there is no tenant scope to fall back on — RBAC is the entire gate, and
 * no `org_admin` grant exists in the namespace at all.
 *
 * **Subscription revenue is never posted here.** It belongs to `billing` and the platform P&L
 * *reads* it from there; recording it in this module too would double-count the same payments.
 * `PlatformIncomeKind` therefore has no `subscription` member on the write side.
 */

export type ExpenseKind =
  | "salaries"
  | "rent"
  | "electricity"
  | "water"
  | "internet"
  | "equipment"
  | "maintenance"
  | "fuel"
  | "marketing"
  | "travel"
  | "software"
  | "professional_fees"
  | "taxes"
  | "other";

export type PlatformIncomeKind =
  | "hardware_sale"
  | "installation"
  | "support_contract"
  | "grant"
  | "other";

export interface PlatformExpense {
  id: string;
  kind: ExpenseKind;
  categoryId: string | null;
  amount: string;
  currency: string;
  occurredOn: string;
  description: string | null;
  vendor: string | null;
  reference: string | null;
  isVoided: boolean;
}

export interface PlatformIncome {
  id: string;
  kind: string;
  categoryId: string | null;
  amount: string;
  currency: string;
  occurredOn: string;
  description: string | null;
  source: string | null;
  reference: string | null;
  isVoided: boolean;
}

export type PlatformCategoryKind = "income" | "expense";

export interface PlatformCategory {
  id: string;
  name: string;
  kind: PlatformCategoryKind;
  description: string | null;
  status: "active" | "inactive";
}

export interface PlatformPnl {
  start: string;
  end: string;
  subscriptionRevenue: string;
  /** Organization Management phase. What `billing` invoiced organizations in this window
   * (`subscription_invoiced`) — distinct from `subscriptionRevenue`, which is only what was
   * actually *collected*. Never merged with it: the gap between the two is receivables. */
  subscriptionInvoiced: string;
  /** As-of-`end` outstanding balance across every organization's subscription invoices
   * (`subscription_receivables`) — a point-in-time snapshot, not itself windowed by `start`. */
  subscriptionReceivables: string;
  otherIncome: string;
  totalRevenue: string;
  totalExpenses: string;
  netProfit: string;
  expensesByKind: Record<string, string>;
  incomeByKind: Record<string, string>;
  currency: string;
}

interface ExpenseWire {
  id: string;
  kind: string;
  category_id: string | null;
  amount: string;
  currency: string;
  occurred_on: string;
  description: string | null;
  vendor: string | null;
  reference: string | null;
  is_voided: boolean;
}

interface IncomeWire {
  id: string;
  kind: string;
  category_id: string | null;
  amount: string;
  currency: string;
  occurred_on: string;
  description: string | null;
  source: string | null;
  reference: string | null;
  is_voided: boolean;
}

function toExpense(w: ExpenseWire): PlatformExpense {
  return {
    id: w.id,
    kind: w.kind as ExpenseKind,
    categoryId: w.category_id,
    amount: w.amount,
    currency: w.currency,
    occurredOn: w.occurred_on,
    description: w.description,
    vendor: w.vendor,
    reference: w.reference,
    isVoided: w.is_voided,
  };
}

function toIncome(w: IncomeWire): PlatformIncome {
  return {
    id: w.id,
    kind: w.kind,
    categoryId: w.category_id,
    amount: w.amount,
    currency: w.currency,
    occurredOn: w.occurred_on,
    description: w.description,
    source: w.source,
    reference: w.reference,
    isVoided: w.is_voided,
  };
}

interface PlatformCategoryWire {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  status: string;
}

function toPlatformCategory(w: PlatformCategoryWire): PlatformCategory {
  return {
    id: w.id,
    name: w.name,
    kind: w.kind as PlatformCategoryKind,
    description: w.description,
    status: w.status as PlatformCategory["status"],
  };
}

/** No pagination on the wire — the backend returns the full list (`GET /platform-finance/
 * categories`), matching how few categories a RAAD-internal ledger realistically has. */
export async function listPlatformCategories(): Promise<PlatformCategory[]> {
  const wire = await apiRequest<PlatformCategoryWire[]>("/platform-finance/categories");
  return wire.map(toPlatformCategory);
}

export async function createPlatformCategory(input: {
  name: string;
  kind: PlatformCategoryKind;
  description?: string | null;
}): Promise<PlatformCategory> {
  const wire = await apiRequest<PlatformCategoryWire>("/platform-finance/categories", {
    method: "POST",
    body: {
      name: input.name,
      kind: input.kind,
      description: input.description ?? null,
    },
  });
  return toPlatformCategory(wire);
}

export async function voidPlatformExpense(
  expenseId: string,
  reason?: string | null,
): Promise<PlatformExpense> {
  const wire = await apiRequest<ExpenseWire>(
    `/platform-finance/expenses/${encodeURIComponent(expenseId)}/void`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toExpense(wire);
}

export async function voidPlatformIncome(
  incomeId: string,
  reason?: string | null,
): Promise<PlatformIncome> {
  const wire = await apiRequest<IncomeWire>(
    `/platform-finance/income/${encodeURIComponent(incomeId)}/void`,
    { method: "POST", body: { reason: reason ?? null } },
  );
  return toIncome(wire);
}

export async function listPlatformExpenses(
  params: OffsetListParams,
): Promise<OffsetPage<PlatformExpense>> {
  const wire = await apiRequest<OffsetPageWire<ExpenseWire>>(
    `/platform-finance/expenses?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toExpense);
}

export async function listPlatformIncome(
  params: OffsetListParams,
): Promise<OffsetPage<PlatformIncome>> {
  const wire = await apiRequest<OffsetPageWire<IncomeWire>>(
    `/platform-finance/income?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toIncome);
}

export async function getPlatformPnl(start: string, end: string): Promise<PlatformPnl> {
  const wire = await apiRequest<{
    start: string;
    end: string;
    subscription_revenue: string;
    subscription_invoiced: string;
    subscription_receivables: string;
    other_income: string;
    total_revenue: string;
    total_expenses: string;
    net_profit: string;
    expenses_by_kind: Record<string, string>;
    income_by_kind: Record<string, string>;
    currency: string;
  }>(`/platform-finance/profit-and-loss?start=${start}&end=${end}`);
  return {
    start: wire.start,
    end: wire.end,
    subscriptionRevenue: wire.subscription_revenue,
    subscriptionInvoiced: wire.subscription_invoiced,
    subscriptionReceivables: wire.subscription_receivables,
    otherIncome: wire.other_income,
    totalRevenue: wire.total_revenue,
    totalExpenses: wire.total_expenses,
    netProfit: wire.net_profit,
    expensesByKind: wire.expenses_by_kind,
    incomeByKind: wire.income_by_kind,
    currency: wire.currency,
  };
}

export async function recordPlatformExpense(input: {
  kind: ExpenseKind;
  amount: string;
  currency: string;
  occurredOn: string;
  vendor?: string | null;
  description?: string | null;
  reference?: string | null;
  categoryId?: string | null;
}): Promise<PlatformExpense> {
  const wire = await apiRequest<ExpenseWire>("/platform-finance/expenses", {
    method: "POST",
    body: {
      kind: input.kind,
      amount: input.amount,
      currency: input.currency,
      occurred_on: input.occurredOn,
      vendor: input.vendor ?? null,
      description: input.description ?? null,
      reference: input.reference ?? null,
      category_id: input.categoryId ?? null,
    },
  });
  return toExpense(wire);
}

export async function recordPlatformIncome(input: {
  kind: PlatformIncomeKind;
  amount: string;
  currency: string;
  occurredOn: string;
  source?: string | null;
  description?: string | null;
  reference?: string | null;
  categoryId?: string | null;
}): Promise<PlatformIncome> {
  const wire = await apiRequest<IncomeWire>("/platform-finance/income", {
    method: "POST",
    body: {
      kind: input.kind,
      amount: input.amount,
      currency: input.currency,
      occurred_on: input.occurredOn,
      source: input.source ?? null,
      description: input.description ?? null,
      reference: input.reference ?? null,
      category_id: input.categoryId ?? null,
    },
  });
  return toIncome(wire);
}

/** Human label for an expense heading — `professional_fees` → "Professional fees". */
export function expenseKindLabel(kind: string): string {
  const spaced = kind.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
