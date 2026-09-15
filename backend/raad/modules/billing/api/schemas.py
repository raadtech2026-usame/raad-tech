"""HTTP request/response DTOs for `billing` (Backend LLD §16; API Contracts §4.7). Pydantic
models are transport-only — no business logic here; `routers.py` does the DTO<->application
translation. Mirrors `transport_ops.api.schemas`'s shape exactly.

Only the five documented `/billing/*` endpoints (API Contracts §4.7 lines 170-174) get a
request/response shape here — `Plan`/`Subscription` have no documented write routes at all (no
`POST/PATCH/DELETE /billing/plans` or `/billing/subscriptions` anywhere in §4.7's table).
**ADR-0040 §4 adds a plan-management surface anyway** — `CreatePlanRequest`/`UpdatePlanRequest`
below, Founder-only — because the ERP requires a real plan catalogue; `Subscription` still has no
create/update request shape here, its lifecycle being owned by ADR-0039's own routes and job. List responses use the same single-DTO shape `application/queries.py` already
committed to (no Summary/Full split — see that file's own docstring).

**`PaymentResponse` deliberately does not follow this module's `id` field-naming precedent.**
Every other response schema in this codebase uses a bare `id` field (`TripResponse.id`,
`StudentResponse.id`, ...). Here, API Contracts §4.7 gives a **literal, verbatim JSON response
sample** — `{ "payment_id":"01J...","status":"processing","required_action":
"AWAIT_PHONE_CONFIRMATION" }` — the only endpoint in the whole billing surface with a documented
response body at all. Following that literal sample over the codebase's inferred convention is
the more faithful choice here. **`required_action` is omitted** — no domain/application source
produces it (`PaymentDTO` has no such field; it is an EVC-Plus-adapter-specific hint that only a
real, connected payment gateway could compute, and no adapter exists this phase — flagged rather
than fabricated).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    id: str
    name: str
    billing_scope: str
    amount: float
    currency: str
    billing_cycle: str
    vehicle_limit: int | None
    device_limit: int | None
    user_limit: int | None
    status: str
    created_at: datetime
    updated_at: datetime


class SubscriptionResponse(BaseModel):
    id: str
    organization_id: str
    plan_id: str
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    auto_renew: bool
    created_at: datetime
    updated_at: datetime
    # ADR-0039 lifecycle timestamps. Optional with `None` defaults so this response model stays
    # backward-compatible for any existing client that does not know about them yet.
    past_due_since: datetime | None = None
    grace_period_ends_at: datetime | None = None
    suspended_at: datetime | None = None
    cancelled_at: datetime | None = None
    expired_at: datetime | None = None


class OpenSubscriptionRequest(BaseModel):
    """Founder/Finance action: opens a subscription (and issues its first invoice) for an
    organization that does not already have one — the same orchestration `POST /organizations`'
    own optional `plan_id` triggers at creation time, now reachable for an organization onboarded
    without one (no trial, no plan yet) or whose trial has ended and is ready to be billed."""

    organization_id: str
    plan_id: str


class RecordManualPaymentRequest(BaseModel):
    """Founder/Finance-recorded payment against an invoice, for money received outside any
    integrated `PaymentProviderPort` (e.g. a bank transfer). Recorded for the invoice's own exact
    amount — there is no `amount` field here to under/over-report."""

    invoice_id: str
    reference: str | None = None


class ChangeSubscriptionPlanRequest(BaseModel):
    """Organization Management phase. See `Subscription.change_plan`'s own docstring — the
    current billing period and every already-issued invoice are unaffected; the new plan's
    price/cycle applies starting with the next invoice this subscription issues."""

    new_plan_id: str


class ExtendGracePeriodRequest(BaseModel):
    """ADR-0039 §1 / requirement 39G — platform-admin grace extension.

    An absolute instant rather than a day count: the domain receives an unambiguous deadline,
    and the API layer (not the domain) owns interpreting the caller's intent — the same
    "resolve time at the edge" convention every other command in this module follows."""

    grace_period_ends_at: datetime


class InvoiceResponse(BaseModel):
    id: str
    organization_id: str
    subscription_id: str
    number: str
    amount: float
    currency: str
    period_start: date
    period_end: date
    status: str
    issued_at: datetime | None
    due_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InitiatePaymentRequest(BaseModel):
    """`POST /billing/payments` body — API Contracts §4.7's documented sample verbatim:
    `{ "invoice_id","method","msisdn","amount","currency" }`, extended by ADR-0022 with an
    optional `payment_method_token` (a client-tokenized id, e.g. a Stripe `PaymentMethod` —
    the raw card number itself must never reach this backend). `msisdn` is now optional too:
    a card provider has none. `idempotency_key` is **not** a body field — it comes from the
    required `Idempotency-Key` header (API rule #6, API Contracts §12), read directly in
    `routers.py`."""

    invoice_id: str
    method: str
    amount: float
    currency: str
    msisdn: str | None = None
    payment_method_token: str | None = None


class PaymentResponse(BaseModel):
    """See module docstring for why this uses `payment_id` (the documented literal sample),
    unlike every other response schema's `id`, and why `required_action` is omitted."""

    payment_id: str
    status: str


class PaymentListItemResponse(BaseModel):
    """`GET /billing/payments` (ADR-0022 — "payment history," no prior list route existed).
    Unlike `PaymentResponse` above (deliberately minimal, matching §4.7's one documented
    literal sample), this is the full row shape — every other billing list route
    (`PlanResponse`/`SubscriptionResponse`/`InvoiceResponse`) already returns its full DTO, and
    a payment-history view needs more than just `payment_id`/`status` to be useful."""

    id: str
    organization_id: str
    invoice_id: str
    provider: str
    provider_ref: str | None
    amount: float
    currency: str
    status: str
    failure_reason: str | None
    created_at: datetime
    confirmed_at: datetime | None


class CreatePlanRequest(BaseModel):
    """ADR-0040 §4 — the plan catalogue's first write surface.

    Monthly and annual pricing are **separate plan rows** sharing a name, not two prices on one
    row: `billing_cycle` drives every period date `Subscription.open`/`renew` computes, so a row
    carrying both prices would make "which amount applies" ambiguous at invoice-issue time. The
    catalogue UI groups rows by name to present them as one commercial tier.
    """

    name: str = Field(min_length=1, max_length=160)
    billing_scope: str = Field(default="organization", pattern="^organization$")
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    billing_cycle: str = Field(pattern="^(monthly|quarterly|annual)$")
    #: `null` means unlimited on all three — what an Enterprise tier needs.
    vehicle_limit: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=0)
    user_limit: int | None = Field(default=None, ge=0)


class UpdatePlanRequest(BaseModel):
    """`billing_scope`/`billing_cycle` are deliberately absent — both are structural, and
    changing a cycle under a live subscription would silently move its renewal date."""

    name: str = Field(min_length=1, max_length=160)
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    vehicle_limit: int | None = Field(default=None, ge=0)
    device_limit: int | None = Field(default=None, ge=0)
    user_limit: int | None = Field(default=None, ge=0)
