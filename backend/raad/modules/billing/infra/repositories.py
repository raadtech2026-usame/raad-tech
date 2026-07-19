"""SQLAlchemy repository implementations for `billing` (Backend LLD §7, §8; Database Design
§8.1-§8.5). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` (§7.1's "aggregate-in/
aggregate-out" rule). Mirrors `transport_ops.infra.repositories`'s identity-map/
`flush_tracked_changes` pattern exactly — see that module's own docstring for the full
rationale (a handler mutating a `get()`-returned domain object needs this bridge, since
SQLAlchemy only dirty-tracks its own ORM rows, not detached domain objects).

**`list_all`'s unrestricted-`TenantRegionScope` caveat carries over unchanged** — the same
system-wide `ScopeResolver`-pending gap `transport_ops.infra.repositories`'s own module
docstring already flags, not a `billing`-specific one. **`PlanModel.list_all` still calls
`list_scoped`** even though `Plan` has no `organization_id` column at all (`infra/models.py`'s
own docstring) — `SqlAlchemyRepositoryBase.list_scoped` already guards its org filter with
`hasattr(self.model, "organization_id")`, so it simply never applies one for `PlanModel` while
still applying the soft-delete filter, the same method every other repository here uses rather
than a special-cased hand-rolled `select()`.

**`SqlAlchemyPaymentRepository.get_by_idempotency_key`** backs the documented idempotency
contract (API Contracts §12) — a direct `select()`, mirroring
`SqlAlchemyRouteRepository.get_by_name`'s identical shape for an analogous non-`get_by_id`
finder. **`SqlAlchemySubscriptionRepository.get_active_by_subscriber`** backs
`domain/repositories.py`'s own flagged, non-LLD-documented finder — see that method's docstring
for the "not EXPIRED/CANCELLED" reading of "active."
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
    TransportFeeRepository,
)
from raad.modules.billing.domain.value_objects import (
    InvoiceId,
    PaymentId,
    PlanId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    TransportFeeId,
)
from raad.modules.billing.infra.mappers import (
    invoice_to_model,
    model_to_invoice,
    model_to_payment,
    model_to_plan,
    model_to_subscription,
    model_to_transport_fee,
    payment_to_model,
    plan_to_model,
    subscription_to_model,
    transport_fee_to_model,
)
from raad.modules.billing.infra.models import (
    InvoiceModel,
    PaymentModel,
    PlanModel,
    SubscriptionModel,
    TransportFeeModel,
)


class SqlAlchemyPlanRepository(SqlAlchemyRepositoryBase[PlanModel], PlanRepository):
    model = PlanModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Plan, PlanModel]] = {}

    async def get(self, plan_id: PlanId) -> Plan | None:
        row = await self.get_by_id(str(plan_id))
        return self._track(row)

    def add(self, plan: Plan) -> None:
        model = plan_to_model(plan)
        super().add(model)
        self._tracked[str(plan.id)] = (plan, model)

    async def list_all(self) -> list[Plan]:
        """`list_scoped` still works here even though `Plan` has no `organization_id`
        (`infra/models.py`'s module docstring) - `SqlAlchemyRepositoryBase.list_scoped` already
        guards its org filter with `hasattr(self.model, "organization_id")`, so this simply
        never applies one for `PlanModel`, while the soft-delete filter still does - the same
        method every other repository in this file uses, not a special case."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_plan(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for plan, model in self._tracked.values():
            plan_to_model(plan, existing=model)

    def _track(self, row: PlanModel | None) -> Plan | None:
        if row is None:
            return None
        plan = model_to_plan(row)
        self._tracked[row.id] = (plan, row)
        return plan


class SqlAlchemySubscriptionRepository(
    SqlAlchemyRepositoryBase[SubscriptionModel], SubscriptionRepository
):
    model = SubscriptionModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Subscription, SubscriptionModel]] = {}

    async def get(self, subscription_id: SubscriptionId) -> Subscription | None:
        row = await self.get_by_id(str(subscription_id))
        return self._track(row)

    def add(self, subscription: Subscription) -> None:
        model = subscription_to_model(subscription)
        super().add(model)
        self._tracked[str(subscription.id)] = (subscription, model)

    async def list_all(self) -> list[Subscription]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_subscription(row) for row in rows]

    async def get_active_by_subscriber(
        self, subscriber_type: SubscriberType, subscriber_id: SubscriberId
    ) -> Subscription | None:
        statement = select(SubscriptionModel).where(
            SubscriptionModel.subscriber_type == subscriber_type.value,
            SubscriptionModel.subscriber_id == str(subscriber_id),
            SubscriptionModel.status.in_(("trial", "active", "suspended")),
            SubscriptionModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalars().first())

    def flush_tracked_changes(self) -> None:
        for subscription, model in self._tracked.values():
            subscription_to_model(subscription, existing=model)

    def _track(self, row: SubscriptionModel | None) -> Subscription | None:
        if row is None:
            return None
        subscription = model_to_subscription(row)
        self._tracked[row.id] = (subscription, row)
        return subscription


class SqlAlchemyInvoiceRepository(
    SqlAlchemyRepositoryBase[InvoiceModel], InvoiceRepository
):
    model = InvoiceModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Invoice, InvoiceModel]] = {}

    async def get(self, invoice_id: InvoiceId) -> Invoice | None:
        row = await self.get_by_id(str(invoice_id))
        return self._track(row)

    def add(self, invoice: Invoice) -> None:
        model = invoice_to_model(invoice)
        super().add(model)
        self._tracked[str(invoice.id)] = (invoice, model)

    async def list_all(self) -> list[Invoice]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_invoice(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for invoice, model in self._tracked.values():
            invoice_to_model(invoice, existing=model)

    def _track(self, row: InvoiceModel | None) -> Invoice | None:
        if row is None:
            return None
        invoice = model_to_invoice(row)
        self._tracked[row.id] = (invoice, row)
        return invoice


class SqlAlchemyPaymentRepository(
    SqlAlchemyRepositoryBase[PaymentModel], PaymentRepository
):
    model = PaymentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Payment, PaymentModel]] = {}

    async def get(self, payment_id: PaymentId) -> Payment | None:
        row = await self.get_by_id(str(payment_id))
        return self._track(row)

    def add(self, payment: Payment) -> None:
        model = payment_to_model(payment)
        super().add(model)
        self._tracked[str(payment.id)] = (payment, model)

    async def list_all(self) -> list[Payment]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_payment(row) for row in rows]

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        statement = select(PaymentModel).where(
            PaymentModel.idempotency_key == idempotency_key
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def flush_tracked_changes(self) -> None:
        for payment, model in self._tracked.values():
            payment_to_model(payment, existing=model)

    def _track(self, row: PaymentModel | None) -> Payment | None:
        if row is None:
            return None
        payment = model_to_payment(row)
        self._tracked[row.id] = (payment, row)
        return payment


class SqlAlchemyTransportFeeRepository(
    SqlAlchemyRepositoryBase[TransportFeeModel], TransportFeeRepository
):
    model = TransportFeeModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[TransportFee, TransportFeeModel]] = {}

    async def get(self, transport_fee_id: TransportFeeId) -> TransportFee | None:
        row = await self.get_by_id(str(transport_fee_id))
        return self._track(row)

    def add(self, transport_fee: TransportFee) -> None:
        model = transport_fee_to_model(transport_fee)
        super().add(model)
        self._tracked[str(transport_fee.id)] = (transport_fee, model)

    async def list_all(self) -> list[TransportFee]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_transport_fee(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for fee, model in self._tracked.values():
            transport_fee_to_model(fee, existing=model)

    def _track(self, row: TransportFeeModel | None) -> TransportFee | None:
        if row is None:
            return None
        fee = model_to_transport_fee(row)
        self._tracked[row.id] = (fee, row)
        return fee


class SqlAlchemyBillingUnitOfWork(SqlAlchemyUnitOfWork, BillingUnitOfWork):
    """Concrete `BillingUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `billing`'s five
    repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row immediately before delegating to `SqlAlchemyUnitOfWork.commit()`
    — identical shape to `transport_ops.infra.repositories.SqlAlchemyTransportOpsUnitOfWork`.
    """

    plans: SqlAlchemyPlanRepository
    subscriptions: SqlAlchemySubscriptionRepository
    invoices: SqlAlchemyInvoiceRepository
    payments: SqlAlchemyPaymentRepository
    transport_fees: SqlAlchemyTransportFeeRepository

    async def __aenter__(self) -> "SqlAlchemyBillingUnitOfWork":
        await super().__aenter__()
        self.plans = SqlAlchemyPlanRepository(self.session)
        self.subscriptions = SqlAlchemySubscriptionRepository(self.session)
        self.invoices = SqlAlchemyInvoiceRepository(self.session)
        self.payments = SqlAlchemyPaymentRepository(self.session)
        self.transport_fees = SqlAlchemyTransportFeeRepository(self.session)
        return self

    async def commit(self) -> None:
        self.plans.flush_tracked_changes()
        self.subscriptions.flush_tracked_changes()
        self.invoices.flush_tracked_changes()
        self.payments.flush_tracked_changes()
        self.transport_fees.flush_tracked_changes()
        await super().commit()
