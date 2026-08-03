"""core: allow outbox.aggregate_id to be null

Revision ID: f3d8b1a4e6c2
Revises: a1c9e4f2b871
Create Date: 2026-08-03 15:00:00.000000

Shared-kernel migration (owned by `core`/the outbox itself, not a single bounded context's own
aggregate build-out — the same "owned by core, flagged in its own docstring" precedent
`role_permissions`'/`audit_entries`' own migrations already established, per CLAUDE.md's
Migration status section).

A real, live-verified production bug, caught only once Priority 1 Item 6's new HTTP routes made
`iam.role_permission_granted`/`revoked` and `organization.region_assignment_granted`/`revoked`/
`support_assignment_granted`/`revoked` reachable for the first time: those six event factories
used a composite string (`f"{role}:{permission}"` or `f"{user_id}:{region_id}"`) as
`aggregate_id`, since `RolePermission`/`ScopeAssignment` are pure grant/revoke reference data
with no real minted ULID identity. `outbox.aggregate_id` is `CHAR(26) NOT NULL` (Database Design
§8.8) — sized for a real ULID, which every *other* event's `aggregate_id` actually is — and a
composite string reliably exceeds 26 characters (even two concatenated 26-char ULIDs plus a
separator already do), raising `asyncpg.exceptions.StringDataRightTruncationError` on every
single grant/revoke call. Never caught before this item: these six factories existed since the
Backend Stabilization phase but were reachable only through application-layer callers with no
real integration/live-HTTP exercise until now.

Fixed at the domain layer by making these six factories pass `aggregate_id=None` instead (the
full role/permission or user/region/organization identity is still captured in `payload`, so no
information is lost) — this migration is the corresponding schema half: `outbox.aggregate_id`
already had a `CHAR(26)` sibling column, `audit_entries.entity_id`, that was *already* nullable
(`core/audit/writer.py`) for exactly this kind of case; `outbox.aggregate_id` should have matched
it from the start, since both represent the identical "which aggregate produced this event"
concept, just materialized into two different shared-kernel tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3d8b1a4e6c2"
down_revision: Union[str, None] = "a1c9e4f2b871"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "outbox",
        "aggregate_id",
        existing_type=sa.CHAR(26),
        nullable=True,
    )


def downgrade() -> None:
    # Reversible only if no row actually holds a NULL aggregate_id at downgrade time (matches
    # this codebase's existing precedent of not silently backfilling data on downgrade) - an
    # operator downgrading past this revision with real RolePermission/ScopeAssignment grant/
    # revoke events already in the table would need to handle those rows explicitly first.
    op.alter_column(
        "outbox",
        "aggregate_id",
        existing_type=sa.CHAR(26),
        nullable=False,
    )
