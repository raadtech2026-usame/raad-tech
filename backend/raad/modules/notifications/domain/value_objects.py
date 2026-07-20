"""Notifications value objects (Backend LLD §5.1; Database Design §7.5-§7.7; ADR-0001: `C7`
owns `notifications`, `device_tokens`, `notification_preferences`). Immutable, equality-by-value,
framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises `DomainError`
(`core.errors.exceptions`), mirroring every other module's identical convention.

**No LLD aggregate contract skeleton exists for `Notification`/`DeviceToken`** (unlike `Trip`/
`DeviceAssignment`) — Backend LLD documents only the *Notification Worker's* runtime behavior
(§11.2/§11.3), never a `Notification`/`DeviceToken` domain-object shape. Both are built here by
structural analogy to the closest already-completed precedent (`Payment`'s `UlidPrimaryKeyMixin`-
only shape, for a table with no `+audit` line), flagged per-field where genuinely interpretive.

**Cross-module references stay opaque, never re-validated** (`.claude/rules/database.md` #3):
`OrganizationId` (→ `organization.Organization`), `UserId` (→ `iam.User`, used both as
`notifications.recipient_user_id` and `device_tokens.user_id`), `TripId` (→ `transport_ops.Trip`,
nullable "context" per §7.5) — the same opaque, non-empty-string-only treatment every other
module's own cross-module VOs already establish (e.g. `transport_ops.VehicleId`).

**`NotificationId`/`DeviceTokenId` are module-owned ULID VOs** (Database Design §1/§20.2), same
shape as every other aggregate-owned id in this codebase.

**`NotificationType`** — Database Design §7.5's `ENUM(trip_started,approaching_stop,arrived_org,
trip_completed,subscription,system)`, used verbatim; matches API Contracts §13.3's "Notification
catalogue" exactly (`trip_started, approaching_stop, arrived_org, trip_completed` — D1 transport
class — plus `subscription`/`system` — billing/system class). No conflict between the two
documents for this enum specifically.

**`NotificationStatus` is a derived value, not a persisted column — flagged, not invented.**
Database Design §7.5 has no `status` column at all for `notifications`; the only state it
tracks is a nullable `read_at` timestamp. The task's own scope names `NotificationStatus`
explicitly, so it is modeled here as a two-value enum (`UNREAD`/`READ`) *computed* from
`read_at is None`, on the `Notification` entity's own `status` property (`entities.py`) — never
written to the database as its own column, since no such column is documented.

**`Platform`** — Database Design §7.6's `ENUM(android,ios)`, used verbatim.

**`FcmToken`'s length is undocumented** (§7.6 gives only the bare column name `fcm_token`, no
explicit `VARCHAR(n)`, unlike `email`/`phone` elsewhere in this codebase). Validated here as a
non-empty opaque string only, with the persistence-layer length choice deferred to
`infra/models.py` (flagged there, not invented as a domain-level length rule no document states).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class NotificationId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"NotificationId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class DeviceTokenId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"DeviceTokenId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """Cross-module reference to an `Organization` aggregate owned by `organization` — opaque,
    non-empty string only (`.claude/rules/database.md` #3)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserId:
    """Cross-module reference to an `iam.User` — opaque, non-empty string only. Used for both
    `notifications.recipient_user_id` and `device_tokens.user_id` (both name the same target
    aggregate, `iam.User`)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TripId:
    """Cross-module reference to a `transport_ops.Trip` — opaque, non-empty string only.
    Nullable at the aggregate level ("context", §7.5) — this VO itself is always non-empty when
    constructed; `Notification.trip_id: TripId | None` carries the nullability."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("TripId must not be empty")

    def __str__(self) -> str:
        return self.value


class NotificationType(str, Enum):
    """Database Design §7.5 verbatim; matches API Contracts §13.3's notification catalogue."""

    TRIP_STARTED = "trip_started"
    APPROACHING_STOP = "approaching_stop"
    ARRIVED_ORG = "arrived_org"
    TRIP_COMPLETED = "trip_completed"
    SUBSCRIPTION = "subscription"
    SYSTEM = "system"


class NotificationStatus(str, Enum):
    """Derived from `read_at` — see module docstring. Not a database column."""

    UNREAD = "unread"
    READ = "read"


class Platform(str, Enum):
    """Database Design §7.6 verbatim."""

    ANDROID = "android"
    IOS = "ios"


@dataclass(frozen=True)
class FcmToken:
    """Opaque, non-empty external push-registration token — see module docstring for the
    undocumented-length note."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("FcmToken must not be empty")

    def __str__(self) -> str:
        return self.value
