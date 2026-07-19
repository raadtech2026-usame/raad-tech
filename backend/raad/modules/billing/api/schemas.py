"""HTTP request/response DTOs for `billing` (Backend LLD §16; API Contracts §4.7). Pydantic
models are transport-only — no business logic here; `routers.py` does the DTO<->application
translation. Mirrors `transport_ops.api.schemas`'s shape exactly.

Only the five documented `/billing/*` endpoints (API Contracts §4.7 lines 170-174) get a
request/response shape here — `Plan`/`Subscription` have no documented write routes at all (no
`POST/PATCH/DELETE /billing/plans` or `/billing/subscriptions` anywhere in §4.7's table; the
user's own task scope explicitly forbids building them), so no `Create*Request`/`Update*Request`
exists for either. List responses use the same single-DTO shape `application/queries.py` already
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

from pydantic import BaseModel


class PlanResponse(BaseModel):
    id: str
    name: str
    billing_scope: str
    amount: float
    currency: str
    billing_cycle: str
    vehicle_limit: int | None
    status: str


class SubscriptionResponse(BaseModel):
    id: str
    organization_id: str
    subscriber_type: str
    subscriber_id: str
    plan_id: str
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    auto_renew: bool


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


class InitiatePaymentRequest(BaseModel):
    """`POST /billing/payments` body — API Contracts §4.7's documented sample verbatim:
    `{ "invoice_id","method","msisdn","amount","currency" }`. `idempotency_key` is **not** a
    body field — it comes from the required `Idempotency-Key` header (API rule #6, API
    Contracts §12), read directly in `routers.py`."""

    invoice_id: str
    method: str
    msisdn: str
    amount: float
    currency: str


class PaymentResponse(BaseModel):
    """See module docstring for why this uses `payment_id` (the documented literal sample),
    unlike every other response schema's `id`, and why `required_action` is omitted."""

    payment_id: str
    status: str
