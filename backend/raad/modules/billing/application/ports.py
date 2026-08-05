"""Outbound ports the `billing` application layer depends on (Backend LLD §4.2). `UnitOfWork`
is the existing core abstraction (`core.db.unit_of_work`), extended here with `billing`'s own
repositories, mirroring `transport_ops.application.ports.TransportOpsUnitOfWork` exactly.

**`PaymentProviderPort` — LLD §4.2 names this interface verbatim** (`interface
PaymentProviderPort   # → EVC Plus adapter`), listed alongside `DeviceCommandPort`/
`VideoSignalingPort`/`PushSenderPort` — all module-specific ports living in their owning
module's own `application/ports.py` (the same placement `tracking.application.ports.
LatestPositionPort` already establishes for an analogous module-specific external dependency),
not a shared `core/` port.

**Redesigned by ADR-0022.** The original `charge(amount, msisdn, reference) -> str` signature
(derived from Phase-2 §20.2's mobile-money-specific sequence diagram) could not represent a card
provider: there is no `msisdn` for a card payment, and a raw card number must never reach this
backend at all (PCI DSS scope) — a card charge needs a client-tokenized `payment_method` id
instead. `PaymentChargeRequest` carries both fields as optional; each concrete adapter validates
that the one it actually needs is present, rather than the port forcing every provider through a
mobile-money-shaped signature. Signature verification and webhook-event parsing move onto the
port itself (`verify_webhook_signature`/`parse_webhook_event`) since every provider defines its
own scheme — there is no provider-agnostic way to check a signature generically.

Concrete adapters: `infra/adapters.py`'s `StripePaymentAdapter` (real, `httpx`-based) and
`EvcPlusPaymentAdapter`/`ZaadPaymentAdapter` (interface-complete stubs — see that module's own
docstring for why their bodies raise rather than guess at an unverified API shape).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
    TransportFeeRepository,
)
from raad.modules.billing.domain.value_objects import Money


@dataclass(frozen=True)
class PaymentChargeRequest:
    """Input to `PaymentProviderPort.charge`. `reference` is the caller's own idempotency key
    (`Payment.idempotency_key`) — adapters pass it through as the *provider's* own idempotency
    key too where the provider's API supports one (Stripe's does), so a retried `charge()` call
    on this side (e.g. after a network timeout whose actual outcome is unknown) cannot also
    double-charge on the provider's side."""

    amount: Money
    reference: str
    msisdn: str | None = None
    payment_method_token: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentChargeResult:
    """Result of `PaymentProviderPort.charge`. `"succeeded"` means the application service can
    call `Payment.mark_paid` immediately (a card charge is frequently synchronously final);
    `"pending"` means `mark_processing`, awaiting the provider's webhook callback — the same two
    outcomes Phase-2 §20.3's state diagram already names, now both reachable from one call
    instead of assuming every provider is always asynchronous."""

    provider_ref: str
    status: Literal["succeeded", "pending", "failed"]
    failure_reason: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """Result of `PaymentProviderPort.parse_webhook_event` — already verified (the caller must
    have called `verify_webhook_signature` first) and already translated out of the provider's
    own wire format into the two outcomes `handle_payment_callback` understands."""

    provider_ref: str
    status: Literal["paid", "failed"]
    failure_reason: str | None = None


class UnhandledWebhookEventError(Exception):
    """Part of `PaymentProviderPort.parse_webhook_event`'s own contract (declared here, not in
    `infra/adapters.py`, so `api/routers.py` can catch it without an API-layer-imports-infra
    violation — `.claude/rules/backend.md` #2/the architecture-gate's own Rule 5) — raised for a
    real, well-formed, correctly-signed event a concrete adapter has no handling for (e.g.
    Stripe's own `payment_intent.created`). Mainstream providers' own webhook documentation
    (Stripe's included) recommends acknowledging (`200`) any event type you don't act on, not
    erroring, since a non-2xx response makes the provider retry indefinitely — the router
    catches this specifically to do exactly that, distinct from a genuine verification/parsing
    failure."""


class PaymentProviderPort(ABC):
    """Phase-2 §20.1: "provider-agnostic behind a payment-provider interface; EVC Plus is the
    first adapter" — this port is that interface (ADR-0022's redesign, see module docstring)."""

    @abstractmethod
    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult:
        """Initiates a charge. Does not itself guarantee the final outcome when `status ==
        "pending"` — that arrives later via the provider's signed webhook callback (Phase-2
        §20.2/§20.4, `parse_webhook_event` below)."""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool:
        """Verifies a webhook request's signature against this provider's own scheme, using a
        secret held only in `PaymentSettings.provider_credentials` (env-only, ADR-0022 — never
        `SystemSetting`). Must be called, and must return `True`, before `parse_webhook_event`
        is ever trusted (`.claude/rules/security.md` #10: payment callbacks are untrusted input
        until signature/secret-verified)."""
        raise NotImplementedError

    @abstractmethod
    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent:
        """Translates an already-signature-verified webhook payload into this port's own
        provider-agnostic `WebhookEvent` shape."""
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
