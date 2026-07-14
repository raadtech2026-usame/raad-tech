"""Tracking ORM models (Backend LLD §17 `db`; Database Design §7.1/§7.2). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

Two models, exactly the two tables this module owns:

- `VehiclePositionModel` (§7.1) — **no audit-column mixin of any kind.** Unlike every table
  seen so far, Database Design §7.1's column list carries no "+ standard audit cols" line and
  no partial audit note either — nothing beyond the columns it explicitly lists. This matches
  the domain layer's own reasoning (Phase 8.1: hard-pruned by partition drop, never
  soft-deleted, immutable after insert) — so not even `UlidPrimaryKeyMixin`'s single-column
  PK shape fully applies: the primary key is **composite `(id, event_time)`**, per the
  Database Design's own explicit note ("PK includes the partition key per MySQL partitioning
  rules") — a real MySQL requirement (every unique key, including the PK, must contain the
  partition key on a RANGE-partitioned table), not an invented column. `UlidPrimaryKeyMixin`
  is still composed for `id`'s ULID default; `event_time` separately declares
  `primary_key=True`, and SQLAlchemy combines the two into one composite key automatically.
  Actual `PARTITION BY RANGE` DDL is an Alembic-migration-time concern (a later phase,
  mirroring `fleet_device`'s 7.3 infra → 7.5 migration split) — this model only shapes the
  columns/PK the partitioning scheme requires.

- `GeofenceCrossingModel` (§7.2) — carries only `id` + `created_at`, exactly Database Design
  §7.2's "+created_at" (not "+standard audit cols"): no `updated_at`/`created_by`/
  `updated_by`/`row_version`/`deleted_at`. None of the four composable mixins in
  `core.db.mixins` produce "created_at alone" (`TimestampMixin` bundles `created_at` *and*
  `updated_at`), so this table follows the same precedent `core.events.outbox.OutboxRecord`
  already established for an identical "append-only ledger, `created_at` only" shape:
  `UlidPrimaryKeyMixin` plus a directly-declared `created_at` column (`core.db.mixins.utcnow`
  default) — not a new mixin invented for one table.

**Neither model declares a single `ForeignKey`.** Every reference either table carries
(`organization_id`, `vehicle_id`, `device_id`, `trip_id`, `stop_id`) is a cross-module
reference (owned by `organization`/`fleet_device`/`fleet_device`/`transport_ops`/
`transport_ops` respectively) — plain indexed-or-not columns per
`.claude/rules/database.md` #3 ("not hard-FK-constrained across module boundaries"), the same
treatment `fleet_device.infra.models` gives `organization_id`. This module owns no table that
references another table *this module* owns, so — unlike `fleet_device` (`cameras.device_id`,
`device_assignments.device_id`/`vehicle_id`) — there is no in-context FK to declare either.

**Indexes implemented exactly as documented, no more:** Database Design §7.1 gives
`vehicle_positions` a full per-column table marking `organization_id` as `ix`; `vehicle_id`/
`trip_id` are also marked `ix` but that requirement is already satisfied by the two named
composite indexes the same section's prose lists (`ix_vehicle_positions__veh_time
(vehicle_id, event_time)`, `ix_vehicle_positions__trip_time (trip_id, event_time)` — MySQL's
leftmost-prefix rule means a composite index already serves lookups on its leading column, so
a redundant single-column index would be an invented extra index); `device_id` carries no `ix`
mark at all, so it stays a plain unindexed column. §7.2's `geofence_events` is given in
compact inline notation with only one index named in prose (`(trip_id, occurred_at)`) and no
explicit per-column `ix` marks at all (unlike §7.1's full table) — so, to avoid inventing an
index the document doesn't state, `organization_id` on `geofence_events` is **not** separately
indexed here, even though every other tenant-owned table in this codebase has one; this
asymmetry is Database Design's own, not introduced by this phase.

Index/constraint names follow `core.db.base`'s naming convention off the real column names
(e.g. `ix_vehicle_positions__vehicle_id_event_time`, not the doc's abbreviated
`ix_vehicle_positions__veh_time`) — the same documented stance `fleet_device.infra.models`
takes.

`latitude`/`longitude` are `mysql.DECIMAL(9, 6)` (Database Design §7.1: `DECIMAL(9,6)`) with
`asdecimal=False`, so the Python-side attribute is a plain `float` — matching the domain
`GeoPoint` value object's own `float` fields exactly, with no `Decimal`-handling needed in
`mappers.py`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CHAR, Enum as SqlEnum, Index, Integer, SmallInteger
from sqlalchemy.dialects.mysql import DATETIME as MySqlDateTime
from sqlalchemy.dialects.mysql import DECIMAL as MySqlDecimal
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin, utcnow

_GEOFENCE_EVENT_TYPE_VALUES = (
    "approaching_stop",
    "entered_stop",
    "arrived_org",
    "exited",
)


class VehiclePositionModel(UlidPrimaryKeyMixin, Base):
    """`vehicle_positions` (Database Design §7.1): a single GPS fix. Composite primary key
    `(id, event_time)` — see module docstring."""

    __tablename__ = "vehicle_positions"
    __table_args__ = (
        Index(
            "ix_vehicle_positions__vehicle_id_event_time", "vehicle_id", "event_time"
        ),
        Index("ix_vehicle_positions__trip_id_event_time", "trip_id", "event_time"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    device_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    trip_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    latitude: Mapped[float] = mapped_column(
        MySqlDecimal(9, 6, asdecimal=False), nullable=False
    )
    longitude: Mapped[float] = mapped_column(
        MySqlDecimal(9, 6, asdecimal=False), nullable=False
    )
    speed_kph: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    heading_deg: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    alarm_flags: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False)
    event_time: Mapped[datetime] = mapped_column(MySqlDateTime(fsp=3), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(MySqlDateTime(fsp=3), nullable=False)


class GeofenceCrossingModel(UlidPrimaryKeyMixin, Base):
    """`geofence_events` (Database Design §7.2): a detected stop/organization-geofence
    crossing. `created_at`-only (no full audit bundle) — see module docstring."""

    __tablename__ = "geofence_events"
    __table_args__ = (
        Index("ix_geofence_events__trip_id_occurred_at", "trip_id", "occurred_at"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    trip_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    stop_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    event_type: Mapped[str] = mapped_column(
        SqlEnum(*_GEOFENCE_EVENT_TYPE_VALUES, name="geofence_event_type"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(MySqlDateTime(fsp=3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        MySqlDateTime(fsp=3), nullable=False, default=utcnow
    )
