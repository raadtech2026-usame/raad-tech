"""billing: create plans, subscriptions, invoices, payments, transport_fees tables

Revision ID: addb6114f18a
Revises: acfa30ebf4d8
Create Date: 2026-07-20 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "addb6114f18a"
down_revision: Union[str, None] = "acfa30ebf4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- plans (Database Design §8.1) - no organization_id, not tenant-owned -------------
    op.create_table(
        "plans",
        sa.Column("name", sa.VARCHAR(length=160), nullable=False),
        sa.Column(
            "billing_scope",
            sa.Enum("organization", "parent", name="billing_scope"),
            nullable=False,
        ),
        sa.Column("price_amount", sa.DECIMAL(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "billing_cycle",
            sa.Enum("monthly", "quarterly", "annual", name="billing_cycle"),
            nullable=False,
        ),
        sa.Column("vehicle_limit", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.Enum("active", "inactive", name="plan_status"), nullable=False
        ),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
    )
    op.create_index(op.f("ix_plans__status"), "plans", ["status"], unique=False)

    # --- subscriptions (Database Design §8.2) -------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column(
            "subscriber_type",
            sa.Enum("organization", "parent", name="subscriber_type"),
            nullable=False,
        ),
        sa.Column("subscriber_id", sa.CHAR(length=26), nullable=False),
        sa.Column("plan_id", sa.CHAR(length=26), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "trial", "active", "suspended", "expired", "cancelled",
                name="subscription_status",
            ),
            nullable=False,
        ),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_subscriptions__plans")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        op.f("ix_subscriptions__organization_id"), "subscriptions", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_subscriptions__subscriber_id"), "subscriptions", ["subscriber_id"], unique=False
    )
    op.create_index(
        op.f("ix_subscriptions__plan_id"), "subscriptions", ["plan_id"], unique=False
    )
    op.create_index(op.f("ix_subscriptions__status"), "subscriptions", ["status"], unique=False)
    op.create_index(
        op.f("ix_subscriptions__current_period_end"),
        "subscriptions",
        ["current_period_end"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions__subscriber_type_subscriber_id_status",
        "subscriptions",
        ["subscriber_type", "subscriber_id", "status"],
        unique=False,
    )

    # --- invoices (Database Design §8.3) --------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("subscription_id", sa.CHAR(length=26), nullable=False),
        sa.Column("number", sa.VARCHAR(length=64), nullable=False),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "issued", "paid", "void", name="invoice_status"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], name=op.f("fk_invoices__subscriptions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("number", name=op.f("ux_invoices__number")),
    )
    op.create_index(
        op.f("ix_invoices__organization_id"), "invoices", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_invoices__subscription_id"), "invoices", ["subscription_id"], unique=False
    )
    op.create_index(op.f("ix_invoices__status"), "invoices", ["status"], unique=False)

    # --- payments (Database Design §8.4) - UlidPrimaryKeyMixin only, no full audit bundle --
    op.create_table(
        "payments",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("invoice_id", sa.CHAR(length=26), nullable=False),
        sa.Column("provider", sa.VARCHAR(length=40), nullable=False),
        sa.Column("provider_ref", sa.VARCHAR(length=120), nullable=True),
        sa.Column("msisdn_masked", sa.VARCHAR(length=32), nullable=True),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "paid", "failed", "expired", "refunded",
                name="payment_status",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], name=op.f("fk_payments__invoices")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint(
            "provider", "provider_ref", name="ux_payments__provider_provider_ref"
        ),
        sa.UniqueConstraint("idempotency_key", name=op.f("ux_payments__idempotency_key")),
    )
    op.create_index(
        op.f("ix_payments__organization_id"), "payments", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_payments__invoice_id"), "payments", ["invoice_id"], unique=False)
    op.create_index(op.f("ix_payments__status"), "payments", ["status"], unique=False)

    # --- transport_fees (Database Design §8.5) --------------------------------------------
    op.create_table(
        "transport_fees",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("student_id", sa.CHAR(length=26), nullable=False),
        sa.Column("period", sa.VARCHAR(length=20), nullable=False),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum("due", "paid", "overdue", "waived", name="transport_fee_status"),
            nullable=False,
        ),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transport_fees")),
    )
    op.create_index(
        op.f("ix_transport_fees__organization_id"), "transport_fees", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_transport_fees__student_id"), "transport_fees", ["student_id"], unique=False
    )
    op.create_index(
        op.f("ix_transport_fees__status"), "transport_fees", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transport_fees__status"), table_name="transport_fees")
    op.drop_index(op.f("ix_transport_fees__student_id"), table_name="transport_fees")
    op.drop_index(op.f("ix_transport_fees__organization_id"), table_name="transport_fees")
    op.drop_table("transport_fees")

    op.drop_index(op.f("ix_payments__status"), table_name="payments")
    op.drop_index(op.f("ix_payments__invoice_id"), table_name="payments")
    op.drop_index(op.f("ix_payments__organization_id"), table_name="payments")
    op.drop_table("payments")

    op.drop_index(op.f("ix_invoices__status"), table_name="invoices")
    op.drop_index(op.f("ix_invoices__subscription_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices__organization_id"), table_name="invoices")
    op.drop_table("invoices")

    op.drop_index(
        "ix_subscriptions__subscriber_type_subscriber_id_status", table_name="subscriptions"
    )
    op.drop_index(op.f("ix_subscriptions__current_period_end"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions__status"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions__plan_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions__subscriber_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions__organization_id"), table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index(op.f("ix_plans__status"), table_name="plans")
    op.drop_table("plans")

    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one.
    # `autogenerate` does not emit this; added by hand (see 8ffa6434d344/71b67f0e5709/
    # 17753b338730/acfa30ebf4d8 for the same fix).
    sa.Enum(name="transport_fee_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="invoice_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="subscription_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="subscriber_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plan_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="billing_cycle").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="billing_scope").drop(op.get_bind(), checkfirst=True)
