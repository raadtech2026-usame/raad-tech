"""Billing application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). DTOs are
plain dataclasses — id fields become `str(vo)`, enum/status fields become `.value`, timestamps
stay native `datetime`/`date`, mirroring `transport_ops.application.queries`'s exact convention.

**One DTO per aggregate, not a Summary/Full split** — a deliberate simplification, flagged: every
`transport_ops` aggregate built so far has both a lighter `*SummaryDTO` (for its list query) and
a full `*DTO` (for get-by-id). With five aggregates landing in one phase, this file uses a
single DTO shape per aggregate for both `Get*ByIdQuery` and `List*Query` — every field here is
already a primitive/small value (no embedded child collections the way `RouteDTO`/`TripDTO`
needed a lighter list projection for), so the split would add ten classes for no real ergonomic
gain. `Plan`/`Subscription`/`Invoice` now carry `created_at`/`updated_at`, closing the
module-wide gap this docstring used to flag — `Payment` deliberately still omits them
(`infra/models.py`'s own docstring: no `+ standard audit cols` line in Database Design §8.4,
unlike its three siblings), and `TransportFee` has no HTTP route exposing it at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from raad.core.pagination import (
    FilterCondition,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)


@dataclass(frozen=True)
class GetPlanByIdQuery:
    plan_id: str


@dataclass(frozen=True)
class ListPlansQuery:
    """Backs `GET /billing/plans` (API Contracts §4.7/§7/§8) - pagination/filtering/sorting
    added under the Pagination/Filtering/Sorting phase, mirroring `organization.application.
    queries.ListOrganizationsQuery`'s exact shape."""

    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class PlanDTO:
    id: str
    name: str
    billing_scope: str
    amount: float
    currency: str
    billing_cycle: str
    vehicle_limit: int | None
    status: str
    created_at: datetime
    updated_at: datetime


def plan_to_dto(plan: Plan) -> PlanDTO:
    return PlanDTO(
        id=str(plan.id),
        name=plan.name,
        billing_scope=plan.billing_scope.value,
        amount=plan.price.amount,
        currency=plan.price.currency,
        billing_cycle=plan.billing_cycle.value,
        vehicle_limit=plan.vehicle_limit,
        status=plan.status.value,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@dataclass(frozen=True)
class GetSubscriptionByIdQuery:
    subscription_id: str


@dataclass(frozen=True)
class ListSubscriptionsQuery:
    """Backs `GET /billing/subscriptions` (API Contracts §4.7/§7/§8) - pagination/filtering/
    sorting added under the Pagination/Filtering/Sorting phase."""

    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class SubscriptionDTO:
    id: str
    organization_id: str
    subscriber_type: str
    subscriber_id: str
    plan_id: str
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    auto_renew: bool
    created_at: datetime
    updated_at: datetime


def subscription_to_dto(subscription: Subscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=str(subscription.id),
        organization_id=str(subscription.organization_id),
        subscriber_type=subscription.subscriber_type.value,
        subscriber_id=str(subscription.subscriber_id),
        plan_id=str(subscription.plan_id),
        status=subscription.status.value,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        auto_renew=subscription.auto_renew,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


@dataclass(frozen=True)
class GetInvoiceByIdQuery:
    invoice_id: str


@dataclass(frozen=True)
class ListInvoicesQuery:
    """Backs `GET /billing/invoices` (API Contracts §4.7/§7/§8) - pagination/filtering/sorting
    added under the Pagination/Filtering/Sorting phase."""

    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class InvoiceDTO:
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


def invoice_to_dto(invoice: Invoice) -> InvoiceDTO:
    return InvoiceDTO(
        id=str(invoice.id),
        organization_id=str(invoice.organization_id),
        subscription_id=str(invoice.subscription_id),
        number=invoice.number,
        amount=invoice.amount.amount,
        currency=invoice.amount.currency,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        status=invoice.status.value,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        paid_at=invoice.paid_at,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


@dataclass(frozen=True)
class GetPaymentByIdQuery:
    payment_id: str


@dataclass(frozen=True)
class ListPaymentsQuery:
    pass


@dataclass(frozen=True)
class PaymentDTO:
    id: str
    organization_id: str
    invoice_id: str
    provider: str
    provider_ref: str | None
    msisdn_masked: str | None
    amount: float
    currency: str
    status: str
    idempotency_key: str
    created_at: datetime
    confirmed_at: datetime | None


def payment_to_dto(payment: Payment) -> PaymentDTO:
    return PaymentDTO(
        id=str(payment.id),
        organization_id=str(payment.organization_id),
        invoice_id=str(payment.invoice_id),
        provider=payment.provider,
        provider_ref=payment.provider_ref,
        msisdn_masked=payment.msisdn_masked,
        amount=payment.amount.amount,
        currency=payment.amount.currency,
        status=payment.status.value,
        idempotency_key=payment.idempotency_key,
        created_at=payment.created_at,
        confirmed_at=payment.confirmed_at,
    )


@dataclass(frozen=True)
class GetTransportFeeByIdQuery:
    transport_fee_id: str


@dataclass(frozen=True)
class ListTransportFeesQuery:
    pass


@dataclass(frozen=True)
class TransportFeeDTO:
    id: str
    organization_id: str
    student_id: str
    period: str
    amount: float
    currency: str
    status: str


def transport_fee_to_dto(transport_fee: TransportFee) -> TransportFeeDTO:
    return TransportFeeDTO(
        id=str(transport_fee.id),
        organization_id=str(transport_fee.organization_id),
        student_id=str(transport_fee.student_id),
        period=transport_fee.period,
        amount=transport_fee.amount.amount,
        currency=transport_fee.amount.currency,
        status=transport_fee.status.value,
    )
