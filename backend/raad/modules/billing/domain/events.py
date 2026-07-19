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
  `TransportFeeCreated`/`TransportFeePaid`/`TransportFeeOverdue`/`TransportFeeWaived` — no
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


# --- Subscription --------------------------------------------------------------------------


def subscription_opened(
    *,
    subscription_id: str,
    organization_id: str,
    subscriber_type: str,
    subscriber_id: str,
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
            "subscriber_type": subscriber_type,
            "subscriber_id": subscriber_id,
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
) -> DomainEvent:
    """`PaymentFailed` (API Contracts §13.2's `payment.failed`, PascalCase)."""
    return _new_event(
        event_type="PaymentFailed",
        aggregate_type="Payment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"invoice_id": invoice_id, "actor_id": actor_id},
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


# --- TransportFee ------------------------------------------------------------------------


def transport_fee_created(
    *,
    transport_fee_id: str,
    organization_id: str,
    student_id: str,
    period: str,
    amount: float,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportFeeCreated",
        aggregate_type="TransportFee",
        aggregate_id=transport_fee_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "student_id": student_id,
            "period": period,
            "amount": amount,
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def transport_fee_paid(
    *,
    transport_fee_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportFeePaid",
        aggregate_type="TransportFee",
        aggregate_id=transport_fee_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def transport_fee_overdue(
    *,
    transport_fee_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportFeeOverdue",
        aggregate_type="TransportFee",
        aggregate_id=transport_fee_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def transport_fee_waived(
    *,
    transport_fee_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="TransportFeeWaived",
        aggregate_type="TransportFee",
        aggregate_id=transport_fee_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
