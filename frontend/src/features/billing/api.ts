import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../shared/api/listParams";
import { ApiError, toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../shared/api/types";

/** `billing.domain.value_objects.BillingScope` — ADR-0016 removed the `parent` value (RAAD
 * bills Organizations only now), leaving one active value, kept as a "documented seam for future
 * variants" rather than eliminated outright (that value object's own docstring). */
export type BillingScope = "organization";

/** `billing.domain.value_objects.BillingCycle`. */
export type BillingCycle = "monthly" | "quarterly" | "annual";

/** `billing.domain.value_objects.PlanStatus` — Database Design §8.1 names the column but not
 * its values; a flat active/inactive toggle, mirroring `ParentStatus`'s identical precedent. */
export type PlanStatus = "active" | "inactive";

/** `billing.domain.value_objects.SubscriptionStatus` — Database Design §8.2's original five
 * plus the two ADR-0039 adds for a real recurring-billing lifecycle. `past_due` is automatic (the
 * period ended unpaid and the standard window is running); `grace_period` is granted (a platform
 * admin explicitly extended it). They are deliberately distinct states, not synonyms. */
export type SubscriptionStatus =
  | "trial"
  | "active"
  | "past_due"
  | "grace_period"
  | "suspended"
  | "expired"
  | "cancelled";

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
  /** Included allowances. All three are `null` for "unlimited" — ADR-0040 §4 added
   * `deviceLimit`/`userLimit` alongside the pre-existing `vehicleLimit`. */
  vehicleLimit: number | null;
  deviceLimit: number | null;
  userLimit: number | null;
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
  device_limit: number | null;
  user_limit: number | null;
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
    // `?? null` rather than a bare read: a response predating ADR-0040's additive migration
    // omits both keys, and `undefined` would break the `number | null` contract downstream.
    deviceLimit: wire.device_limit ?? null,
    userLimit: wire.user_limit ?? null,
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

/* ---- Plan catalogue writes (ADR-0040 §4) --------------------------------------------------
 *
 * Founder-only, behind `billing.plans.manage` — deliberately distinct from the read-only
 * `billing.plans.list` five roles hold, because changing what RAAD charges is materially more
 * sensitive than reading the price list.
 *
 * **Monthly and annual are separate plan rows sharing a name**, not two prices on one row:
 * `billingCycle` drives every period date a subscription computes, so one row carrying both
 * would make "which amount applies" ambiguous at invoice-issue time. The catalogue UI groups by
 * name to present them as one commercial tier.
 *
 * Editing a plan never retro-changes an already-issued invoice — invoices capture their own
 * amount at issue time — so there is no "apply to existing subscriptions" affordance to offer.
 */

export interface PlanInput {
  name: string;
  amount: number;
  currency: string;
  vehicleLimit: number | null;
  deviceLimit: number | null;
  userLimit: number | null;
}

export async function createPlan(
  input: PlanInput & { billingCycle: BillingCycle },
): Promise<Plan> {
  const wire = await apiRequest<PlanWire>("/billing/plans", {
    method: "POST",
    body: {
      name: input.name,
      billing_scope: "organization",
      amount: input.amount,
      currency: input.currency,
      billing_cycle: input.billingCycle,
      vehicle_limit: input.vehicleLimit,
      device_limit: input.deviceLimit,
      user_limit: input.userLimit,
    },
  });
  return toPlan(wire);
}

export async function updatePlan(planId: string, input: PlanInput): Promise<Plan> {
  const wire = await apiRequest<PlanWire>(`/billing/plans/${encodeURIComponent(planId)}`, {
    method: "PATCH",
    body: {
      name: input.name,
      amount: input.amount,
      currency: input.currency,
      vehicle_limit: input.vehicleLimit,
      device_limit: input.deviceLimit,
      user_limit: input.userLimit,
    },
  });
  return toPlan(wire);
}

export async function setPlanStatus(planId: string, active: boolean): Promise<Plan> {
  const wire = await apiRequest<PlanWire>(
    `/billing/plans/${encodeURIComponent(planId)}/${active ? "activate" : "disable"}`,
    { method: "POST" },
  );
  return toPlan(wire);
}

/** Active organization plans, for the onboarding picker. Small and cached — the catalogue is a
 * handful of rows, not a paginated list. */
export async function listActivePlansForPicker(): Promise<Plan[]> {
  const page = await listPlans({
    page: 1,
    pageSize: 100,
    sort: { field: "amount", direction: "asc" },
    filters: { status: "active", billing_scope: "organization" },
    search: "",
  });
  return page.data;
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
  /** ADR-0039 lifecycle timestamps. Optional on the wire: older responses omit them entirely,
   * so they are `null` rather than absent once mapped. */
  pastDueSince: string | null;
  gracePeriodEndsAt: string | null;
  suspendedAt: string | null;
  cancelledAt: string | null;
  expiredAt: string | null;
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
  past_due_since?: string | null;
  grace_period_ends_at?: string | null;
  suspended_at?: string | null;
  cancelled_at?: string | null;
  expired_at?: string | null;
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
    pastDueSince: wire.past_due_since ?? null,
    gracePeriodEndsAt: wire.grace_period_ends_at ?? null,
    suspendedAt: wire.suspended_at ?? null,
    cancelledAt: wire.cancelled_at ?? null,
    expiredAt: wire.expired_at ?? null,
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

/** `GET /billing/subscriptions/{id}` — uniform-CRUD addition backing the Founder's Subscription
 * Details page (2026-09-10). `list_subscriptions`/`get_subscription_by_id` share the same
 * `billing.subscriptions.list` permission and the same `toSubscription` wire mapping above — one
 * subscription read, not a second implementation of it. 404s (never 403s) for an unknown id: a
 * subscription id is not information worth hiding cross-tenant existence of, the same posture
 * every other by-id route in this API takes. */
export async function getSubscription(subscriptionId: string): Promise<Subscription> {
  const wire = await apiRequest<SubscriptionWire>(
    `/billing/subscriptions/${encodeURIComponent(subscriptionId)}`,
  );
  return toSubscription(wire);
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

/** `billing.domain.value_objects.PaymentStatus`. */
export type PaymentStatus = "pending" | "processing" | "paid" | "failed" | "expired";

export interface Payment {
  id: string;
  organizationId: string;
  invoiceId: string;
  provider: string;
  providerRef: string | null;
  amount: number;
  currency: string;
  status: PaymentStatus;
  failureReason: string | null;
  createdAt: string;
  confirmedAt: string | null;
}

interface PaymentWire {
  id: string;
  organization_id: string;
  invoice_id: string;
  provider: string;
  provider_ref: string | null;
  amount: number;
  currency: string;
  status: string;
  failure_reason: string | null;
  created_at: string;
  confirmed_at: string | null;
}

function toPayment(wire: PaymentWire): Payment {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    invoiceId: wire.invoice_id,
    provider: wire.provider,
    providerRef: wire.provider_ref,
    amount: wire.amount,
    currency: wire.currency,
    status: wire.status as PaymentStatus,
    failureReason: wire.failure_reason,
    createdAt: wire.created_at,
    confirmedAt: wire.confirmed_at,
  };
}

/** `GET /billing/payments` (ADR-0022 — "payment history," no prior list route existed).
 * Founder/Finance Staff/Org Admin (mirrors `listSubscriptions`'s grant set). Whitelist confirmed
 * against `SqlAlchemyPaymentRepository`: filterable `organization_id`/`invoice_id`/`status`,
 * sortable `amount`/`status`/`created_at`/`confirmed_at`, no searchable fields. */
export async function listPayments(params: OffsetListParams): Promise<OffsetPage<Payment>> {
  const wire = await apiRequest<OffsetPageWire<PaymentWire>>(`/billing/payments?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toPayment);
}

export interface InitiatePaymentInput {
  invoiceId: string;
  /** `Payment.provider` on the backend — e.g. `"stripe"`, matching the active
   * `billing_payment_provider` System Setting (see `getBillingProviderConfig` below). */
  method: string;
  amount: number;
  currency: string;
  /** A Stripe `PaymentMethod` id, tokenized client-side via Stripe Elements
   * (`stripe.createPaymentMethod`) — the raw card number never reaches this backend (ADR-0022,
   * PCI DSS SAQ A scope). */
  paymentMethodToken?: string;
  msisdn?: string;
}

export interface InitiatePaymentResult {
  paymentId: string;
  status: string;
}

/** `POST /billing/payments` (ADR-0022 — real now that a verified `StripePaymentAdapter` can be
 * bound; previously this had no client at all, since a bound provider didn't exist). Requires
 * `Idempotency-Key` (API rule #6, API Contracts §12) — generated fresh per call via
 * `crypto.randomUUID()` (the same convention `Toast`'s own id generation already uses), so a
 * genuine double-submit (e.g. a double click) before the first request resolves would still race
 * to two distinct keys; `ConfirmDialog`'s own loading state is what actually prevents that, this
 * header is the server-side backstop for network-level retries. */
export async function initiatePayment(input: InitiatePaymentInput): Promise<InitiatePaymentResult> {
  const wire = await apiRequest<{ payment_id: string; status: string }>("/billing/payments", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: {
      invoice_id: input.invoiceId,
      method: input.method,
      amount: input.amount,
      currency: input.currency,
      payment_method_token: input.paymentMethodToken,
      msisdn: input.msisdn,
    },
  });
  return { paymentId: wire.payment_id, status: wire.status };
}

interface SystemSettingWire {
  key: string;
  value: Record<string, unknown>;
  scope: string;
}

export interface BillingProviderConfig {
  /** `null` when no `PaymentProviderPort` is bound this deployment — `OrgBillingPage`'s "Pay
   * Invoice" flow renders an honest "not available yet" state rather than a control guaranteed
   * to fail, mirroring this same file's own established restraint before ADR-0022 existed. */
  provider: string | null;
}

/** `GET /admin/settings` (`platform_audit`, already gated by `admin.settings.read` — both
 * Founder and Org Admin hold it) — reads the one non-secret `billing_payment_provider` row
 * ADR-0022 seeds (`{"provider":"stripe"}`), so this page can ask "is online payment available"
 * without a new route. `key` is not a whitelisted filter server-side
 * (`SqlAlchemySystemSettingRepository.filterable_fields` only has `scope`), so this filters by
 * `scope=platform` and finds the row client-side, capped at the first 50 settings — the same
 * "capped at N, honest fallback" pattern `listOrganizationsForPicker` below already establishes.
 * Never returns a secret: the real provider credentials live only in the backend's own env vars,
 * never serialized into this response (ADR-0022's own explicit design). */
export async function getBillingProviderConfig(): Promise<BillingProviderConfig> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 50,
    sort: { field: "key", direction: "asc" },
    filters: { scope: "platform" },
    search: "",
  });
  const wire = await apiRequest<OffsetPageWire<SystemSettingWire>>(`/admin/settings?${query}`);
  const row = wire.data.find((item) => item.key === "billing_payment_provider");
  const provider = row?.value?.provider;
  return { provider: typeof provider === "string" ? provider : null };
}

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

// --- ADR-0039 subscription lifecycle ------------------------------------------------------------

/** `GET /billing/subscriptions/current` — the caller's OWN organization's subscription.
 *
 * Preferred over filtering `listSubscriptions` by `organization_id`: this route takes no path or
 * query id at all, so it is self-scoped by construction rather than by a filter a caller could
 * change. Returns `null` on 404, which is the honest answer for an organization that has never
 * had a subscription - not an error state the UI should surface as a failure. */
export async function getCurrentSubscription(): Promise<Subscription | null> {
  try {
    const wire = await apiRequest<SubscriptionWire>("/billing/subscriptions/current");
    return toSubscription(wire);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** `POST /billing/subscriptions/{id}/suspend` — platform-admin only
 * (`billing.subscriptions.manage`; org_admin does NOT hold it). */
export async function suspendSubscription(subscriptionId: string): Promise<Subscription> {
  const wire = await apiRequest<SubscriptionWire>(
    `/billing/subscriptions/${encodeURIComponent(subscriptionId)}/suspend`,
    { method: "POST" },
  );
  return toSubscription(wire);
}

/** `POST /billing/subscriptions/{id}/reactivate` — platform-admin only. */
export async function reactivateSubscription(subscriptionId: string): Promise<Subscription> {
  const wire = await apiRequest<SubscriptionWire>(
    `/billing/subscriptions/${encodeURIComponent(subscriptionId)}/reactivate`,
    { method: "POST" },
  );
  return toSubscription(wire);
}

/** `POST /billing/subscriptions/{id}/extend-grace` — platform-admin only.
 *
 * Takes an absolute instant, not a day count: the API owns interpreting the caller's intent, so
 * the deadline the domain records is unambiguous. Callers pass an ISO-8601 string. */
export async function extendGracePeriod(
  subscriptionId: string,
  gracePeriodEndsAt: string,
): Promise<Subscription> {
  const wire = await apiRequest<SubscriptionWire>(
    `/billing/subscriptions/${encodeURIComponent(subscriptionId)}/extend-grace`,
    { method: "POST", body: { grace_period_ends_at: gracePeriodEndsAt } },
  );
  return toSubscription(wire);
}
