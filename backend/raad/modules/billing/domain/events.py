"""Domain events for the `billing` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`), populated with `billing`-specific
`event_type`/`aggregate_type`/`payload`, mirroring every other module's identical
`_new_event` pattern.

Factories take primitive values only, never the aggregate objects themselves (serializable for
`outbox.payload_json`, Database Design §8.8; avoids a circular import with `entities.py`).

**Naming provenance, per event — some documented verbatim, most this phase's own choice
(flagged, not silently assumed), exactly as `transport_ops.domain.events`'s own running log
already establishes for its own five phases:**

- `SubscriptionRenewed` / `SubscriptionExpired` — **LLD §5.4 names both verbatim** ("Re-
  evaluation events... `SubscriptionExpired` / `SubscriptionRenewed` (Billing)").
- `PaymentConfirmed` / `PaymentFailed` — API Contracts §13.2 names the wire form
  (`payment.confirmed` / `payment.failed`, dot-notation); translated to this codebase's
  enforced PascalCase convention, the same translation every prior phase's own event catalogue
  entries already apply (e.g. `TripStarted` from `trip.started`).
- `PlanCreated`/`PlanActivated`/`PlanDisabled`, `SubscriptionOpened`/`SubscriptionSuspended`/
  `SubscriptionCancelled`, `InvoiceIssued`/`InvoicePaid`/`InvoiceVoided`,
  `PaymentInitiated`/`PaymentProcessing`/`PaymentExpired`,
  approved document names any of these; chosen to match each aggregate's own domain method
  names 1:1 and the established PascalCase-past-tense convention, the same posture
  `RouteCreated`/`TripScheduled`/`StudentAssignmentCreated` already establish for their own
  unnamed creation/status events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    org_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


# --- Plan --------------------------------------------------------------------------------


def plan_created(
    *,
    plan_id: str,
    name: str,
    billing_scope: str,
    amount: float,
    currency: str,
    billing_cycle: str,
    vehicle_limit: int | None,
    device_limit: int | None = None,
    user_limit: int | None = None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="PlanCreated",
        aggregate_type="Plan",
        aggregate_id=plan_id,
        org_id=None,  # Plan is not tenant-owned - see entities.py's Plan docstring
        occurred_at=occurred_at,
        payload={
            "name": name,
            "billing_scope": billing_scope,
            "amount": amount,
            "currency": currency,
            "billing_cycle": billing_cycle,
            "vehicle_limit": vehicle_limit,
            "device_limit": device_limit,
            "user_limit": user_limit,
            "actor_id": actor_id,
        },
    )


def plan_updated(
    *,
    plan_id: str,
    name: str,
    amount: float,
    currency: str,
    vehicle_limit: int | None,
    device_limit: int | None,
    user_limit: int | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    """ADR-0040 §4. `Plan` had no update path before — its catalogue was seed-only."""
    return _new_event(
        event_type="PlanUpdated",
        aggregate_type="Plan",
        aggregate_id=plan_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={
            "plan_id": plan_id,
            "name": name,
            "amount": amount,
            "currency": currency,
            "vehicle_limit": vehicle_limit,
            "device_limit": device_limit,
            "user_limit": user_limit,
            "actor_id": actor_id,
        },
    )


def plan_activated(
    *, plan_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="PlanActivated",
        aggregate_type="Plan",
        aggregate_id=plan_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def plan_disabled(
    *, plan_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="PlanDisabled",
        aggregate_type="Plan",
        aggregate_id=plan_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def plan_deleted(
    *, plan_id: str, name: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    """Organization Management phase. Constructed directly by
    `BillingApplicationService.delete_plan` rather than through a `Plan.delete()` mutator — the
    row is gone immediately after, so there is no aggregate left to keep mutating/re-querying,
    unlike every other event here. `.claude/rules/security.md` #8 still requires this action be
    audit-logged, so the event is built and recorded explicitly instead of silently skipped
    (mirrors `ScopeAssignmentApplicationService`'s own precedent for a grant/revoke aggregate
    with no rich lifecycle of its own — see that service's events for the identical shape)."""
    return _new_event(
        event_type="PlanDeleted",
        aggregate_type="Plan",
        aggregate_id=plan_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"name": name, "actor_id": actor_id},
    )


# --- Subscription --------------------------------------------------------------------------


def subscription_opened(
    *,
    subscription_id: str,
    organization_id: str,
    plan_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="SubscriptionOpened",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "plan_id": plan_id,
            "actor_id": actor_id,
        },
    )


def subscription_renewed(
    *,
    subscription_id: str,
    organization_id: str,
    period_start: str,
    period_end: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`SubscriptionRenewed` (Backend LLD §5.4 verbatim) — a CR-1 re-evaluation event."""
    return _new_event(
        event_type="SubscriptionRenewed",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "period_start": period_start,
            "period_end": period_end,
            "actor_id": actor_id,
        },
    )


def subscription_expired(
    *,
    subscription_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`SubscriptionExpired` (Backend LLD §5.4 verbatim) — a CR-1 re-evaluation event."""
    return _new_event(
        event_type="SubscriptionExpired",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def subscription_suspended(
    *,
    subscription_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="SubscriptionSuspended",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def subscription_plan_changed(
    *,
    subscription_id: str,
    organization_id: str,
    old_plan_id: str,
    new_plan_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """Organization Management phase. No approved document names this event — flagged, matching
    the established "flagged, not silently assumed" naming posture every prior phase's own
    unnamed events already carry."""
    return _new_event(
        event_type="SubscriptionPlanChanged",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "old_plan_id": old_plan_id,
            "new_plan_id": new_plan_id,
            "actor_id": actor_id,
        },
    )


def subscription_cancelled(
    *,
    subscription_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="SubscriptionCancelled",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def subscription_past_due(
    *,
    subscription_id: str,
    organization_id: str,
    grace_period_ends_at: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0039 §5 — the billing period ended with an unpaid invoice and the automatic grace
    window has started. Carries `grace_period_ends_at` so a consumer can surface the deadline
    without a second lookup."""
    return _new_event(
        event_type="SubscriptionPastDue",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id, "grace_period_ends_at": grace_period_ends_at},
    )


def subscription_grace_period_extended(
    *,
    subscription_id: str,
    organization_id: str,
    grace_period_ends_at: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0039 §1 — a platform admin deliberately extended grace beyond the automatic window.
    Distinct from `SubscriptionPastDue` precisely because a human decided it."""
    return _new_event(
        event_type="SubscriptionGracePeriodExtended",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id, "grace_period_ends_at": grace_period_ends_at},
    )


def subscription_reactivated(
    *,
    subscription_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0039 §5 — a suspended/past-due subscription was returned to `ACTIVE` without a new
    billing period being started (unlike `SubscriptionRenewed`, which always moves the period).
    Kept separate so "we let them back in" and "they paid for another month" are never conflated
    in the audit trail."""
    return _new_event(
        event_type="SubscriptionReactivated",
        aggregate_type="Subscription",
        aggregate_id=subscription_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


# --- Invoice ---------------------------------------------------------------------------


def invoice_issued(
    *,
    invoice_id: str,
    organization_id: str,
    subscription_id: str,
    amount: float,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="InvoiceIssued",
        aggregate_type="Invoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "subscription_id": subscription_id,
            "amount": amount,
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def invoice_paid(
    *,
    invoice_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="InvoicePaid",
        aggregate_type="Invoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def invoice_voided(
    *,
    invoice_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="InvoiceVoided",
        aggregate_type="Invoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


# --- Payment ---------------------------------------------------------------------------


def payment_initiated(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    provider: str,
    amount: float,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="PaymentInitiated",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "provider": provider,
            "amount": amount,
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def payment_processing(
    *,
    payment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="PaymentProcessing",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def payment_confirmed(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    provider_ref: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`PaymentConfirmed` (API Contracts §13.2's `payment.confirmed`, PascalCase)."""
    return _new_event(
        event_type="PaymentConfirmed",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "provider_ref": provider_ref,
            "actor_id": actor_id,
        },
    )


def payment_failed(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    occurred_at: datetime,
    actor_id: str | None,
    failure_reason: str | None = None,
) -> DomainEvent:
    """`PaymentFailed` (API Contracts §13.2's `payment.failed`, PascalCase). `failure_reason`
    (ADR-0022) is optional — a provider-supplied decline message when one exists, `None`
    otherwise (e.g. `reconcile_expired_payments`' own timeout-driven failures have no provider
    message to attach)."""
    return _new_event(
        event_type="PaymentFailed",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"invoice_id": invoice_id, "actor_id": actor_id, "failure_reason": failure_reason},
    )


def payment_requires_review(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    reason: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`PaymentRequiresReview` (finance P0.3). A provider confirmed money that could not be
    applied — the invoice was voided, or already paid by another payment, while this one was in
    flight. The payment is kept as paid (the money is real) and this event lands in
    `audit_entries`, where Finance can find it and refund by hand; no refund feature exists yet."""
    return _new_event(
        event_type="PaymentRequiresReview",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"invoice_id": invoice_id, "reason": reason, "actor_id": actor_id},
    )


def payment_expired(
    *,
    payment_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="PaymentExpired",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
