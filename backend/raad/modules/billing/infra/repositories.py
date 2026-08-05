"""SQLAlchemy repository implementations for `billing` (Backend LLD §7, §8; Database Design
§8.1-§8.5). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` (§7.1's "aggregate-in/
aggregate-out" rule). Mirrors `transport_ops.infra.repositories`'s identity-map/
`flush_tracked_changes` pattern exactly — see that module's own docstring for the full
rationale (a handler mutating a `get()`-returned domain object needs this bridge, since
SQLAlchemy only dirty-tracks its own ORM rows, not detached domain objects).

**Tenant-scoping (ADR-0021).** `subscriptions`/`invoices`/`payments`/`transport_fees` are now
constructed with the caller's resolved `TenantRegionScope` (`SqlAlchemyBillingUnitOfWork.
__aenter__`, set from `api/deps.get_billing_uow`'s `Depends(get_scope)`) — `get_by_id`/
`list_page`/`list_all` all apply it automatically via the base class, mirroring `fleet_device`/
`organization`/`transport_ops`'s identical fix. This closes what was flagged the highest-severity
finding of the tenant-isolation audit: `GET /billing/subscriptions`/`GET /billing/invoices`
previously returned every organization's financial data to any caller holding the (list-only)
`billing.subscriptions.list`/`billing.invoices.list` permission — including `parent`, which
holds both. `plans` also takes a `scope` constructor parameter for shape-parity with every other
repository here, but it stays functionally inert: `PlanModel` has no `organization_id` column at
all (`infra/models.py`'s own docstring), so `SqlAlchemyRepositoryBase._apply_scope`'s `hasattr`
guard never applies one — the same, correct, already-audited "not a bug" posture this module
docstring described before this ADR, unchanged.

**`SqlAlchemyPaymentRepository.get_by_idempotency_key`** backs the documented idempotency
contract (API Contracts §12) — a direct `select()`, mirroring
`SqlAlchemyRouteRepository.get_by_name`'s identical shape for an analogous non-`get_by_id`
finder. **`SqlAlchemySubscriptionRepository.get_active_by_organization`** backs
`domain/repositories.py`'s own flagged, non-LLD-documented finder — see that method's docstring
for the "not EXPIRED/CANCELLED" reading of "active" (ADR-0016: renamed from the former
`get_active_by_subscriber`, organization-only now).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
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
    OrganizationId,
    PaymentId,
    PlanId,
    SubscriptionId,
    TransportFeeId,
)
from raad.modules.billing.infra.mappers import (
    _to_naive_utc,
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

    #: Whitelists for `GET /billing/plans` (§8) - limited to columns already exposed on
    #: `PlanResponse` (`api/schemas.py`), never an internal-only column. `"amount"` (the wire/
    #: DTO field name, `PlanDTO.amount`) maps to `price_amount` (`PlanModel`'s actual column) -
    #: the identical wire-name-vs-column-name split `core.db.repository.FilterField`'s own
    #: docstring documents (e.g. `iam`'s `role` transform), not a typo.
    filterable_fields = {
        "billing_scope": FilterField(column="billing_scope"),
        "billing_cycle": FilterField(column="billing_cycle"),
        "status": FilterField(column="status"),
        "currency": FilterField(column="currency"),
    }
    sortable_fields = {
        "name": "name",
        "amount": "price_amount",
        "status": "status",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ("name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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
        rows = await self.list_scoped()
        return [model_to_plan(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Plan]:
        """Same unscoped posture as `list_all` above - `PlanModel` has no `organization_id`, so
        `TenantRegionScope(organization_ids=None)` is inert here (`SqlAlchemyRepositoryBase.
        list_page`'s own `hasattr` guard), not a shortcut. Backs `GET /billing/plans`'s
        paginated/filtered/sorted contract, mirroring `SqlAlchemyOrganizationRepository.
        list_page`'s identical shape."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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

    #: Whitelist for `GET /billing/subscriptions` (§8) - limited to columns already on
    #: `SubscriptionResponse`. No `searchable_fields` - `subscriptions` has no free-text label
    #: column, mirroring `SqlAlchemyRegionRepository`'s own "only opt in what actually exists"
    #: posture rather than inventing a search target.
    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "plan_id": FilterField(column="plan_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "status": "status",
        "current_period_start": "current_period_start",
        "current_period_end": "current_period_end",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Subscription, SubscriptionModel]] = {}

    async def get(self, subscription_id: SubscriptionId) -> Subscription | None:
        row = await self.get_by_id(str(subscription_id))
        return self._track(row)

    def add(self, subscription: Subscription) -> None:
        model = subscription_to_model(subscription)
        super().add(model)
        self._tracked[str(subscription.id)] = (subscription, model)

    async def list_all(self) -> list[Subscription]:
        rows = await self.list_scoped()
        return [model_to_subscription(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Subscription]:
        """Same unrestricted-`TenantRegionScope` posture `list_all` above already carries (the
        system-wide `ScopeResolver`-pending gap, not a `billing`-specific shortcut) - backs
        `GET /billing/subscriptions`'s paginated/filtered/sorted contract."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

    async def get_active_by_organization(
        self, organization_id: OrganizationId
    ) -> Subscription | None:
        statement = select(SubscriptionModel).where(
            SubscriptionModel.organization_id == str(organization_id),
            SubscriptionModel.status.in_(("trial", "active", "suspended")),
            SubscriptionModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalars().first())

    async def count_by_status(self) -> dict[str, int]:
        """ADR-0020: "Subscription/Billing Status" KPI — one `GROUP BY status` query."""
        statement = self._apply_scope(
            select(SubscriptionModel.status, func.count())
            .where(SubscriptionModel.deleted_at.is_(None))
            .group_by(SubscriptionModel.status)
        )
        result = await self._session.execute(statement)
        return dict(result.all())

    async def count_expiring_between(self, *, start: datetime, end: datetime) -> int:
        """ADR-0020: "Expiring Organizations" KPI — see the domain interface's own docstring
        for why this is a real query, not a mirror of `sweep_expired_subscriptions`'s
        unfiltered scan."""
        statement = self._apply_scope(
            select(SubscriptionModel).where(
                SubscriptionModel.deleted_at.is_(None),
                SubscriptionModel.status.in_(("trial", "active", "suspended")),
                SubscriptionModel.current_period_end >= _to_naive_utc(start),
                SubscriptionModel.current_period_end < _to_naive_utc(end),
            )
        )
        result = await self._session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        return result.scalar_one()

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

    #: Whitelist for `GET /billing/invoices` (§8) - limited to columns already on
    #: `InvoiceResponse`. `period_start`/`period_end` need `value_type=date` (`FilterField`'s
    #: own docstring) since `InvoiceModel` stores them as native PostgreSQL `DATE`, not text.
    filterable_fields = {
        "subscription_id": FilterField(column="subscription_id"),
        "status": FilterField(column="status"),
        "currency": FilterField(column="currency"),
        "period_start": FilterField(column="period_start", value_type=date),
        "period_end": FilterField(column="period_end", value_type=date),
    }
    sortable_fields = {
        "number": "number",
        "amount": "amount",
        "status": "status",
        "issued_at": "issued_at",
        "due_at": "due_at",
        "paid_at": "paid_at",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ("number",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Invoice, InvoiceModel]] = {}

    async def get(self, invoice_id: InvoiceId) -> Invoice | None:
        row = await self.get_by_id(str(invoice_id))
        return self._track(row)

    def add(self, invoice: Invoice) -> None:
        model = invoice_to_model(invoice)
        super().add(model)
        self._tracked[str(invoice.id)] = (invoice, model)

    async def list_all(self) -> list[Invoice]:
        rows = await self.list_scoped()
        return [model_to_invoice(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Invoice]:
        """Same unrestricted-`TenantRegionScope` posture `list_all` above already carries -
        backs `GET /billing/invoices`'s paginated/filtered/sorted contract."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

    async def sum_paid_amount_between(self, *, start: datetime, end: datetime) -> float:
        """ADR-0020: "Revenue" KPI — see the domain interface's own docstring for the
        currency-naive scope call."""
        statement = self._apply_scope(
            select(func.coalesce(func.sum(InvoiceModel.amount), 0.0)).where(
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status == "paid",
                InvoiceModel.paid_at >= _to_naive_utc(start),
                InvoiceModel.paid_at < _to_naive_utc(end),
            )
        )
        result = await self._session.execute(statement)
        return result.scalar_one()

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

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Payment, PaymentModel]] = {}

    async def get(self, payment_id: PaymentId) -> Payment | None:
        row = await self.get_by_id(str(payment_id))
        return self._track(row)

    def add(self, payment: Payment) -> None:
        model = payment_to_model(payment)
        super().add(model)
        self._tracked[str(payment.id)] = (payment, model)

    async def list_all(self) -> list[Payment]:
        rows = await self.list_scoped()
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

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[TransportFee, TransportFeeModel]] = {}

    async def get(self, transport_fee_id: TransportFeeId) -> TransportFee | None:
        row = await self.get_by_id(str(transport_fee_id))
        return self._track(row)

    def add(self, transport_fee: TransportFee) -> None:
        model = transport_fee_to_model(transport_fee)
        super().add(model)
        self._tracked[str(transport_fee.id)] = (transport_fee, model)

    async def list_all(self) -> list[TransportFee]:
        rows = await self.list_scoped()
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
        self.plans = SqlAlchemyPlanRepository(self.session, scope=self.scope)
        self.subscriptions = SqlAlchemySubscriptionRepository(
            self.session, scope=self.scope
        )
        self.invoices = SqlAlchemyInvoiceRepository(self.session, scope=self.scope)
        self.payments = SqlAlchemyPaymentRepository(self.session, scope=self.scope)
        self.transport_fees = SqlAlchemyTransportFeeRepository(
            self.session, scope=self.scope
        )
        return self

    async def commit(self) -> None:
        self.plans.flush_tracked_changes()
        self.subscriptions.flush_tracked_changes()
        self.invoices.flush_tracked_changes()
        self.payments.flush_tracked_changes()
        self.transport_fees.flush_tracked_changes()
        await super().commit()
