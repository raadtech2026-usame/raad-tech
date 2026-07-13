"""Fleet & Device value objects (Backend LLD §5.1; Database Design §5). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`), the project's existing domain-invariant exception.

`VehicleId`/`DeviceId`/`CameraId`/`AssignmentId` are minted and owned by *this* module
(`vehicles`/`devices`/`cameras`/`device_assignments` are this module's own tables), so the
strict ULID shape is validated — same reasoning as `organization.domain.value_objects`.
`OrganizationId` is a cross-module reference validated only as an opaque non-empty string,
mirroring `iam.domain.value_objects.OrganizationId` exactly (`.claude/rules/database.md` #3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

_TERMINAL_ID_MAX_LENGTH = 64  # Database Design §5.2: VARCHAR(64)
_MSISDN_MAX_LENGTH = 32  # Database Design §5.2: VARCHAR(32)


@dataclass(frozen=True)
class VehicleId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"VehicleId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class DeviceId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"DeviceId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CameraId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"CameraId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AssignmentId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"AssignmentId must be a 26-character ULID: {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """A reference to an `Organization` aggregate owned by the `organization` module
    (Database Design §4.2) — this module never loads or mutates that aggregate, only stores
    its id, per "cross-context references are by ID only" (`.claude/rules/architecture.md` #3
    / `.claude/rules/database.md` #3). Deliberately validated as an opaque non-empty string,
    not a specific ID format/scheme — `fleet_device` doesn't own how `organization` mints its
    ids. Identical stance to `iam.domain.value_objects.OrganizationId`."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TerminalId:
    """The JT808 terminal/SIM identifier a device presents on the wire (Database Design §5.2:
    `terminal_id VARCHAR(64)`, globally unique `UX`). An opaque, vendor-assigned string — the
    exact wire encoding (2013 vs 2019 protocol editions) is a device-plane ACL concern
    (Phase 3.4 §6), not something this module's domain validates beyond shape."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("TerminalId must not be empty")
        if len(self.value) > _TERMINAL_ID_MAX_LENGTH:
            raise DomainError(
                f"TerminalId must be at most {_TERMINAL_ID_MAX_LENGTH} characters"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Msisdn:
    """A device SIM's phone number (Backend LLD §5.1 lists `Msisdn` as a value-object
    example; Database Design §5.2: `sim_msisdn VARCHAR(32)`, "masked in logs"). `repr()`
    masks all but the last 4 digits so accidental logging of the object never leaks the full
    number; `str()` returns the full value for the persistence boundary."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("Msisdn must not be empty")
        if len(self.value) > _MSISDN_MAX_LENGTH:
            raise DomainError(f"Msisdn must be at most {_MSISDN_MAX_LENGTH} characters")

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Msisdn('{self.masked()}')"

    def masked(self) -> str:
        if len(self.value) <= 4:
            return "*" * len(self.value)
        return "*" * (len(self.value) - 4) + self.value[-4:]


class VehicleStatus(str, Enum):
    """Database Design §5.1: `status ENUM(active,inactive,maintenance)`."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class DeviceLifecycleState(str, Enum):
    """Database Design §5.2: `lifecycle_state ENUM(registered,activated,assigned,suspended,
    retired)`, which the Database Design itself derives from Phase 2 §19.2's state machine.
    §19.2's diagram additionally shows `Unassigned` and `Reassigned`; the Database Design
    reconciles those onto this 5-value enum — `Unassigned` ≡ `activated` with no active
    `DeviceAssignment` row, and `Reassigned` is a transition (close old + open new
    assignment), not a persisted state. `entities.Device` enforces the §19.2 edges over these
    five values (see its docstring)."""

    REGISTERED = "registered"
    ACTIVATED = "activated"
    ASSIGNED = "assigned"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class CameraPosition(str, Enum):
    """Database Design §5.3: `position ENUM(in_cabin,road_facing,other)` — **D5**: `in_cabin`
    is never exposed to parents. That exposure rule is the `video` context's policy
    (`VideoAccessPolicy`, Backend LLD §5.2); this module only records the provisioning
    fact."""

    IN_CABIN = "in_cabin"
    ROAD_FACING = "road_facing"
    OTHER = "other"
