import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/** `billing.domain.value_objects.BillingScope` — ADR-0016 removed the `parent` value (RAAD
 * bills Organizations only now), leaving one active value, kept as a "documented seam for future
 * variants" rather than eliminated outright (that value object's own docstring). */
export type BillingScope = "organization";

/** `billing.domain.value_objects.BillingCycle`. */
export type BillingCycle = "monthly" | "quarterly" | "annual";

/** `billing.domain.value_objects.PlanStatus` — Database Design §8.1 names the column but not
 * its values; a flat active/inactive toggle, mirroring `ParentStatus`'s identical precedent. */
export type PlanStatus = "active" | "inactive";

/** `billing.domain.value_objects.SubscriptionStatus`. */
export type SubscriptionStatus = "trial" | "active" | "suspended" | "expired" | "cancelled";

/** `billing.domain.value_objects.InvoiceStatus` — exhaustively four values, no `failed` member
 * (Database Design §8.3). */
export type InvoiceStatus = "draft" | "issued" | "paid" | "void";

export interface Plan {
  id: string;
  name: string;
  billingScope: BillingScope;
  amount: number;
  currency: string;
  billingCycle: BillingCycle;
  vehicleLimit: number | null;
  status: PlanStatus;
  createdAt: string;
  updatedAt: string;
}

interface PlanWire {
  id: string;
  name: string;
  billing_scope: string;
  amount: number;
  currency: string;
  billing_cycle: string;
  vehicle_limit: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function toPlan(wire: PlanWire): Plan {
  return {
    id: wire.id,
    name: wire.name,
    billingScope: wire.billing_scope as BillingScope,
    amount: wire.amount,
    currency: wire.currency,
    billingCycle: wire.billing_cycle as BillingCycle,
    vehicleLimit: wire.vehicle_limit,
    status: wire.status as PlanStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

/** `GET /billing/plans` — in-scope, no documented role restriction (API Contracts §4.7 line
 * 170); every role that can reach a billing page holds `billing.plans.list`. Whitelist confirmed
 * against `billing/infra/repositories.py`'s `SqlAlchemyPlanRepository`: filterable
 * `billing_scope`/`billing_cycle`/`status`/`currency`, sortable
 * `name`/`amount`/`status`/`created_at`/`updated_at`, searchable `name`. */
export async function listPlans(params: OffsetListParams): Promise<OffsetPage<Plan>> {
  const wire = await apiRequest<OffsetPageWire<PlanWire>>(`/billing/plans?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toPlan);
}

export interface Subscription {
  id: string;
  organizationId: string;
  planId: string;
  status: SubscriptionStatus;
  currentPeriodStart: string | null;
  currentPeriodEnd: string | null;
  autoRenew: boolean;
  createdAt: string;
  updatedAt: string;
}

interface SubscriptionWire {
  id: string;
  organization_id: string;
  plan_id: string;
  status: string;
  current_period_start: string | null;
  current_period_end: string | null;
  auto_renew: boolean;
  created_at: string;
  updated_at: string;
}

function toSubscription(wire: SubscriptionWire): Subscription {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    planId: wire.plan_id,
    status: wire.status as SubscriptionStatus,
    currentPeriodStart: wire.current_period_start,
    currentPeriodEnd: wire.current_period_end,
    autoRenew: wire.auto_renew,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

/** `GET /billing/subscriptions` — Org Admin/Finance; Parent(own) (API Contracts §4.7 line 171).
 * **Not yet scope-filtered server-side** — `list_subscriptions` reads every organization's
 * subscriptions regardless of caller (`billing/api/routers.py`'s own module docstring, the same
 * system-wide, already-flagged `ScopeResolver` gap every list endpoint in this codebase carries,
 * not billing-specific). Whitelist confirmed against `SqlAlchemySubscriptionRepository`:
 * filterable `organization_id`/`plan_id`/`status`, sortable
 * `status`/`current_period_start`/`current_period_end`/`created_at`/`updated_at`, **no
 * searchable fields** (no free-text label column on this resource). */
export async function listSubscriptions(params: OffsetListParams): Promise<OffsetPage<Subscription>> {
  const wire = await apiRequest<OffsetPageWire<SubscriptionWire>>(
    `/billing/subscriptions?${buildOffsetListQuery(params)}`,
  );
  return toOffsetPage(wire, toSubscription);
}

export interface Invoice {
  id: string;
  organizationId: string;
  subscriptionId: string;
  number: string;
  amount: number;
  currency: string;
  periodStart: string;
  periodEnd: string;
  status: InvoiceStatus;
  issuedAt: string | null;
  dueAt: string | null;
  paidAt: string | null;
  createdAt: string;
  updatedAt: string;
}

interface InvoiceWire {
  id: string;
  organization_id: string;
  subscription_id: string;
  number: string;
  amount: number;
  currency: string;
  period_start: string;
  period_end: string;
  status: string;
  issued_at: string | null;
  due_at: string | null;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
}

function toInvoice(wire: InvoiceWire): Invoice {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    subscriptionId: wire.subscription_id,
    number: wire.number,
    amount: wire.amount,
    currency: wire.currency,
    periodStart: wire.period_start,
    periodEnd: wire.period_end,
    status: wire.status as InvoiceStatus,
    issuedAt: wire.issued_at,
    dueAt: wire.due_at,
    paidAt: wire.paid_at,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

/** `GET /billing/invoices` — same role/scope posture as `listSubscriptions` above. Whitelist
 * confirmed against `SqlAlchemyInvoiceRepository`: filterable
 * `subscription_id`/`status`/`currency`/`period_start`/`period_end`, sortable
 * `number`/`amount`/`status`/`issued_at`/`due_at`/`paid_at`/`created_at`/`updated_at`,
 * searchable `number`. */
export async function listInvoices(params: OffsetListParams): Promise<OffsetPage<Invoice>> {
  const wire = await apiRequest<OffsetPageWire<InvoiceWire>>(`/billing/invoices?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toInvoice);
}

/** `POST /billing/payments` deliberately has no client here this phase. Confirmed by reading
 * `billing/api/routers.py`'s own module docstring before deciding, not assumed: with no
 * `PaymentProviderPort` bound, this route always persists a `PENDING` `Payment` row and then
 * raises `NotImplementedError` (500) at the charge step — a guaranteed failure on every call, by
 * design ("fail loudly, don't fake a charge"). Wiring a "Pay now" control to it would create a
 * real, permanently-`PENDING` row on every click while showing the user a broken action —
 * offering a control that's guaranteed to fail is the same anti-pattern this codebase's own
 * "fail loudly, don't fake it" posture already rules out for *data*, extended here to mean an
 * *affordance* too. Revisit once Known Issue #4 (a real payment-provider account) is resolved.
 * `POST /billing/payments/callback` is a provider-only webhook — never called from this UI. */
export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup backing this page's organization-name
 * resolution for Subscriptions/Invoices (neither response carries a name, only
 * `organization_id`) — this feature folder's own self-contained copy
 * (`.claude/rules/frontend.md` #1), matching every other feature's identical
 * `listOrganizationsForPicker` precedent. Capped at the first 100 organizations (by name); a
 * caller past that count falls back to the raw id rather than a fabricated name. */
export async function listOrganizationsForPicker(): Promise<OrganizationOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: {},
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<OrganizationOptionWire>>(`/organizations?${query}`);
  return wire.data.map((org) => ({ id: org.id, name: org.name }));
}
