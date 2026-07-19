"""Billing value objects (Backend LLD §5.1; Database Design §8.1-§8.5; ADR-0001: `billing` owns
`Subscription`/`Plan`/`Invoice`/`Payment`/`TransportFee`, Phase-2 §2.1's C8 row). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`), mirroring every other module's identical convention.

**Phase 15 scope: all five documented aggregates in one phase** (unlike `transport_ops`'s
incremental one-aggregate-per-phase build-out) — this phase's own task explicitly scopes
"the complete Billing bounded context... end-to-end in a single implementation."

**Cross-module references stay opaque, never re-validated.** `organization_id` (every table),
`subscriber_id` when `subscriber_type=parent` (→ `transport_ops.Parent`), and
`transport_fees.student_id` (→ `transport_ops.Student`) are cross-module references — opaque,
non-empty strings only, the same treatment `transport_ops.domain.value_objects.VehicleId`
already establishes for its own cross-module reference to `fleet_device.Vehicle`
(`.claude/rules/database.md` #3). `SubscriberId` covers both `subscriber_type` cases
(`organization` or `parent`) with one opaque type — which aggregate it actually names is a
runtime fact carried by the sibling `subscriber_type` field, not encoded in the id's own shape
(Database Design §8.2 gives `subscriber_id` no distinct format per type).

**`plan_id` / `subscription_id` / `invoice_id` are in-context references** — `Plan`,
`Subscription`, `Invoice`, `Payment` are all owned by this same `billing` module, so these reuse
this file's own module-owned id types directly (`PlanId`, `SubscriptionId`, `InvoiceId`), never
re-declared as opaque strings, mirroring `transport_ops`'s identical in-context-vs-cross-module
split (e.g. `Trip.route_id: RouteId` vs `Trip.vehicle_id: VehicleId`).

**Undocumented enum values, flagged per-field, not guessed silently:**
- `PlanStatus` — Database Design §8.1 gives the column name (`status`) but **no enumerated
  values** (unlike every other status field in that table's compact notation). Mirrors
  `transport_ops.domain.value_objects.ParentStatus`'s identical situation: the simplest
  defensible choice, a flat `active`/`inactive` toggle, not an invented richer lifecycle.
- Every other enum here (`BillingScope`, `BillingCycle`, `SubscriberType`, `SubscriptionStatus`,
  `InvoiceStatus`, `PaymentStatus`, `TransportFeeStatus`) **is** explicitly spelled out in
  Database Design §8.1-§8.5 and used verbatim.

**`InvoiceStatus` has no `failed` value — flagged, not invented.** Phase-2 §20.2's payment
workflow narrative says "Mark Invoice FAILED" on a declined/timeout payment, but Database Design
§8.3 gives `invoices.status ENUM(draft,issued,paid,void)` — no `failed` member exists. Treated
here as a documentation imprecision in the narrative text, not a fourth status this schema
supports: on payment failure, `Payment.mark_failed()` records the failure (`payments.status`
*does* have `failed`) and the invoice is left unchanged (still `issued`, awaiting a further
attempt) — see `entities.py`'s `Invoice`/`Payment` docstrings for the full reasoning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class OrganizationId:
    """Cross-module reference to an `Organization` aggregate owned by `organization` — opaque,
    non-empty string only (`.claude/rules/database.md` #3), mirroring every other module's
    identical `OrganizationId` treatment."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SubscriberId:
    """Cross-module reference, opaque — see module docstring. Names either an `Organization` or
    a `transport_ops.Parent`, disambiguated at the call site by `SubscriberType`, never by this
    id's own shape."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("SubscriberId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StudentId:
    """Cross-module reference to a `transport_ops.Student` — opaque, non-empty string only, the
    same treatment `SubscriberId` above gets."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("StudentId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PlanId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"PlanId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SubscriptionId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"SubscriptionId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class InvoiceId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"InvoiceId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PaymentId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"PaymentId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TransportFeeId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"TransportFeeId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class BillingScope(str, Enum):
    """Database Design §8.1: `plans.billing_scope ENUM(organization,parent)` — which
    `SubscriberType` a plan is meant to be purchased by."""

    ORGANIZATION = "organization"
    PARENT = "parent"


class BillingCycle(str, Enum):
    """Database Design §8.1: `plans.billing_cycle ENUM(monthly,quarterly,annual)`."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class PlanStatus(str, Enum):
    """Database Design §8.1 names the `status` column but not its values — flagged in module
    docstring. Flat `active`/`inactive` toggle, mirroring `ParentStatus`'s identical precedent
    for an equally undocumented-values status field."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class SubscriberType(str, Enum):
    """Database Design §8.2: `subscriptions.subscriber_type ENUM(organization,parent)` — "maps
    to billing_model (CR-1)"."""

    ORGANIZATION = "organization"
    PARENT = "parent"


class SubscriptionStatus(str, Enum):
    """Database Design §8.2: `subscriptions.status ENUM(trial,active,suspended,expired,
    cancelled)`."""

    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class InvoiceStatus(str, Enum):
    """Database Design §8.3: `invoices.status ENUM(draft,issued,paid,void)` — exhaustively four
    values; no `failed` member (see module docstring's flagged Phase-2 §20.2 narrative
    imprecision)."""

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    VOID = "void"


class PaymentStatus(str, Enum):
    """Database Design §8.4: `payments.status ENUM(pending,processing,paid,failed,expired,
    refunded)`, matching Phase-2 §20.3's state diagram exactly."""

    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"


class TransportFeeStatus(str, Enum):
    """Database Design §8.5: `transport_fees.status ENUM(due,paid,overdue,waived)`."""

    DUE = "due"
    PAID = "paid"
    OVERDUE = "overdue"
    WAIVED = "waived"


@dataclass(frozen=True)
class Money:
    """`amount`/`currency` appear together on every Billing table (`plans.price_amount`,
    `invoices.amount`, `payments.amount`, `transport_fees.amount`, each paired with a
    `currency CHAR(3)`) — grouped into one value object rather than two parallel primitive
    fields threaded through every aggregate/method, the same "small immutable VO for a
    recurring column pair" reasoning Backend LLD §5.1 itself invites (its own value-object
    list example names `Money` verbatim: "Value Objects... e.g., GeoPoint, Msisdn, Radius,
    Money"). **`Money` is therefore the one value object in this file with a directly
    documented name**, not a phase-invented one.
    """

    amount: float
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise DomainError(f"Money amount must not be negative: {self.amount}")
        if len(self.currency) != 3:
            raise DomainError(
                f"Money currency must be a 3-letter ISO 4217 code: {self.currency!r}"
            )

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
