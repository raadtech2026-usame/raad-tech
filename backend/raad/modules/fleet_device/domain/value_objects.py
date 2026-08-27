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
_IMEI_LENGTH = 15  # GSMA TS.06: IMEI is always exactly 15 digits, a fixed global standard
_ICCID_MAX_LENGTH = 32  # ICCID length varies 18-20 digits by issuer; VARCHAR(32) ceiling only
_SERIAL_NUMBER_MAX_LENGTH = 64  # vendor-defined format, same flexibility as TerminalId


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
class InventoryItemId:
    """`device_inventory.id` (ADR-0018) — minted and owned by this module, same strict-ULID
    treatment as `DeviceId`."""

    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"InventoryItemId must be a 26-character ULID: {self.value!r}"
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


@dataclass(frozen=True)
class Imei:
    """A device modem's IMEI (Device Domain Overhaul architecture review — Database Design
    §5.2's previously-flagged gap: theft/fraud checks, vendor support). Exactly 15 digits
    (GSMA TS.06), unlike `TerminalId`/`Msisdn`'s deliberately vendor-flexible length — IMEI is
    a fixed global standard, not a vendor dialect."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("Imei must not be empty")
        if len(self.value) != _IMEI_LENGTH or not self.value.isdigit():
            raise DomainError(f"Imei must be exactly {_IMEI_LENGTH} digits: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Iccid:
    """A SIM card's ICCID (Device Domain Overhaul architecture review) — used to correlate a
    SIM swap with the device it's inserted into. Length varies 18-20 digits by issuer, so only
    a max-length ceiling is validated here, mirroring `TerminalId`'s identical vendor-format
    flexibility."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("Iccid must not be empty")
        if len(self.value) > _ICCID_MAX_LENGTH:
            raise DomainError(f"Iccid must be at most {_ICCID_MAX_LENGTH} characters")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SerialNumber:
    """Vendor-assigned hardware serial number (Device Domain Overhaul architecture review) —
    warehouse/RMA workflow key. Opaque, vendor-defined format — same flexibility as
    `TerminalId`."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("SerialNumber must not be empty")
        if len(self.value) > _SERIAL_NUMBER_MAX_LENGTH:
            raise DomainError(
                f"SerialNumber must be at most {_SERIAL_NUMBER_MAX_LENGTH} characters"
            )

    def __str__(self) -> str:
        return self.value


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
    """Database Design §5.3's original three values (`in_cabin`, `road_facing`, `other`),
    widened by ADR-0032 with five directional/role values discovered channels can now be
    assigned to. **D5**: `IN_CABIN`/`DRIVER_FACING` are never exposed to parents — enforced in
    `interfaces/http/policy_guards.resolve_d5_decision` (a real gap found and fixed by
    ADR-0032: this module's own prior docstring claimed `VideoAccessPolicy` consumed this fact,
    but `VideoAccessPolicy.evaluate` never took a camera/position argument at all — the check
    did not exist anywhere before ADR-0032). `is_cabin_facing` is the single source of truth
    for that exclusion set, so a future position value only needs to be added to
    `_CABIN_FACING_POSITIONS` once, not re-derived at every call site."""

    IN_CABIN = "in_cabin"
    ROAD_FACING = "road_facing"
    OTHER = "other"
    FRONT = "front"
    REAR = "rear"
    LEFT = "left"
    RIGHT = "right"
    DRIVER_FACING = "driver_facing"

    @property
    def is_cabin_facing(self) -> bool:
        """True for any position showing the vehicle's interior/occupants — the set D5 excludes
        from parent video access, regardless of an explicit `has_video_*_access` grant."""
        return self in _CABIN_FACING_POSITIONS


_CABIN_FACING_POSITIONS = frozenset({CameraPosition.IN_CABIN, CameraPosition.DRIVER_FACING})


@dataclass(frozen=True)
class AudioCapability:
    """ADR-0033: the terminal's own `0x1003` audio/video attributes report (`mdvrdocs/
    MDVR-808-1078-spec.pdf` §6.1.2 Table 6.1), recorded verbatim — no codec/sample-rate
    assumption is made anywhere in this value object or its callers. Every field is the raw wire
    value; `codec`/`video_codec` are Table 6.21's enum byte, not decoded to a name here (no
    approved document maps every one of that table's 28 codec IDs to a name yet). Device-level,
    not camera-level: `0x1003` reports `max_audio_channels` independently of
    `max_video_channels` — this codebase does not assume a 1:1 audio-to-video-channel mapping."""

    codec: int
    channels: int
    sample_rate: int
    sample_bits: int
    frame_length: int
    supports_output: bool
    video_codec: int


class DeviceInventoryState(str, Enum):
    """ADR-0018 §1: `device_inventory.state ENUM(manufactured,in_stock,allocated,scrapped)`.
    `receive()` (`entities.DeviceInventoryItem`) deliberately skips straight to `IN_STOCK` —
    ADR-0018 itself calls the exact initial state "an implementation choice, not user-facing
    this phase" — and no `scrap()` transition is implemented this phase (no documented
    use-case/route reaches it); `SCRAPPED` stays a legal value only to match the ADR's exact
    enum shape at the database level."""

    MANUFACTURED = "manufactured"
    IN_STOCK = "in_stock"
    ALLOCATED = "allocated"
    SCRAPPED = "scrapped"
