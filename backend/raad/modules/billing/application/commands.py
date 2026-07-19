"""Billing application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects —
every command carries the calling `Principal` as `actor`, identifiers are plain `str`, mirroring
`transport_ops.application.commands`'s exact shape.

**`RenewParentSubscriptionCommand` is the one command in this file with a literal LLD
citation** — §4.2's own contract-skeleton example names it verbatim: `Command
RenewParentSubscription { parent_id, plan_id, msisdn, actor }`. `organization_id` is added here
beyond that literal skeleton — every command in this entire codebase requires it for tenant
scoping (`.claude/rules/backend.md` #4), and LLD §4.2's own skeletons are explicitly
"signatures only... no logic" illustrations, not exhaustive field lists (the same minimal,
necessary addition `ScheduleTripCommand` already makes beyond `Command StartTrip`'s own
skeleton). No document names an HTTP route for it (API Contracts §4.7 lists no
`/billing/subscriptions/renew`-shaped path) — reachable at the application layer only, the same
"use-case exists, no approved endpoint yet" posture `RemoveStopFromRouteCommand` establishes.

**`InitiatePaymentCommand` / `PaymentCallbackCommand` back the two documented payment routes**
(API Contracts §4.7: `POST /billing/payments`, `POST /billing/payments/callback`).
`InitiatePaymentCommand`'s fields match the documented request body verbatim
(`invoice_id, method, msisdn, amount, currency`) plus `idempotency_key` (API rule #6: required
`Idempotency-Key` header, carried into the command rather than the body, matching where the
header actually lives on the wire). `PaymentCallbackCommand`'s exact body shape is **not**
documented anywhere (API Contracts §12: "Body is provider-shaped and normalized by the
adapter" — normalization is `EvcPlusPaymentAdapter`'s job, and that adapter is deliberately not
implemented this phase, see `infra/adapters.py`) — this command's shape
(`payment_id, provider_ref, status`) is a **minimal, flagged placeholder** for an
already-normalized outcome, not a claim about EVC Plus's real webhook contract.

**Every other command** (`Plan`/`Subscription` status transitions, `Invoice` issuance/voiding,
`TransportFee` lifecycle) has no approved document naming it, 1:1 with each aggregate's own
domain method names — the same "flagged, not silently assumed" naming posture every prior
phase's own unnamed commands already carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class CreatePlanCommand:
    name: str
    billing_scope: str
    amount: float
    currency: str
    billing_cycle: str
    vehicle_limit: int | None
    actor: Principal


@dataclass(frozen=True)
class ActivatePlanCommand:
    plan_id: str
    actor: Principal


@dataclass(frozen=True)
class DisablePlanCommand:
    plan_id: str
    actor: Principal


@dataclass(frozen=True)
class RenewParentSubscriptionCommand:
    """Backend LLD §4.2 verbatim (plus `organization_id` — see module docstring). No approved
    HTTP route exists for this command this phase."""

    organization_id: str
    parent_id: str
    plan_id: str
    msisdn: str
    actor: Principal


@dataclass(frozen=True)
class ExpireSubscriptionCommand:
    subscription_id: str
    actor: Principal


@dataclass(frozen=True)
class SuspendSubscriptionCommand:
    subscription_id: str
    actor: Principal


@dataclass(frozen=True)
class CancelSubscriptionCommand:
    subscription_id: str
    actor: Principal


@dataclass(frozen=True)
class IssueInvoiceCommand:
    organization_id: str
    subscription_id: str
    amount: float
    currency: str
    period_start: date
    period_end: date
    due_at: datetime | None
    actor: Principal


@dataclass(frozen=True)
class VoidInvoiceCommand:
    invoice_id: str
    actor: Principal


@dataclass(frozen=True)
class InitiatePaymentCommand:
    """`POST /billing/payments` (API Contracts §4.7, documented request body verbatim, plus
    `idempotency_key` from the required `Idempotency-Key` header, API rule #6)."""

    invoice_id: str
    method: str
    msisdn: str
    amount: float
    currency: str
    idempotency_key: str
    actor: Principal


@dataclass(frozen=True)
class PaymentCallbackCommand:
    """`POST /billing/payments/callback` — see module docstring for why this shape is a
    flagged, minimal placeholder, not a documented EVC Plus webhook contract."""

    payment_id: str
    status: str
    provider_ref: str | None
    actor: Principal


@dataclass(frozen=True)
class MarkPaymentExpiredCommand:
    """No approved HTTP route (Scheduler/reconciliation-job-triggered only, out of this
    phase's scope per the task's own "Scheduler behavior that lacks documented execution
    details" exclusion)."""

    payment_id: str
    actor: Principal


@dataclass(frozen=True)
class CreateTransportFeeCommand:
    organization_id: str
    student_id: str
    period: str
    amount: float
    currency: str
    actor: Principal


@dataclass(frozen=True)
class MarkTransportFeePaidCommand:
    transport_fee_id: str
    actor: Principal


@dataclass(frozen=True)
class MarkTransportFeeOverdueCommand:
    transport_fee_id: str
    actor: Principal


@dataclass(frozen=True)
class WaiveTransportFeeCommand:
    transport_fee_id: str
    actor: Principal
