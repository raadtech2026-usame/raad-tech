"""Repository interfaces for the `billing` module (Backend LLD §5.1/§7.1/§7.2). Framework-free
— no SQLAlchemy/FastAPI/Pydantic. No LLD-given contract skeleton exists for any of these five
(unlike `TripRepository`, which LLD §7.2 gives verbatim) — each mirrors the closest already-
completed precedent in `transport_ops.domain.repositories`.

`PlanRepository`/`SubscriptionRepository`/`InvoiceRepository`/`PaymentRepository`/
— `get`/`add`/`list_all`, the same minimal shape `DriverRepository`
establishes for an aggregate with no module-owned uniqueness constraint beyond its own primary
key (none of `plans`/`subscriptions`/`invoices`/`payments` declare a `UX` on
anything other than `payments.idempotency_key`/`payments.provider_ref` and `invoices.number` —
see `PaymentRepository.get_by_idempotency_key` and `InvoiceRepository`'s own docstring below for
the two that need a dedicated finder).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
)
from raad.modules.billing.domain.value_objects import (
    InvoiceId,
    OrganizationId,
    PaymentId,
    PlanId,
    SubscriptionId,
)


class PlanRepository(ABC):
    @abstractmethod
    async def get(self, plan_id: PlanId) -> Plan | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, plan: Plan) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Plan]:
        """Backs `ListPlansQuery` (API Contracts §4.7's documented `GET /billing/plans`).
        `Plan` is not tenant-owned (`entities.py`'s own docstring) — unlike every other
        `list_all` in this codebase, this one is not even implicitly org-scoped."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Plan]:
        """Backs `GET /billing/plans`'s paginated/filtered/sorted contract (API Contracts §7/
        §8), added under the Pagination/Filtering/Sorting phase. `core.pagination` is
        framework-free (no SQLAlchemy/FastAPI), so referencing its types here does not pull
        infra/transport concerns into the domain layer — mirrors
        `organization.domain.repositories.OrganizationRepository.list_page`'s identical
        reasoning."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, plan: Plan) -> None:
        """Organization Management phase — the **first and only** aggregate-root hard delete in
        this codebase (every other lifecycle terminus anywhere here is a status-flag transition:
        `Plan.disable()`, `Region.deactivate()`, `Organization.deactivate()`,
        `PlatformFinancialCategory.archive()` — none of them write `deleted_at` or issue a real
        `DELETE`). Deliberately narrow: the application layer
        (`BillingApplicationService.delete_plan`) only ever calls this after confirming, via
        `SubscriptionRepository.exists_for_plan`, that no subscription — in any status, ever —
        has referenced this plan. `subscriptions.plan_id` also carries a real DB `FOREIGN KEY`
        with no `ON DELETE` clause (Postgres default `RESTRICT`), so a referenced plan could
        never be deleted even if this application-layer guard were bypassed — the guard exists to
        turn that DB-level rejection into a clear, explained refusal instead of a raw
        `IntegrityError`."""
        raise NotImplementedError


class SubscriptionRepository(ABC):
    @abstractmethod
    async def get(self, subscription_id: SubscriptionId) -> Subscription | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, subscription: Subscription) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Subscription]:
        """Backs `ListSubscriptionsQuery` (API Contracts §4.7's documented
        `GET /billing/subscriptions`). Already implicitly scoped to the caller's tenant."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Subscription]:
        """Backs `GET /billing/subscriptions`'s paginated/filtered/sorted contract (API
        Contracts §7/§8), added under the Pagination/Filtering/Sorting phase."""
        raise NotImplementedError

    @abstractmethod
    async def get_current_by_organization(
        self, organization_id: OrganizationId
    ) -> Subscription | None:
        """ADR-0039 — the organization's most recent subscription **regardless of status**,
        newest first.

        **Why this is a separate finder and not a flag on `get_active_by_organization`.** That
        method deliberately excludes `EXPIRED`/`CANCELLED`, which is correct for its own job
        ("find a row in flight so we don't open a duplicate") and exactly wrong for access
        enforcement: an expired organization would come back as `None`, be read as "never
        subscribed", and — under `OrganizationAccessPolicy`'s deliberate fail-open on `None`
        (see that policy's own docstring) — be **granted** access. That would have silently
        defeated the whole point of ADR-0039 for the one state most likely to occur in
        production. Enforcement therefore asks this method, which hides nothing.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_lifecycle_candidates(self) -> list[Subscription]:
        """ADR-0039 §5 — every subscription the lifecycle job could still transition
        (`trial`/`active`/`past_due`/`grace_period`). Terminal states (`suspended` is terminal
        *for the job*; `expired`/`cancelled` are terminal outright) are excluded in SQL rather
        than fetched and skipped in Python, which is what the replaced
        `sweep_expired_subscriptions` did via an unfiltered `list_all()` — an unbounded scan of
        every subscription ever created, on every tick.

        Deliberately not paginated: this is a platform-wide job, and the candidate set is
        bounded by the number of paying organizations (tens, not millions). If that assumption
        ever stops holding, this is the method to add a cursor to.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_active_by_organization(
        self, organization_id: OrganizationId
    ) -> Subscription | None:
        """Not from any LLD contract skeleton — added because opening/renewing an organization's
        subscription needs to find an existing one to extend rather than blindly opening a
        duplicate every time, and no document states whether "active" here should include
        `TRIAL` — reads it as "not `EXPIRED`/`CANCELLED`" (i.e. `TRIAL`, `ACTIVE`, or
        `SUSPENDED`), the most conservative reading that still avoids creating a second row for
        an organization that already has one in flight. Flagged as this phase's own
        interpretive choice, not a documented method. ADR-0016: renamed from the former
        `get_active_by_subscriber(subscriber_type, subscriber_id)` now that `Subscription` keys
        on `organization_id` alone."""
        raise NotImplementedError

    @abstractmethod
    async def count_by_status(self) -> dict[str, int]:
        """ADR-0020: "Subscription/Billing Status" KPI — one `GROUP BY status` query."""
        raise NotImplementedError

    @abstractmethod
    async def count_expiring_between(self, *, start: datetime, end: datetime) -> int:
        """ADR-0020: "Expiring Organizations" KPI — a real SQL query, deliberately **not** a
        mirror of `sweep_expired_subscriptions`'s existing `list_all()` + in-Python scan (that
        loads every subscription unfiltered; fine for an infrequent sweep job, wrong for a KPI
        read). Counts non-terminal subscriptions (`trial`/`active`/`suspended`) whose
        `current_period_end` falls in `[start, end)` — both boundaries resolved by the caller
        (never `datetime.now()` called here), matching every other new stats method this ADR
        adds."""
        raise NotImplementedError

    @abstractmethod
    async def exists_for_plan(self, plan_id: PlanId) -> bool:
        """Organization Management phase — does *any* subscription, in *any* status (including
        terminal ones), reference this plan? Backs `BillingApplicationService.delete_plan`'s
        safety guard — see `PlanRepository.delete`'s own docstring for the full reasoning.
        Deliberately not status-filtered, unlike `has_unpaid_for_subscription`: even a long-
        cancelled subscription that once used this plan is a historical record this plan's own
        row is still needed to make sense of (`SubscriptionResponse.planId` is rendered
        directly), so "referenced" means referenced at all, ever."""
        raise NotImplementedError

    @abstractmethod
    async def count_active_by_billing_cycle(self) -> dict[str, int]:
        """Platform Finance "Monthly vs Annual Subscribers" KPI — a `Subscription` JOIN `Plan`
        grouped by `Plan.billing_cycle` (`monthly`/`quarterly`/`annual`), restricted to
        non-terminal subscriptions (`trial`/`active`/`past_due`/`grace_period`, the same set
        `list_lifecycle_candidates` already treats as "still a real subscriber" — a suspended/
        expired/cancelled subscriber is not meaningfully "a monthly subscriber" for this KPI).
        `Subscription` itself carries no `billing_cycle` — only `Plan` does — so this is
        genuinely a new query, not a re-derivation of `count_by_status`."""
        raise NotImplementedError


class InvoiceRepository(ABC):
    @abstractmethod
    async def get(self, invoice_id: InvoiceId) -> Invoice | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, invoice: Invoice) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Invoice]:
        """Backs `ListInvoicesQuery` (API Contracts §4.7's documented
        `GET /billing/invoices`). Already implicitly scoped to the caller's tenant."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Invoice]:
        """Backs `GET /billing/invoices`'s paginated/filtered/sorted contract (API Contracts
        §7/§8), added under the Pagination/Filtering/Sorting phase."""
        raise NotImplementedError

    @abstractmethod
    async def has_unpaid_for_subscription(
        self, subscription_id: SubscriptionId
    ) -> bool:
        """ADR-0039 §5 — does this subscription have any invoice not yet `PAID`/`VOID`?

        This is the fact that decides `ACTIVE → PAST_DUE` vs `ACTIVE → renew` when a period
        rolls over. Expressed as a `bool` rather than returning the invoices themselves because
        the lifecycle job needs nothing else from them, and a `COUNT`-shaped query stays cheap
        as invoice history grows.

        `VOID` counts as settled: a voided invoice is one RAAD itself withdrew, and holding a
        tenant past-due over an invoice we cancelled would be wrong.
        """
        raise NotImplementedError

    @abstractmethod
    async def exists_for_period(
        self,
        subscription_id: SubscriptionId,
        *,
        period_start: date,
        period_end: date,
    ) -> bool:
        """ADR-0039 §5 — is there already an invoice covering exactly this billing period?

        **This is the lifecycle job's idempotency guard for invoice issuance**, and the reason
        the job can run every minute without generating a duplicate invoice every minute. State,
        not a run marker: re-running the job is a no-op because the invoice it would create
        already exists.
        """
        raise NotImplementedError

    @abstractmethod
    async def latest_paid_period_end(self, subscription_id: SubscriptionId) -> date | None:
        """The furthest `period_end` of any *paid* invoice for this subscription, or `None`.

        What a payment has actually bought. `activate_subscription` compares it with the
        subscription's current period so that activating after a manual payment never extends
        the subscription past the period that payment covered (finance P0.2).
        """
        raise NotImplementedError

    @abstractmethod
    async def sum_paid_amount_between(self, *, start: datetime, end: datetime) -> float:
        """ADR-0020: "Revenue" KPI — sums `invoices.amount` for `status=paid` rows whose
        `paid_at` falls in `[start, end)`. Deliberately currency-naive (a plain sum across
        whatever `currency` values exist) — no document names a multi-currency aggregation
        rule, and this platform's actual currency situation is out of this ADR's scope to
        invent one for."""
        raise NotImplementedError

    @abstractmethod
    async def sum_issued_amount_between(self, *, start: datetime, end: datetime) -> float:
        """Platform Finance "Invoiced" KPI — sums `invoices.amount` for every non-`void` invoice
        whose `issued_at` falls in `[start, end)`, regardless of whether it has since been paid.
        Distinct from `sum_paid_amount_between` (that answers "Collected"): an invoice issued and
        still unpaid counts here but not there, which is the whole point of keeping Invoiced and
        Collected as two separate numbers rather than one. Same currency-naive scope as
        `sum_paid_amount_between`."""
        raise NotImplementedError

    @abstractmethod
    async def sum_outstanding_amount(self, *, as_of: datetime) -> float:
        """Platform Finance "Receivables" KPI — sums `invoices.amount` for every invoice still
        `issued` (unpaid, not void) as of `as_of`. Deliberately **not** a period sum like the two
        methods above: receivables is a point-in-time balance — an invoice issued long before
        the reporting window and still unpaid is still owed today, so it must count regardless of
        when it was issued, unlike Invoiced/Collected which are genuinely period-scoped flows."""
        raise NotImplementedError


class PaymentRepository(ABC):
    @abstractmethod
    async def get(self, payment_id: PaymentId) -> Payment | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, payment: Payment) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Payment]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Backs the documented idempotency contract (API Contracts §12: "a repeat with the
        same key returns the original result") — `ux_payments__idem` (Database Design §8.4) is
        this method's DB-level backstop, mirroring every other module's "typed application
        check + DB unique constraint" defense-in-depth pattern (e.g.
        `fleet_device.application.validators.ensure_terminal_id_available`)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_provider_ref(self, provider: str, provider_ref: str) -> Payment | None:
        """ADR-0022: resolves the webhook route's own `PaymentCallbackCommand.payment_id` from
        the provider's own reference id (a Stripe webhook payload names only its own
        `payment_intent.id`, never this system's internal ULID). `ux_payments__provider_
        provider_ref` (Database Design §8.4, `infra/models.py`) is this method's DB-level
        backstop, the same defense-in-depth pattern `get_by_idempotency_key` above already
        establishes."""
        raise NotImplementedError
