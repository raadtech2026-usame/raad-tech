"""Platform & Audit value objects (Backend LLD §5.1; Database Design §8.7/§8.9). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`), mirroring every other module's identical convention.

**Architecture Resolution (Backend Stabilization phase, High finding #5 of the pre-production
review): `platform_audit` (C10) built for the first time.** Scoped to the two aggregates with an
actual documented API surface (`AuditEntry`, read-only; `SystemSetting`, `GET/PATCH
/admin/settings`) — see this package's `entities.py` module docstring for why `Integration`
(Database Design §8.9's other table) is deliberately not built this phase.

`AuditEntryId` is a ULID VO like every other module's own id type, but `AuditEntry` itself is
**never created through this module** — every row is written by the shared-kernel
`core.audit.writer.AuditWriter` (ADR-0007), transactionally, from every *other* module's own
`SqlAlchemyUnitOfWork.commit()`. This VO exists only so `AuditEntry`'s read-model shape matches
every other entity's id-typing convention.

**Cross-module references stay opaque, never re-validated** (`.claude/rules/database.md` #3):
`OrganizationId` (→ `organization.Organization`, nullable — "null for platform-level actions",
Database Design §8.7) and `UserId` (→ `iam.User`, `actor_user_id`, also nullable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

_SETTING_KEY_MAX_LENGTH = 26  # Database Design §8.9 gives `system_settings.key` no explicit
# length (compact notation) - capped here at 26, not an arbitrarily larger bound, because
# `SystemSettingSet`/`SystemSettingUpdated` (domain/events.py) carry `key` as the shared
# `DomainEvent.aggregate_id`, and both downstream sinks that column feeds - `outbox.aggregate_id`
# (Database Design §8.8) and `audit_entries.entity_id` (§8.7, via the shared-kernel AuditWriter,
# ADR-0007) - are `CHAR(26)`. A longer key would raise a DB error at commit time for every other
# ULID-keyed aggregate's identical column; this VO enforces the real constraint at the domain
# boundary instead of letting it surface as a cryptic Postgres error three layers down.


@dataclass(frozen=True)
class AuditEntryId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"AuditEntryId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SystemSettingKey:
    """`system_settings.key` (Database Design §8.9) — the table's own primary key, a short
    human-chosen label (e.g. `"maps.provider"`), never a ULID."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("SystemSettingKey must not be empty")
        if len(self.value) > _SETTING_KEY_MAX_LENGTH:
            raise DomainError(
                f"SystemSettingKey must be at most {_SETTING_KEY_MAX_LENGTH} characters: "
                f"{len(self.value)}"
            )

    def __str__(self) -> str:
        return self.value
