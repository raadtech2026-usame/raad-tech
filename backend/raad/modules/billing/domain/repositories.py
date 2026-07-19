"""Repository interfaces for the `billing` module (Backend LLD §5.1/§7.1/§7.2). Framework-free
— no SQLAlchemy/FastAPI/Pydantic. No LLD-given contract skeleton exists for any of these five
(unlike `TripRepository`, which LLD §7.2 gives verbatim) — each mirrors the closest already-
completed precedent in `transport_ops.domain.repositories`.

`PlanRepository`/`SubscriptionRepository`/`InvoiceRepository`/`PaymentRepository`/
`TransportFeeRepository` — `get`/`add`/`list_all`, the same minimal shape `DriverRepository`
establishes for an aggregate with no module-owned uniqueness constraint beyond its own primary
key (none of `plans`/`subscriptions`/`invoices`/`payments`/`transport_fees` declare a `UX` on
anything other than `payments.idempotency_key`/`payments.provider_ref` and `invoices.number` —
see `PaymentRepository.get_by_idempotency_key` and `InvoiceRepository`'s own docstring below for
the two that need a dedicated finder).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
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
    async def get_active_by_subscriber(
        self, subscriber_type: SubscriberType, subscriber_id: SubscriberId
    ) -> Subscription | None:
        """Not from any LLD contract skeleton — added because `RenewParentSubscriptionCommand`
        (LLD §4.2) needs to find an existing subscription to extend rather than blindly opening
        a duplicate every renewal, and no document states whether "active" here should include
        `TRIAL` — reads it as "not `EXPIRED`/`CANCELLED`" (i.e. `TRIAL`, `ACTIVE`, or
        `SUSPENDED`), the most conservative reading that still avoids creating a second row for
        a subscriber who already has one in flight. Flagged as this phase's own interpretive
        choice, not a documented method."""
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


class TransportFeeRepository(ABC):
    @abstractmethod
    async def get(self, transport_fee_id: TransportFeeId) -> TransportFee | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, transport_fee: TransportFee) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[TransportFee]:
        """No documented API surface reaches this (`entities.py`'s `TransportFee` docstring) —
        still implemented for the same reason `Route.remove_stop`'s command/service exist
        without an HTTP route: a complete, tested use-case at the layers below the router."""
        raise NotImplementedError
