"""Platform & Audit ORM models (Backend LLD §17 `db`; Database Design §8.9). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2). PostgreSQL types only (ADR-0002).

**No `AuditEntryRecord` is defined here.** `audit_entries` is a shared-kernel table
(ADR-0007) — its one and only ORM model, `core.audit.writer.AuditEntryRecord`, is imported
directly by `infra/repositories.py`. Defining a second `Base`-mapped class for the same
`__tablename__` here would collide with that registration; see `core/audit/writer.py`'s module
docstring for the full architecture.

`SystemSettingModel.key` is `VARCHAR(26)`, matching `domain/value_objects.SystemSettingKey`'s
own enforced max length exactly — see that VO's docstring for why 26 specifically (the shared
`DomainEvent.aggregate_id`/`audit_entries.entity_id` `CHAR(26)` constraint every `SystemSetting`
event flows through).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base

_SETTING_KEY_LENGTH = 26
_SETTING_SCOPE_LENGTH = 60  # Database Design §8.9 gives no explicit length (compact notation)


class SystemSettingModel(Base):
    """`system_settings` (Database Design §8.9): `(key PK, value_json, scope)` — no
    `AuditedTableMixin`/`UlidPrimaryKeyMixin`, since the table's own primary key is `key`, a
    human-chosen label, not a ULID `id` (unlike every other table in this codebase)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(VARCHAR(_SETTING_KEY_LENGTH), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    scope: Mapped[str] = mapped_column(VARCHAR(_SETTING_SCOPE_LENGTH), nullable=False)
