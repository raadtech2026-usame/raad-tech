"""tracking: convert vehicle_positions to monthly RANGE partitioning (audit finding B15)

Revision ID: c8b4d17e9f30
Revises: a7f31c92be04
Create Date: 2026-09-04 20:00:00.000000

`.claude/rules/database.md` #6 mandates that `vehicle_positions` be "partitioned by time (RANGE,
monthly, by `event_time`)" and "hard-pruned via partition drops, not per-row soft delete". The
table was never actually partitioned — a plain heap with 380,510 rows at the time of this
migration, pruned by row-level `DELETE`.

**Most of the work was already done.** `VehiclePositionModel`'s own module docstring records
that the composite primary key `(id, event_time)` exists *specifically* because "every unique
key, including the PK, must contain the partition key on a partitioned table", and explicitly
defers the DDL: "Actual `PARTITION BY RANGE` DDL is an Alembic-migration-time concern (a later
phase)". This is that phase. The column and PK shape need no change at all — verified against
the live database before writing this.

## What this does

PostgreSQL cannot convert a populated heap into a partitioned table in place, so:

1. rename `vehicle_positions` -> `vehicle_positions_legacy`
2. create `vehicle_positions` as `PARTITION BY RANGE (event_time)`, identical columns and PK
3. create one partition per month across a generous window, **plus a `DEFAULT` partition**
4. copy every row across
5. **verify the copied row count matches** — and abort the whole migration if it does not
6. drop the legacy table, then build the secondary indexes on the partitioned parent

Step 5 is the important one. This migration moves real, irreplaceable GPS history; a silent
partial copy would be the worst possible outcome, so it fails loudly instead. The whole thing
runs inside Alembic's transaction, so an abort rolls back to the original table intact.

## Why a DEFAULT partition

Without one, an insert whose `event_time` falls outside every defined range fails outright — and
on this table that means **dropping a live GPS fix from a moving school bus**. A device with a
badly-skewed clock, or simply the calendar advancing past the last pre-created month, would do
it. The `DEFAULT` partition makes that impossible: the row always lands somewhere.

It is a safety net, not the design. `create_upcoming_vehicle_position_partitions` (the
maintenance job added alongside this migration) keeps real monthly partitions provisioned ahead
of time so `DEFAULT` stays empty. A non-empty `DEFAULT` is a signal that job has stopped
running, not normal operation — note that PostgreSQL refuses to attach a new partition whose
range overlaps rows already sitting in `DEFAULT`, which is exactly why the job runs ahead.

## Downgrade

Fully reversible and data-preserving: rebuild a plain heap, copy every row back, verify the
count again, drop the partitioned table. The only thing not restored is the physical partition
layout, which is the point of downgrading.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8b4d17e9f30"
down_revision: Union[str, None] = "a7f31c92be04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Columns, in the exact physical order the live table has them. Kept explicit rather than
#: `SELECT *` so the copy is order-independent and a future column addition breaks loudly here
#: instead of silently mis-mapping values.
_COLUMNS = (
    "organization_id",
    "vehicle_id",
    "device_id",
    "trip_id",
    "latitude",
    "longitude",
    "speed_kph",
    "heading_deg",
    "alarm_flags",
    "is_backfill",
    "event_time",
    "received_at",
    "id",
)

_COLUMN_LIST = ", ".join(_COLUMNS)

_TABLE_BODY = """
    organization_id CHAR(26) NOT NULL,
    vehicle_id CHAR(26) NOT NULL,
    device_id CHAR(26) NOT NULL,
    trip_id CHAR(26),
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    speed_kph SMALLINT,
    heading_deg SMALLINT,
    alarm_flags INTEGER,
    is_backfill BOOLEAN NOT NULL,
    event_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    received_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    id CHAR(26) NOT NULL
"""

#: Pre-created partition window. Starts before the earliest real data (2026-08) and runs well
#: ahead so the maintenance job has room even if it is briefly not running. Generated rather
#: than hand-listed so the boundaries cannot drift.
_PARTITION_START = (2026, 1)
_PARTITION_MONTHS = 36


def _month_bounds(year: int, month: int) -> tuple[str, str, str]:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return (
        f"vehicle_positions_{year}_{month:02d}",
        f"{year}-{month:02d}-01",
        f"{next_year}-{next_month:02d}-01",
    )


def _iter_partitions():
    year, month = _PARTITION_START
    for _ in range(_PARTITION_MONTHS):
        yield _month_bounds(year, month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _copied_row_count_matches(source: str, target: str) -> None:
    """Aborts the migration unless every row made it across. This table holds real GPS history
    that cannot be regenerated, so a silent partial copy must never be allowed to commit."""
    bind = op.get_bind()
    before = bind.execute(sa.text(f"SELECT count(*) FROM {source}")).scalar_one()
    after = bind.execute(sa.text(f"SELECT count(*) FROM {target}")).scalar_one()
    if before != after:
        raise RuntimeError(
            f"vehicle_positions copy mismatch: {source} had {before} rows, "
            f"{target} received {after}. Aborting so the transaction rolls back with the "
            "original table intact."
        )


def upgrade() -> None:
    op.execute("ALTER TABLE vehicle_positions RENAME TO vehicle_positions_legacy")
    # Indexes follow the table on rename and would collide with the new ones created below.
    op.execute(
        "ALTER INDEX ix_vehicle_positions__vehicle_id_event_time "
        "RENAME TO ix_vp_legacy__vehicle_id_event_time"
    )
    op.execute(
        "ALTER INDEX ix_vehicle_positions__trip_id_event_time "
        "RENAME TO ix_vp_legacy__trip_id_event_time"
    )
    op.execute(
        "ALTER INDEX ix_vehicle_positions__organization_id "
        "RENAME TO ix_vp_legacy__organization_id"
    )
    op.execute("ALTER INDEX pk_vehicle_positions RENAME TO pk_vp_legacy")

    op.execute(
        f"""
        CREATE TABLE vehicle_positions (
            {_TABLE_BODY},
            CONSTRAINT pk_vehicle_positions PRIMARY KEY (id, event_time)
        ) PARTITION BY RANGE (event_time)
        """
    )

    for name, start, end in _iter_partitions():
        op.execute(
            f"CREATE TABLE {name} PARTITION OF vehicle_positions "
            f"FOR VALUES FROM ('{start}') TO ('{end}')"
        )
    # The safety net — see this migration's own docstring for why a dropped GPS fix is
    # unacceptable and why this must never be the normal landing place.
    op.execute(
        "CREATE TABLE vehicle_positions_default PARTITION OF vehicle_positions DEFAULT"
    )

    op.execute(
        f"INSERT INTO vehicle_positions ({_COLUMN_LIST}) "
        f"SELECT {_COLUMN_LIST} FROM vehicle_positions_legacy"
    )
    _copied_row_count_matches("vehicle_positions_legacy", "vehicle_positions")

    op.execute("DROP TABLE vehicle_positions_legacy")

    # Built after the copy, not before: bulk-loading into an unindexed table then indexing once
    # is materially faster than maintaining indexes per row.
    op.create_index(
        "ix_vehicle_positions__vehicle_id_event_time",
        "vehicle_positions",
        ["vehicle_id", "event_time"],
    )
    op.create_index(
        "ix_vehicle_positions__trip_id_event_time",
        "vehicle_positions",
        ["trip_id", "event_time"],
    )
    op.create_index(
        "ix_vehicle_positions__organization_id",
        "vehicle_positions",
        ["organization_id"],
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vehicle_positions RENAME TO vehicle_positions_partitioned")
    op.execute("ALTER INDEX pk_vehicle_positions RENAME TO pk_vp_partitioned")
    op.execute(
        "ALTER INDEX ix_vehicle_positions__vehicle_id_event_time "
        "RENAME TO ix_vp_part__vehicle_id_event_time"
    )
    op.execute(
        "ALTER INDEX ix_vehicle_positions__trip_id_event_time "
        "RENAME TO ix_vp_part__trip_id_event_time"
    )
    op.execute(
        "ALTER INDEX ix_vehicle_positions__organization_id "
        "RENAME TO ix_vp_part__organization_id"
    )

    op.execute(
        f"""
        CREATE TABLE vehicle_positions (
            {_TABLE_BODY},
            CONSTRAINT pk_vehicle_positions PRIMARY KEY (id, event_time)
        )
        """
    )
    op.execute(
        f"INSERT INTO vehicle_positions ({_COLUMN_LIST}) "
        f"SELECT {_COLUMN_LIST} FROM vehicle_positions_partitioned"
    )
    _copied_row_count_matches("vehicle_positions_partitioned", "vehicle_positions")

    # Dropping the parent drops every partition with it.
    op.execute("DROP TABLE vehicle_positions_partitioned")

    op.create_index(
        "ix_vehicle_positions__vehicle_id_event_time",
        "vehicle_positions",
        ["vehicle_id", "event_time"],
    )
    op.create_index(
        "ix_vehicle_positions__trip_id_event_time",
        "vehicle_positions",
        ["trip_id", "event_time"],
    )
    op.create_index(
        "ix_vehicle_positions__organization_id",
        "vehicle_positions",
        ["organization_id"],
    )
