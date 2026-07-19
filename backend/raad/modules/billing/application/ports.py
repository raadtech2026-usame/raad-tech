"""Outbound ports the `billing` application layer depends on (Backend LLD §4.2). `UnitOfWork`
is the existing core abstraction (`core.db.unit_of_work`), extended here with `billing`'s own
repositories, mirroring `transport_ops.application.ports.TransportOpsUnitOfWork` exactly.

**`PaymentProviderPort` — LLD §4.2 names this interface verbatim** (`interface
PaymentProviderPort   # → EVC Plus adapter`), listed alongside `DeviceCommandPort`/
`VideoSignalingPort`/`PushSenderPort` — all module-specific ports living in their owning
module's own `application/ports.py` (the same placement `tracking.application.ports.
LatestPositionPort` already establishes for an analogous module-specific external dependency),
not a shared `core/` port.

`charge()`'s signature is derived from Phase-2 §20.2's sequence diagram, the only place its
actual usage is described: `"PS->>EVC: Payment request"` following `"API->>PS: Charge request
(amount, msisdn, ref)"`, then `"Async result (success/fail) via callback"` — three inputs,
returning the provider's own reference token synchronously (the request-accepted
acknowledgment API Contracts §4.7's documented payment response shows:
`{"payment_id":...,"status":"processing","required_action":"AWAIT_PHONE_CONFIRMATION"}`); the
actual success/fail outcome arrives later via the separate, asynchronous
`POST /billing/payments/callback` webhook, not this method's return value. No concrete
implementation of this port exists this phase — see `infra/adapters.py`'s own docstring (a
module docstring only; no `EvcPlusPaymentAdapter` class is defined there) for why.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
    TransportFeeRepository,
)
from raad.modules.billing.domain.value_objects import Money


class PaymentProviderPort(ABC):
    """Phase-2 §20.1: "provider-agnostic behind a payment-provider interface; EVC Plus is the
    first adapter" — this port is that interface, EVC-Plus-unaware by design (the Anti-
    Corruption Layer LLD §6.3 describes: "the domain never sees a provider-specific field")."""

    @abstractmethod
    async def charge(self, *, amount: Money, msisdn: str, reference: str) -> str:
        """Initiates a charge; returns the provider's own reference/transaction id
        (`payments.provider_ref`, Database Design §8.4). Does not itself resolve success or
        failure — that arrives later via the provider's signed webhook callback (Phase-2
        §20.2/§20.4)."""
        raise NotImplementedError


class BillingUnitOfWork(UnitOfWork):
    """Bundles this module's five repositories onto one transaction boundary (LLD §8.2 contract
    skeleton style), mirroring `TransportOpsUnitOfWork`'s identical shape. The concrete
    implementation is `infra.repositories.SqlAlchemyBillingUnitOfWork`.
    """

    plans: PlanRepository
    subscriptions: SubscriptionRepository
    invoices: InvoiceRepository
    payments: PaymentRepository
    transport_fees: TransportFeeRepository
