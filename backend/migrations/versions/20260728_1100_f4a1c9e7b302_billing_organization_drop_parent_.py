"""billing/organization: drop parent-billing path (ADR-0016)

Revision ID: f4a1c9e7b302
Revises: d3f7b8c2a915
Create Date: 2026-07-28 11:00:00.000000

ADR-0016 (RAAD business model realignment, Accepted 2026-07-28): "RAAD does NOT care how
schools collect money from parents. RAAD bills only Organizations." The former dual-mode
billing shape is deleted outright, not deprecated in place:

- `organizations.billing_model` (`ENUM(organization_pays,parent_pays)`) — every organization's
  billing arrangement is now implicitly "RAAD bills the Organization," so there is nothing left
  to record per-row. Column and its `billing_model` PostgreSQL `ENUM` type are dropped.
- `subscriptions.subscriber_type`/`subscriber_id` (the former polymorphic
  organization-or-parent subscriber) — `Subscription` now keys on its already-existing
  `organization_id` column alone. Both columns, their indexes
  (`ix_subscriptions__subscriber_id`, the composite
  `ix_subscriptions__subscriber_type_subscriber_id_status`), and the `subscriber_type`
  PostgreSQL `ENUM` type are dropped; a new `ix_subscriptions__organization_id_status`
  composite index replaces the dropped composite (mirrors what it indexed, `organization_id`
  now standing in for `subscriber_type`+`subscriber_id`).

**`plans.billing_scope` is deliberately NOT touched by this migration**, even though ADR-0016's
own Decision section also names `BillingScope`'s parent-facing value as removed at the
domain-enum level (`billing/domain/value_objects.py`'s `BillingScope` now has only
`ORGANIZATION`). The ADR's own explicit migration paragraph lists exactly `organizations.
billing_model` and `subscriptions.subscriber_type`/`subscriber_id` as the columns a migration
drops — narrowing the existing `billing_scope` PostgreSQL `ENUM` type's allowed values in place
is a materially different, riskier operation (recreate-the-type-and-every-dependent-column, since
PostgreSQL has no `ALTER TYPE ... DROP VALUE`) that no document asks for here. The application
layer simply never writes `'parent'` into that column again — an accepted, flagged gap, not a
silent one.

**Backfill:** none needed for the drop direction — every existing row in this pre-production
database is already `organization_pays`/`organization`-typed (ADR-0016's own Consequences
section). The reverse (`downgrade()`) direction re-adds `billing_model`/`subscriber_type` with a
server-side default matching that same fact (`organization_pays`/`organization`) so existing
rows backfill cleanly, and backfills `subscriber_id` from each subscription's own
`organization_id` (the only value that was ever meaningful for an `organization`-typed
subscriber) before restoring its `NOT NULL` constraint — mirroring
`b6f2a19d3e7c`'s identical "server_default only for the backfill, dropped immediately after"
discipline for the two enum-typed columns.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f4a1c9e7b302"
down_revision: Union[str, None] = "d3f7b8c2a915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- subscriptions: drop subscriber_type/subscriber_id -----------------------------------
    op.drop_index(
        "ix_subscriptions__subscriber_type_subscriber_id_status",
        table_name="subscriptions",
    )
    op.drop_index(
        op.f("ix_subscriptions__subscriber_id"), table_name="subscriptions"
    )
    op.create_index(
        "ix_subscriptions__organization_id_status",
        "subscriptions",
        ["organization_id", "status"],
        unique=False,
    )
    op.drop_column("subscriptions", "subscriber_id")
    op.drop_column("subscriptions", "subscriber_type")
    sa.Enum(name="subscriber_type").drop(op.get_bind(), checkfirst=True)

    # --- organizations: drop billing_model --------------------------------------------------
    op.drop_column("organizations", "billing_model")
    sa.Enum(name="billing_model").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # --- organizations: restore billing_model -------------------------------------------------
    # `op.add_column` alone only emits ALTER TABLE ... ADD COLUMN — unlike `op.create_table`,
    # it never emits the type's own CREATE TYPE first, so the native ENUM type must be created
    # explicitly (`create_type=False` on the column below then skips re-creating it).
    billing_model_enum = sa.Enum(
        "organization_pays", "parent_pays", name="billing_model"
    )
    billing_model_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "organizations",
        sa.Column(
            "billing_model",
            sa.Enum(
                "organization_pays",
                "parent_pays",
                name="billing_model",
                create_type=False,
            ),
            nullable=False,
            server_default="organization_pays",
        ),
    )
    op.alter_column("organizations", "billing_model", server_default=None)

    # --- subscriptions: restore subscriber_type/subscriber_id ---------------------------------
    subscriber_type_enum = sa.Enum("organization", "parent", name="subscriber_type")
    subscriber_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "subscriptions",
        sa.Column(
            "subscriber_type",
            sa.Enum(
                "organization", "parent", name="subscriber_type", create_type=False
            ),
            nullable=False,
            server_default="organization",
        ),
    )
    op.alter_column("subscriptions", "subscriber_type", server_default=None)
    op.add_column(
        "subscriptions", sa.Column("subscriber_id", sa.CHAR(length=26), nullable=True)
    )
    op.execute("UPDATE subscriptions SET subscriber_id = organization_id")
    op.alter_column("subscriptions", "subscriber_id", nullable=False)

    op.drop_index("ix_subscriptions__organization_id_status", table_name="subscriptions")
    op.create_index(
        op.f("ix_subscriptions__subscriber_id"),
        "subscriptions",
        ["subscriber_id"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions__subscriber_type_subscriber_id_status",
        "subscriptions",
        ["subscriber_type", "subscriber_id", "status"],
        unique=False,
    )
