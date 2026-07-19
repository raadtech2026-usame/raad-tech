"""Billing ORM models (Backend LLD §17 `db`; Database Design §8.1-§8.5). SQLAlchemy is confined
to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2). PostgreSQL types only (ADR-0002).

`PlanModel` has **no `organization_id`** — §8.1 defines `plans` with no such column at all
(platform-level, not tenant-owned; `domain/entities.py`'s `Plan` docstring explains the
reasoning). Every other table's `organization_id` is a plain indexed column, never a database
FK — cross-context reference (`.claude/rules/database.md` #3), the same treatment every other
module's own `organization_id` gets. `subscriptions.subscriber_id`
(→ `organization.Organization` or `transport_ops.Parent`, disambiguated by `subscriber_type`)
and `transport_fees.student_id` (→ `transport_ops.Student`) are likewise plain indexed columns,
never FKs — cross-module references.

`subscriptions.plan_id`, `invoices.subscription_id`, `payments.invoice_id` **are** real database
`ForeignKey`s — all three are same-module, in-context references (`plans`/`subscriptions`/
`invoices` all owned by this one `billing` module), the identical treatment
`transport_ops.infra.models.StopModel.route_id` already establishes for its own in-context
reference.

**`PaymentModel` composes `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`.** Database
Design §8.4's `payments` table lists exactly its own columns (including its own `created_at`/
`confirmed_at` pair) with no "+ standard audit cols" line — unlike `plans`/`subscriptions`/
`invoices`/`transport_fees`, which each end with one. This is the identical situation
`transport_ops.infra.models.StudentParentModel`/`fleet_device.infra.models.
DeviceAssignmentModel` already establish for a table whose own timestamp columns already serve
the audit purpose — confirmed by re-reading §8.4 in full before implementing, not assumed from
the other four tables' shape.

**No partial unique index in this file** — unlike `trips`/`student_assignments`/
`device_assignments`, no "one active X" invariant is documented anywhere for any Billing table
(`domain/entities.py`'s `Subscription` docstring flags this explicitly for `subscriptions`
specifically; no other table in this file has a documented candidate for one either). The two
plain composite indexes that *are* documented — `ix_subscriptions__subscriber` (§8.2) and
`ux_payments__provider_ref` (§8.4) — are emitted below with real column names, per
`core.db.base`'s naming convention (the same expansion `TripModel`'s own composite index
already applies over its doc's abbreviated form).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    DATE,
    DECIMAL,
    VARCHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin, UlidPrimaryKeyMixin

_BILLING_SCOPE_VALUES = ("organization", "parent")
_BILLING_CYCLE_VALUES = ("monthly", "quarterly", "annual")
_PLAN_STATUS_VALUES = ("active", "inactive")
_SUBSCRIBER_TYPE_VALUES = ("organization", "parent")
_SUBSCRIPTION_STATUS_VALUES = ("trial", "active", "suspended", "expired", "cancelled")
_INVOICE_STATUS_VALUES = ("draft", "issued", "paid", "void")
_PAYMENT_STATUS_VALUES = ("pending", "processing", "paid", "failed", "expired", "refunded")
_TRANSPORT_FEE_STATUS_VALUES = ("due", "paid", "overdue", "waived")

# Database Design §8.1 gives `plans.name` no explicit length (compact notation) - mirrors
# transport_ops.RouteModel.name's identical VARCHAR(160) precedent (`domain/entities.py`'s own
# note for the same reasoning).
_PLAN_NAME_LENGTH = 160
# §8.3 gives `invoices.number` no explicit length beyond "UX" (unique) - this file's own
# `Invoice.issue()` sets it to the invoice's own 26-char ULID id, so 64 gives headroom without
# claiming a specific documented format.
_INVOICE_NUMBER_LENGTH = 64
# §8.5 gives `transport_fees.period` no type at all - modeled as a short label
# (`domain/entities.py`'s own note); 20 chars comfortably fits e.g. "2026-07" plus headroom.
_TRANSPORT_FEE_PERIOD_LENGTH = 20


class PlanModel(AuditedTableMixin, Base):
    """`plans` (Database Design §8.1). Not tenant-owned - see module docstring."""

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(VARCHAR(_PLAN_NAME_LENGTH), nullable=False)
    billing_scope: Mapped[str] = mapped_column(
        SqlEnum(*_BILLING_SCOPE_VALUES, name="billing_scope"), nullable=False
    )
    price_amount: Mapped[float] = mapped_column(
        DECIMAL(12, 2, asdecimal=False), nullable=False
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(
        SqlEnum(*_BILLING_CYCLE_VALUES, name="billing_cycle"), nullable=False
    )
    vehicle_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_PLAN_STATUS_VALUES, name="plan_status"), nullable=False, index=True
    )


class SubscriptionModel(AuditedTableMixin, Base):
    """`subscriptions` (Database Design §8.2)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "ix_subscriptions__subscriber_type_subscriber_id_status",
            "subscriber_type",
            "subscriber_id",
            "status",
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    subscriber_type: Mapped[str] = mapped_column(
        SqlEnum(*_SUBSCRIBER_TYPE_VALUES, name="subscriber_type"), nullable=False
    )
    subscriber_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("plans.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        SqlEnum(*_SUBSCRIPTION_STATUS_VALUES, name="subscription_status"),
        nullable=False,
        index=True,
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InvoiceModel(AuditedTableMixin, Base):
    """`invoices` (Database Design §8.3)."""

    __tablename__ = "invoices"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(
        VARCHAR(_INVOICE_NUMBER_LENGTH), nullable=False, unique=True
    )
    amount: Mapped[float] = mapped_column(DECIMAL(12, 2, asdecimal=False), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    period_start: Mapped[date] = mapped_column(DATE, nullable=False)
    period_end: Mapped[date] = mapped_column(DATE, nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_INVOICE_STATUS_VALUES, name="invoice_status"), nullable=False, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class PaymentModel(UlidPrimaryKeyMixin, Base):
    """`payments` (Database Design §8.4) - see module docstring for why this composes
    `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_ref", name="ux_payments__provider_provider_ref"
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    invoice_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("invoices.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    msisdn_masked: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    amount: Mapped[float] = mapped_column(DECIMAL(12, 2, asdecimal=False), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_PAYMENT_STATUS_VALUES, name="payment_status"), nullable=False, index=True
    )
    # `CHAR(64)` is Database Design §8.4's literal column type. PostgreSQL blank-pads CHAR(n)
    # storage and returns it padded on SELECT (unlike VARCHAR) - `infra/mappers.py`'s
    # `model_to_payment` strips this back off; implemented as documented rather than silently
    # switched to VARCHAR, since the doc is unambiguous, not incomplete.
    idempotency_key: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


class TransportFeeModel(AuditedTableMixin, Base):
    """`transport_fees` (Database Design §8.5)."""

    __tablename__ = "transport_fees"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    period: Mapped[str] = mapped_column(
        VARCHAR(_TRANSPORT_FEE_PERIOD_LENGTH), nullable=False
    )
    amount: Mapped[float] = mapped_column(DECIMAL(12, 2, asdecimal=False), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_TRANSPORT_FEE_STATUS_VALUES, name="transport_fee_status"),
        nullable=False,
        index=True,
    )
