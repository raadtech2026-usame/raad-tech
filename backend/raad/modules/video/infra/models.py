"""Video ORM model (Backend LLD §17 `db`; Database Design §7.4). SQLAlchemy is confined to this
infra layer — the domain and application layers never import it (`.claude/rules/backend.md`
#2). PostgreSQL types only (ADR-0002).

**`VideoSessionModel` composes `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`** — the
identical situation `billing.infra.models.PaymentModel`'s own docstring already establishes.
Database Design §7.4 lists exactly its own columns plus a single trailing "+ created_at" note
("every session audited"), **not** "+ standard audit cols" the way `plans`/`subscriptions`/
`invoices`/`transport_fees` each end with — no `updated_at`/`created_by`/`updated_by`/
`deleted_at`/`row_version` is documented for this table, confirmed by re-reading §7.4 in full
before implementing, not assumed from every other module's own default shape.

`device_id`/`camera_id`/`requested_by` are plain indexed-where-documented columns, never
database `ForeignKey`s — all three are cross-module references (`fleet_device.Device`/`Camera`,
`iam.User`), the same treatment every other module's own cross-module reference columns get
(`.claude/rules/database.md` #3).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin

_VIDEO_PURPOSE_VALUES = ("live", "playback")
_VIDEO_SESSION_STATUS_VALUES = ("requested", "active", "ended", "failed")


class VideoSessionModel(UlidPrimaryKeyMixin, Base):
    """`video_sessions` (Database Design §7.4) - see module docstring for why this composes
    `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`."""

    __tablename__ = "video_sessions"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    purpose: Mapped[str] = mapped_column(
        SqlEnum(*_VIDEO_PURPOSE_VALUES, name="video_purpose"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    status: Mapped[str] = mapped_column(
        SqlEnum(*_VIDEO_SESSION_STATUS_VALUES, name="video_session_status"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
