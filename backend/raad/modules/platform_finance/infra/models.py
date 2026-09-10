"""Platform finance ORM models (ADR-0040 §1). SQLAlchemy confined to infra; PostgreSQL only.

**No table here carries `organization_id`, and that is load-bearing.** These are RAAD's own
books. `SqlAlchemyRepositoryBase._apply_scope` guards its tenant filter with
`hasattr(model, "organization_id")`, so the absence of the column means no tenant filter is ever
applied — which is correct, because there is no tenant. The isolation that matters here is RBAC:
only `founder` and `finance_staff` hold any `platform_finance.*` permission (ADR-0040 §7), and no
`org_admin` grant exists in the namespace at all.

Table names are prefixed `platform_` for the same reason `school_erp` uses `erp_`: three
financial domains coexist in one schema and the prefix makes which is which visible in `\\dt`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, DATE, DECIMAL, VARCHAR, Boolean, ForeignKey, Index, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_CATEGORY_KIND_VALUES = ("income", "expense")
_CATEGORY_STATUS_VALUES = ("active", "inactive")
_EXPENSE_KIND_VALUES = (
    "salaries",
    "rent",
    "electricity",
    "water",
    "internet",
    "equipment",
    "maintenance",
    "fuel",
    "marketing",
    "travel",
    "software",
    "professional_fees",
    "taxes",
    "other",
)
_INCOME_KIND_VALUES = (
    "subscription",
    "hardware_sale",
    "installation",
    "support_contract",
    "grant",
    "other",
)


class PlatformFinancialCategoryModel(AuditedTableMixin, Base):
    __tablename__ = "platform_financial_categories"

    name: Mapped[str] = mapped_column(VARCHAR(160), nullable=False)
    kind: Mapped[str] = mapped_column(
        SqlEnum(*_CATEGORY_KIND_VALUES, name="platform_category_kind"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_CATEGORY_STATUS_VALUES, name="platform_category_status"), nullable=False
    )

    __table_args__ = (Index("ix_platform_financial_categories__kind", "kind"),)


class PlatformExpenseModel(AuditedTableMixin, Base):
    __tablename__ = "platform_expenses"

    kind: Mapped[str] = mapped_column(
        SqlEnum(*_EXPENSE_KIND_VALUES, name="platform_expense_kind"), nullable=False
    )
    category_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("platform_financial_categories.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(DATE, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor: Mapped[str | None] = mapped_column(VARCHAR(160), nullable=True)
    reference: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    #: Nullable and never populated yet — no upload endpoint or blob store exists (ADR-0040
    #: Consequences). Present so adding one later is additive.
    attachment_url: Mapped[str | None] = mapped_column(VARCHAR(500), nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_platform_expenses__occurred_kind", "occurred_on", "kind"),
    )


class PlatformIncomeModel(AuditedTableMixin, Base):
    __tablename__ = "platform_income"

    kind: Mapped[str] = mapped_column(
        SqlEnum(*_INCOME_KIND_VALUES, name="platform_income_kind"), nullable=False
    )
    category_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("platform_financial_categories.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(DATE, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(VARCHAR(160), nullable=True)
    reference: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_platform_income__occurred_kind", "occurred_on", "kind"),
    )
