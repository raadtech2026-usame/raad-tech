"""organization: add trial_started_at/trial_ends_at columns

Revision ID: f1a4c8b2e6d9
Revises: e7c3a95d1f42
Create Date: 2026-09-14 10:00:00.000000

Adds `organizations.trial_started_at`/`trial_ends_at` for the Founder-controlled organization
trial workflow (Organization Lifecycle / Subscription / Platform Finance architecture pass,
2026-09-14). Both columns are nullable and purely additive — every pre-existing organization
correctly reads as "no trial" (`TrialState.NOT_STARTED`, both columns null), which is true: no
prior version of this codebase had any trial concept, so there is nothing to backfill.

Deliberately placed on `organizations` (the `organization` module), never on `billing.
subscriptions` — a trial can exist before any `Plan`/`Subscription` is ever chosen for the
organization (a trial is offered at organization-creation time, independent of billing), so it
cannot be modeled as a `Subscription`-owned field. See `organization/domain/entities.py`'s own
module note and `organization/domain/value_objects.TrialState` for the full reasoning, and why
this is a deliberately separate concept from the pre-existing `billing.SubscriptionStatus.TRIAL`
enum value (a permanent, one-time "just opened, not yet paid" label on a `Subscription` row,
never a time-boxed grace period).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a4c8b2e6d9"
down_revision: Union[str, None] = "e7c3a95d1f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("trial_started_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("trial_ends_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "trial_ends_at")
    op.drop_column("organizations", "trial_started_at")
