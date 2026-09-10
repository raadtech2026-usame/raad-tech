"""Platform finance value objects (ADR-0040 §1). Immutable, equality-by-value, framework-free.

**This module is the Vendor/Employee -> RAAD money flow: RAAD's own operating costs and
non-subscription income.** It is the third and last financial domain, and it is deliberately
neither of the other two:

    billing          RAAD   -> Organization   (SaaS revenue)
    school_erp       Org    -> Student        (school finance)
    platform_finance Vendor -> RAAD           (operating cost)   <- this module

**Platform-scoped, not tenant-scoped.** Nothing here carries `organization_id`, exactly like
`plans`, `regions` and `device_inventory`. That absence is the structural guarantee that no
organization can ever read RAAD's internal costs: there is no tenant column for a scope filter to
match, and no `org_admin` grant exists in the `platform_finance.*` namespace.

`Money` is `Decimal`-backed here for the same reason `school_erp` chose it — see that module's
own `Money` docstring. The duplication across modules is deliberate
(`.claude/rules/backend.md` #1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _validate_ulid(value: str, field: str) -> str:
    if not _ULID_PATTERN.match(value):
        raise DomainError(f"{field} must be a 26-character ULID: {value!r}")
    return value


@dataclass(frozen=True)
class PlatformCategoryId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "PlatformCategoryId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PlatformExpenseId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "PlatformExpenseId")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PlatformIncomeId:
    value: str

    def __post_init__(self) -> None:
        _validate_ulid(self.value, "PlatformIncomeId")

    def __str__(self) -> str:
        return self.value


class PlatformCategoryKind(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class PlatformCategoryStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ExpenseKind(str, Enum):
    """RAAD's own operating cost headings, exactly the set the requirement names.

    A closed enum *alongside* the free-form `PlatformFinancialCategory` tree, not instead of it:
    the enum is what makes "how much did we spend on salaries this year" answerable across every
    deployment without depending on how one operator happened to name their categories, while the
    category tree stays available for the finer breakdown underneath it. `OTHER` is the escape
    hatch, so an unanticipated cost is filed honestly rather than mislabelled as one of the above.
    """

    SALARIES = "salaries"
    RENT = "rent"
    ELECTRICITY = "electricity"
    WATER = "water"
    INTERNET = "internet"
    EQUIPMENT = "equipment"
    MAINTENANCE = "maintenance"
    FUEL = "fuel"
    MARKETING = "marketing"
    TRAVEL = "travel"
    SOFTWARE = "software"
    PROFESSIONAL_FEES = "professional_fees"
    TAXES = "taxes"
    OTHER = "other"


class PlatformIncomeKind(str, Enum):
    """Where RAAD's money comes from.

    `SUBSCRIPTION` exists as a heading but is **never** written by this module: subscription
    revenue is `billing`'s, and recording it here as well would double-count it against the same
    payments. It is present so the Platform P&L can *label* the revenue line it reads from
    `billing`, keeping one vocabulary across both — see `PlatformFinanceApplicationService`.
    """

    SUBSCRIPTION = "subscription"
    HARDWARE_SALE = "hardware_sale"
    INSTALLATION = "installation"
    SUPPORT_CONTRACT = "support_contract"
    GRANT = "grant"
    OTHER = "other"


@dataclass(frozen=True)
class Money:
    """`Decimal`-backed, quantised to two places at construction. See module docstring."""

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

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
