"""School ERP value objects (ADR-0038 §2, ADR-0040 §2). Immutable, equality-by-value,
framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises `DomainError`
(`core.errors.exceptions`), mirroring every other module's identical convention.

**This module is the Organization -> Student money flow, and only that.** ADR-0038 §2 and
ADR-0039 make the separation from `billing` (RAAD -> Organization) a security boundary rather
than a modelling preference: two `Invoice`-shaped aggregates exist deliberately and must never be
consolidated. Nothing here imports from `raad.modules.billing`, and nothing there imports from
here.

**Cross-module references stay opaque, never re-validated.** `organization_id`, `student_id`,
`route_id`, `vehicle_id` and `driver_id` all point at aggregates owned by other modules, so they
are format-validated strings with no existence check — `.claude/rules/backend.md` #3 forbids the
cross-module DB read that checking them would require. This is the same posture
`transport_ops.Trip.vehicle_id` and `billing.OrganizationId` already establish.

**`Money` is duplicated here rather than imported from `billing`.** `.claude/rules/backend.md` #1
allows a module to import only another module's `__init__` facade, and a value object is not a
facade export. The duplication is deliberate and is the same call every module in this codebase
already makes for `_AggregateRoot` and `OrganizationId`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

#: `YYYY-MM` — the billing period a student invoice covers. A month is the only period the
#: requirement names ("Monthly fee"), and keeping it a formatted string rather than a date range
#: is what makes "has this student already been invoiced for March?" a unique-constraint check
#: rather than an overlap query.
_PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_ulid(value: str, field: str) -> str:
    if not _ULID_PATTERN.match(value):
        raise DomainError(f"{field} must be a 26-character ULID: {value!r}")
    return value


@dataclass(frozen=True)
class OrganizationId:
    """Cross-module reference to an `organization.Organization` — opaque, non-empty only."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StudentId:
    """Cross-module reference to a `transport_ops.Student`."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("StudentId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RouteId:
    """Cross-module reference to a `transport_ops.Route`, captured on an invoice at issue time
    (ADR-0040 §3) so a bill remains a historical record of the transport it was for."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("RouteId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class VehicleId:
    """Cross-module reference to a `fleet_device.Vehicle`."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("VehicleId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class DriverId:
    """Cross-module reference to a `transport_ops.Driver`."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("DriverId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class FinancialCategoryId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "FinancialCategoryId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class FeePlanId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "FeePlanId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StudentInvoiceId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "StudentInvoiceId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StudentPaymentId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "StudentPaymentId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class IncomeId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "IncomeId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ExpenseId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "ExpenseId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ParentId:
    """Cross-module reference to a `transport_ops.Parent` — opaque, format-validated only, the
    identical posture `StudentId` above already establishes (`.claude/rules/backend.md` #3: no
    cross-module DB read to existence-check it)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("ParentId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ParentBillingProfileId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "ParentBillingProfileId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ParentInvoiceId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "ParentInvoiceId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ParentInvoiceLineId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "ParentInvoiceLineId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class BillingPeriod:
    """`YYYY-MM`. One month is the only period the ERP charter names, and a formatted string
    makes "already invoiced for this period" a unique constraint rather than a range query."""

    value: str

    def __post_init__(self) -> None:
        if not _PERIOD_PATTERN.match(self.value):
            raise DomainError(f"BillingPeriod must be YYYY-MM: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class CategoryKind(str, Enum):
    """Which side of the ledger a `FinancialCategory` classifies. One tree, two kinds, rather
    than two tables — a category is the same shape either way, and the kind is what keeps an
    expense from being filed under an income heading."""

    INCOME = "income"
    EXPENSE = "expense"


class CategoryStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class FeePlanStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class StudentInvoiceStatus(str, Enum):
    """Five states. `PARTIALLY_PAID` is first-class rather than derived, because the requirement
    names partial payments explicitly and because a stored state keeps "who still owes" an
    indexable column comparison instead of a correlated sum (ADR-0040 §2).

    `CANCELLED` covers both a voided bill and the waiver `transport_fees.waived` used to mean —
    the migration maps that value here.
    """

    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class ParentBillingProfileStatus(str, Enum):
    """Whether a Parent Billing Profile is currently picked up by monthly generation.
    `INACTIVE` is how an organization stops billing a family (a withdrawn child, a fee waiver)
    without deleting the profile's own history of what it used to charge."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class ParentInvoiceStatus(str, Enum):
    """Exactly the three user-facing states Part 9 of the 2026-09-11 directive specifies, plus
    `CANCELLED` for a voided/erroneously-generated invoice — the same fourth-state precedent
    `StudentInvoiceStatus.CANCELLED` already establishes for an identical need. There is no
    `PARTIALLY_PAID`-vs-`PARTIAL` naming mismatch to reconcile with `StudentInvoiceStatus`
    deliberately: this is a new, independent status set, not a renamed copy of the old one."""

    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"
    CANCELLED = "cancelled"


class StudentPaymentMethod(str, Enum):
    """How a school received money from a family. Deliberately a closed enum of the methods this
    market actually uses — `MOBILE_MONEY` covers EVC Plus/Zaad, which Phase 2 §20 names, without
    binding the ERP to a specific provider integration that does not exist."""

    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    CHEQUE = "cheque"
    CARD = "card"
    OTHER = "other"


@dataclass(frozen=True)
class Money:
    """`amount`/`currency` column pair, as `Decimal` — never `float`.

    ADR-0038 §3 requires ERP to reuse "`Money`/`NUMERIC` monetary representation (no floats,
    ever)". `billing.Money` predates that instruction and stores a `float`; this one does not
    repeat it, because school finance sums thousands of small student payments where binary
    floating point accumulates visible error. `Decimal` in, `NUMERIC(12,2)` on disk, quantised to
    two places at construction so every stored amount is already exact.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise DomainError(f"Money amount must be a Decimal, got {type(self.amount).__name__}")
        if self.amount < 0:
            raise DomainError(f"Money amount must not be negative: {self.amount}")
        if len(self.currency) != 3:
            raise DomainError(
                f"Money currency must be a 3-letter ISO 4217 code: {self.currency!r}"
            )
        # `object.__setattr__` because the dataclass is frozen; quantising here means no caller
        # can persist a third decimal place that the NUMERIC(12,2) column would silently round.
        # ROUND_HALF_UP explicitly, not `quantize`'s default. Python defaults to
        # ROUND_HALF_EVEN (banker's rounding), which turns 10.005 into 10.00 — defensible
        # statistically, but not what a bursar typing an invoice amount expects, and not what
        # every other system a school reconciles against will do. Stated rather than inherited,
        # because a silent rounding convention is the kind of thing nobody discovers until two
        # ledgers disagree by a cent.
        object.__setattr__(
            self, "amount", self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        object.__setattr__(self, "currency", self.currency.upper())

    def add(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise DomainError(
                f"Cannot combine {self.currency} with {other.currency} — "
                "amounts in different currencies are never summed"
            )

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
