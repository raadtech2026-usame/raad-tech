"""ORM ↔ Domain mappers for `billing` (Backend LLD §7.1 "aggregate-in/aggregate-out"; §17
`db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions. Mirrors `transport_ops.infra.mappers`'s `existing=` in-place-update pattern
exactly, including reusing its `_to_naive_utc` fix (Phase 12's live-verification finding:
`SystemClock` returns tz-aware `datetime`s, but every `DateTime(timezone=False)` column needs
naive ones) for every timestamp field here that comes from `Clock.now()`.
"""

from __future__ import annotations

from datetime import datetime

from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    InvoiceStatus,
    Money,
    OrganizationId,
    PaymentId,
    PaymentStatus,
    PlanId,
    PlanStatus,
    StudentId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    SubscriptionStatus,
    TransportFeeId,
    TransportFeeStatus,
)
from raad.modules.billing.infra.models import (
    InvoiceModel,
    PaymentModel,
    PlanModel,
    SubscriptionModel,
    TransportFeeModel,
)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """See `transport_ops.infra.mappers._to_naive_utc`'s own docstring for the live-DB finding
    that motivated this — identical fix, duplicated per module for the same reason every other
    per-module convention in this codebase is duplicated rather than shared
    (`.claude/rules/backend.md` #1)."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def plan_to_model(plan: Plan, *, existing: PlanModel | None = None) -> PlanModel:
    model = existing if existing is not None else PlanModel(id=str(plan.id))
    model.name = plan.name
    model.billing_scope = plan.billing_scope.value
    model.price_amount = plan.price.amount
    model.currency = plan.price.currency
    model.billing_cycle = plan.billing_cycle.value
    model.vehicle_limit = plan.vehicle_limit
    model.status = plan.status.value
    return model


def model_to_plan(model: PlanModel) -> Plan:
    return Plan(
        id=PlanId(model.id),
        name=model.name,
        billing_scope=BillingScope(model.billing_scope),
        price=Money(model.price_amount, model.currency),
        billing_cycle=BillingCycle(model.billing_cycle),
        vehicle_limit=model.vehicle_limit,
        status=PlanStatus(model.status),
    )


def subscription_to_model(
    subscription: Subscription, *, existing: SubscriptionModel | None = None
) -> SubscriptionModel:
    model = (
        existing if existing is not None else SubscriptionModel(id=str(subscription.id))
    )
    model.organization_id = str(subscription.organization_id)
    model.subscriber_type = subscription.subscriber_type.value
    model.subscriber_id = str(subscription.subscriber_id)
    model.plan_id = str(subscription.plan_id)
    model.status = subscription.status.value
    model.current_period_start = _to_naive_utc(subscription.current_period_start)
    model.current_period_end = _to_naive_utc(subscription.current_period_end)
    model.auto_renew = subscription.auto_renew
    return model


def model_to_subscription(model: SubscriptionModel) -> Subscription:
    return Subscription(
        id=SubscriptionId(model.id),
        organization_id=OrganizationId(model.organization_id),
        subscriber_type=SubscriberType(model.subscriber_type),
        subscriber_id=SubscriberId(model.subscriber_id),
        plan_id=PlanId(model.plan_id),
        status=SubscriptionStatus(model.status),
        current_period_start=model.current_period_start,
        current_period_end=model.current_period_end,
        auto_renew=model.auto_renew,
    )


def invoice_to_model(
    invoice: Invoice, *, existing: InvoiceModel | None = None
) -> InvoiceModel:
    model = existing if existing is not None else InvoiceModel(id=str(invoice.id))
    model.organization_id = str(invoice.organization_id)
    model.subscription_id = str(invoice.subscription_id)
    model.number = invoice.number
    model.amount = invoice.amount.amount
    model.currency = invoice.amount.currency
    model.period_start = invoice.period_start
    model.period_end = invoice.period_end
    model.status = invoice.status.value
    model.issued_at = _to_naive_utc(invoice.issued_at)
    model.due_at = _to_naive_utc(invoice.due_at)
    model.paid_at = _to_naive_utc(invoice.paid_at)
    return model


def model_to_invoice(model: InvoiceModel) -> Invoice:
    return Invoice(
        id=InvoiceId(model.id),
        organization_id=OrganizationId(model.organization_id),
        subscription_id=SubscriptionId(model.subscription_id),
        number=model.number,
        amount=Money(model.amount, model.currency),
        period_start=model.period_start,
        period_end=model.period_end,
        status=InvoiceStatus(model.status),
        issued_at=model.issued_at,
        due_at=model.due_at,
        paid_at=model.paid_at,
    )


def payment_to_model(
    payment: Payment, *, existing: PaymentModel | None = None
) -> PaymentModel:
    model = existing if existing is not None else PaymentModel(id=str(payment.id))
    model.organization_id = str(payment.organization_id)
    model.invoice_id = str(payment.invoice_id)
    model.provider = payment.provider
    model.provider_ref = payment.provider_ref
    model.msisdn_masked = payment.msisdn_masked
    model.amount = payment.amount.amount
    model.currency = payment.amount.currency
    model.status = payment.status.value
    model.idempotency_key = payment.idempotency_key
    model.created_at = _to_naive_utc(payment.created_at)
    model.confirmed_at = _to_naive_utc(payment.confirmed_at)
    return model


def model_to_payment(model: PaymentModel) -> Payment:
    return Payment(
        id=PaymentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        invoice_id=InvoiceId(model.invoice_id),
        provider=model.provider,
        provider_ref=model.provider_ref,
        msisdn_masked=model.msisdn_masked,
        amount=Money(model.amount, model.currency),
        status=PaymentStatus(model.status),
        # `idempotency_key` is `CHAR(64)` (Database Design §8.4 literal, `infra/models.py`'s
        # own docstring) - PostgreSQL blank-pads CHAR(n) storage and returns it padded on
        # SELECT (unlike VARCHAR), so a shorter key round-trips with trailing spaces unless
        # stripped here. `.rstrip()` undoes a storage-format artifact, not real data - a
        # legitimate idempotency key ending in a space is not a scenario this needs to guard
        # against (an opaque client-supplied token, never displayed/parsed for meaning).
        idempotency_key=model.idempotency_key.rstrip(),
        created_at=model.created_at,
        confirmed_at=model.confirmed_at,
    )


def transport_fee_to_model(
    fee: TransportFee, *, existing: TransportFeeModel | None = None
) -> TransportFeeModel:
    model = existing if existing is not None else TransportFeeModel(id=str(fee.id))
    model.organization_id = str(fee.organization_id)
    model.student_id = str(fee.student_id)
    model.period = fee.period
    model.amount = fee.amount.amount
    model.currency = fee.amount.currency
    model.status = fee.status.value
    return model


def model_to_transport_fee(model: TransportFeeModel) -> TransportFee:
    return TransportFee(
        id=TransportFeeId(model.id),
        organization_id=OrganizationId(model.organization_id),
        student_id=StudentId(model.student_id),
        period=model.period,
        amount=Money(model.amount, model.currency),
        status=TransportFeeStatus(model.status),
    )
