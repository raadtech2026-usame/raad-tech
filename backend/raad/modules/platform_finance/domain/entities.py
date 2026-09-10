"""Platform finance aggregates (ADR-0040 §1). Framework-free — no SQLAlchemy/Pydantic/FastAPI,
no I/O.

Three aggregates for the Vendor/Employee -> RAAD money flow: `PlatformFinancialCategory`,
`PlatformExpense`, `PlatformIncome`.

**No `organization_id` anywhere in this file.** That is the point — see `value_objects.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid
from raad.core.time.clock import Clock
from raad.modules.platform_finance.domain.value_objects import (
    ExpenseKind,
    Money,
    PlatformCategoryId,
    PlatformCategoryKind,
    PlatformCategoryStatus,
    PlatformExpenseId,
    PlatformIncomeId,
    PlatformIncomeKind,
)

_MAX_NAME = 160
_MAX_DESCRIPTION = 500
_ZERO = Decimal("0.00")


class _AggregateRoot:
    """Duplicated per module deliberately (`.claude/rules/backend.md` #1)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


def _event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict,
) -> DomainEvent:
    """`org_id` is always `None` here — platform finance is not tenant-owned, and stamping a
    tenant onto these events would make them look scoped when they are not."""
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=None,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


def _validate_name(name: str) -> None:
    if not name or not name.strip():
        raise DomainError("name must not be empty")
    if len(name) > _MAX_NAME:
        raise DomainError(f"name must be at most {_MAX_NAME} characters")


def _validate_description(description: str | None) -> None:
    if description is not None and len(description) > _MAX_DESCRIPTION:
        raise DomainError(f"description must be at most {_MAX_DESCRIPTION} characters")


class PlatformFinancialCategory(_AggregateRoot):
    """`platform_financial_categories` — RAAD's own income/expense classification tree."""

    def __init__(
        self,
        *,
        id: PlatformCategoryId,
        name: str,
        kind: PlatformCategoryKind,
        description: str | None,
        status: PlatformCategoryStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_name(name)
        _validate_description(description)
        self.id = id
        self.name = name
        self.kind = kind
        self.description = description
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PlatformFinancialCategory) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: PlatformCategoryId,
        name: str,
        kind: PlatformCategoryKind,
        description: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "PlatformFinancialCategory":
        now = clock.now()
        category = cls(
            id=id,
            name=name,
            kind=kind,
            description=description,
            status=PlatformCategoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        category._record(
            _event(
                event_type="platform_finance.CategoryCreated",
                aggregate_type="PlatformFinancialCategory",
                aggregate_id=str(id),
                occurred_at=now,
                payload={"category_id": str(id), "name": name, "kind": kind.value,
                         "actor_id": actor_id},
            )
        )
        return category

    def archive(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == PlatformCategoryStatus.INACTIVE:
            return
        self.status = PlatformCategoryStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            _event(
                event_type="platform_finance.CategoryArchived",
                aggregate_type="PlatformFinancialCategory",
                aggregate_id=str(self.id),
                occurred_at=self.updated_at,
                payload={"category_id": str(self.id), "actor_id": actor_id},
            )
        )


class PlatformExpense(_AggregateRoot):
    """`platform_expenses` — what RAAD spends to operate.

    Carries both a closed `kind` (salaries, rent, electricity, ...) and an optional free-form
    `category_id`. The enum is what makes cost-by-heading comparable across deployments; the
    category is the operator's own finer breakdown underneath it. See `ExpenseKind`.
    """

    def __init__(
        self,
        *,
        id: PlatformExpenseId,
        kind: ExpenseKind,
        category_id: PlatformCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None,
        vendor: str | None,
        reference: str | None,
        attachment_url: str | None,
        is_voided: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Expense amount must be greater than zero")
        self.id = id
        self.kind = kind
        self.category_id = category_id
        self.amount = amount
        self.occurred_on = occurred_on
        self.description = description
        self.vendor = vendor
        self.reference = reference
        self.attachment_url = attachment_url
        self.is_voided = is_voided
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PlatformExpense) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: PlatformExpenseId,
        kind: ExpenseKind,
        category_id: PlatformCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None = None,
        vendor: str | None = None,
        reference: str | None = None,
        attachment_url: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "PlatformExpense":
        now = clock.now()
        expense = cls(
            id=id,
            kind=kind,
            category_id=category_id,
            amount=amount,
            occurred_on=occurred_on,
            description=description,
            vendor=vendor,
            reference=reference,
            attachment_url=attachment_url,
            is_voided=False,
            created_at=now,
            updated_at=now,
        )
        expense._record(
            _event(
                event_type="platform_finance.ExpenseRecorded",
                aggregate_type="PlatformExpense",
                aggregate_id=str(id),
                occurred_at=now,
                payload={
                    "expense_id": str(id),
                    "kind": kind.value,
                    "amount": str(amount.amount),
                    "currency": amount.currency,
                    "occurred_on": occurred_on.isoformat(),
                    "actor_id": actor_id,
                },
            )
        )
        return expense

    def void(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.is_voided:
            return
        self.is_voided = True
        self.updated_at = clock.now()
        self._record(
            _event(
                event_type="platform_finance.ExpenseVoided",
                aggregate_type="PlatformExpense",
                aggregate_id=str(self.id),
                occurred_at=self.updated_at,
                payload={"expense_id": str(self.id), "reason": reason, "actor_id": actor_id},
            )
        )


class PlatformIncome(_AggregateRoot):
    """`platform_income` — RAAD income that is **not** subscription revenue.

    Subscription revenue lives in `billing` and is read from there by the Platform P&L. Recording
    it here as well would double-count the same payments against themselves, so
    `PlatformIncomeKind.SUBSCRIPTION` is rejected on write — the one heading this table refuses.
    """

    def __init__(
        self,
        *,
        id: PlatformIncomeId,
        kind: PlatformIncomeKind,
        category_id: PlatformCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None,
        source: str | None,
        reference: str | None,
        is_voided: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Income amount must be greater than zero")
        if kind is PlatformIncomeKind.SUBSCRIPTION:
            raise DomainError(
                "Subscription revenue is owned by the billing module and is read from there — "
                "recording it here would double-count the same payments."
            )
        self.id = id
        self.kind = kind
        self.category_id = category_id
        self.amount = amount
        self.occurred_on = occurred_on
        self.description = description
        self.source = source
        self.reference = reference
        self.is_voided = is_voided
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PlatformIncome) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: PlatformIncomeId,
        kind: PlatformIncomeKind,
        category_id: PlatformCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None = None,
        source: str | None = None,
        reference: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "PlatformIncome":
        now = clock.now()
        income = cls(
            id=id,
            kind=kind,
            category_id=category_id,
            amount=amount,
            occurred_on=occurred_on,
            description=description,
            source=source,
            reference=reference,
            is_voided=False,
            created_at=now,
            updated_at=now,
        )
        income._record(
            _event(
                event_type="platform_finance.IncomeRecorded",
                aggregate_type="PlatformIncome",
                aggregate_id=str(id),
                occurred_at=now,
                payload={
                    "income_id": str(id),
                    "kind": kind.value,
                    "amount": str(amount.amount),
                    "currency": amount.currency,
                    "occurred_on": occurred_on.isoformat(),
                    "actor_id": actor_id,
                },
            )
        )
        return income

    def void(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.is_voided:
            return
        self.is_voided = True
        self.updated_at = clock.now()
        self._record(
            _event(
                event_type="platform_finance.IncomeVoided",
                aggregate_type="PlatformIncome",
                aggregate_id=str(self.id),
                occurred_at=self.updated_at,
                payload={"income_id": str(self.id), "reason": reason, "actor_id": actor_id},
            )
        )
