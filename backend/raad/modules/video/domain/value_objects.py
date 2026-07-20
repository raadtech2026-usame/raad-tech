"""Video value objects (Backend LLD §5.1; Database Design §7.4). Immutable, equality-by-value,
framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises `DomainError`
(`core.errors.exceptions`), mirroring every other module's identical convention.

**Architecture Resolution (Backend Stabilization phase):** `video` was a pure scaffold with no
domain/application/infra logic (D5's `VideoAccessPolicy` existed since Phase 14 but had no
route to enforce). Built now, minimally, per this phase's explicit "Video subsystem" scope:
native JT1078 device signaling is explicitly out — `VideoProviderPort` (`application/ports.py`)
abstracts a hardware/vendor video API instead (MVP), left unbound (no concrete adapter), the
same "fail loudly, don't fake" treatment `PaymentProviderPort`/`LatestPositionPort` already
establish.

Cross-module references stay opaque, never re-validated (`.claude/rules/database.md` #3):
`OrganizationId` (→ `organization.Organization`), `DeviceId`/`CameraId` (→
`fleet_device.Device`/`Camera`), `UserId` (→ `iam.User`, `requested_by`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class VideoSessionId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"VideoSessionId must be a 26-character ULID: {self.value!r}"
            )

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
class DeviceId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("DeviceId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CameraId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("CameraId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserId:
    """Cross-module reference to an `iam.User` — names `video_sessions.requested_by`
    (Database Design §7.4: "must be org_admin / permitted RAAD staff — never parent, D5")."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


class VideoPurpose(str, Enum):
    """Database Design §7.4 verbatim: `video_sessions.purpose ENUM(live,playback)`."""

    LIVE = "live"
    PLAYBACK = "playback"


class VideoSessionStatus(str, Enum):
    """Database Design §7.4 verbatim: `video_sessions.status ENUM(requested,active,ended,
    failed)`."""

    REQUESTED = "requested"
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"
