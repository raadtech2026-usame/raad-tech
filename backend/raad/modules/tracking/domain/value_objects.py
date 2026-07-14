"""Tracking value objects (Backend LLD §5.1; Database Design §7.1/§7.2; Phase 2 §22).
Immutable, equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation
raises `DomainError` (`core.errors.exceptions`), the same existing domain-invariant exception
`fleet_device`/`organization`/`iam` use.

`VehiclePositionId`/`GeofenceCrossingId` are minted and owned by *this* module
(`vehicle_positions`/`geofence_events` are this module's own tables per Database Design §7.1/
§7.2 and JT808 LLD §15 "the Business API persists vehicle_positions, geofence_events..."), so
the strict ULID shape is validated — same reasoning as `fleet_device.domain.value_objects`.
`OrganizationId`/`VehicleId`/`DeviceId`/`TripId`/`StopId` are cross-module references
(owned by `organization`, `fleet_device`, `fleet_device`, `transport_ops`, `transport_ops`
respectively) validated only as opaque non-empty strings — never re-validating another
module's id format (`.claude/rules/database.md` #3, `.claude/rules/architecture.md` #3).

`GeoPoint` is named verbatim as a value-object example in Backend LLD §5.1. `SpeedKph`/
`HeadingDegrees`/`AlarmFlags` are bounded to the Database Design §7.1 column types they will
persist as (`SMALLINT`/`SMALLINT`/`INT`) — the same "cite the DB Design length/range" stance
`fleet_device.domain.value_objects.TerminalId`/`Msisdn` take for `VARCHAR` lengths.

**Scoped strictly to the fields the approved documentation specifies.** Database Design §7.1's
`vehicle_positions` columns, JT808 Technical Design §10's canonical `PositionReport`
(`organization_id, vehicle_id, device_id, trip_id?, lat, lng, speed_kph, heading_deg,
alarm_flags, event_time, is_backfill`), and API Contracts §11.2's `/ws/tracking` wire payload
all agree on exactly this field set. Altitude, GPS status/quality, and ACC/ignition state are
real JT/T 808 concepts but appear in **none** of the approved RAAD documents — deliberately not
modeled here (confirmed with the user rather than assumed, per `.claude/rules/workflow.md` #8);
add them only once an approved Database Design / API Contracts addendum defines their column
name, type, and semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# Database Design §7.1: `speed_kph SMALLINT`, `heading_deg SMALLINT`, `alarm_flags INT`.
# MySQL's default signed SMALLINT/INT ranges — the same "bound to the persisted column type"
# stance `fleet_device`'s VOs take for VARCHAR lengths.
_SMALLINT_MAX = 32_767
_INT_MAX = 2_147_483_647

_LATITUDE_MIN, _LATITUDE_MAX = -90.0, 90.0
_LONGITUDE_MIN, _LONGITUDE_MAX = -180.0, 180.0
_HEADING_MAX_EXCLUSIVE = 360  # compass bearing: 0..359


@dataclass(frozen=True)
class VehiclePositionId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"VehiclePositionId must be a 26-character ULID: {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GeofenceCrossingId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"GeofenceCrossingId must be a 26-character ULID: {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """Cross-module reference to an `Organization` aggregate owned by the `organization`
    module — opaque, non-empty string only, mirroring `fleet_device.domain.value_objects.
    OrganizationId` exactly (`.claude/rules/database.md` #3)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class VehicleId:
    """Cross-module reference to a `Vehicle` aggregate owned by `fleet_device` — opaque,
    non-empty string only; this module never re-validates `fleet_device`'s ULID shape.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("VehicleId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class DeviceId:
    """Cross-module reference to a `Device` aggregate owned by `fleet_device` — opaque,
    non-empty string only."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("DeviceId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TripId:
    """Cross-module reference to a `Trip` aggregate owned by `transport_ops` — opaque,
    non-empty string only. `vehicle_positions.trip_id` is nullable (Database Design §7.1:
    "null when no active trip") — callers that need "no trip" hold `None`, not an empty
    `TripId`, matching the nullable-column shape rather than inventing a sentinel value.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("TripId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StopId:
    """Cross-module reference to a `Stop` aggregate owned by `transport_ops` — opaque,
    non-empty string only. `geofence_events.stop_id` is nullable (Database Design §7.2: rows
    for the org-arrival/exit-of-org-geofence event carry no stop)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("StopId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GeoPoint:
    """A latitude/longitude pair (Backend LLD §5.1 names `GeoPoint` verbatim as a
    value-object example). Bounded to valid Earth coordinates; precision beyond that is an
    infra/persistence concern (Database Design §7.1: `DECIMAL(9,6)`), not a domain
    invariant."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (_LATITUDE_MIN <= self.latitude <= _LATITUDE_MAX):
            raise DomainError(
                f"latitude must be between {_LATITUDE_MIN} and {_LATITUDE_MAX}: "
                f"{self.latitude!r}"
            )
        if not (_LONGITUDE_MIN <= self.longitude <= _LONGITUDE_MAX):
            raise DomainError(
                f"longitude must be between {_LONGITUDE_MIN} and {_LONGITUDE_MAX}: "
                f"{self.longitude!r}"
            )


@dataclass(frozen=True)
class SpeedKph:
    """Ground speed in km/h (Database Design §7.1: `speed_kph SMALLINT`). Non-negative — a
    physical speed magnitude, not a signed velocity component."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise DomainError(f"SpeedKph must not be negative: {self.value!r}")
        if self.value > _SMALLINT_MAX:
            raise DomainError(
                f"SpeedKph must be at most {_SMALLINT_MAX}: {self.value!r}"
            )

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class HeadingDegrees:
    """Compass bearing in degrees, `0 <= value < 360` (Database Design §7.1:
    `heading_deg SMALLINT`)."""

    value: int

    def __post_init__(self) -> None:
        if not (0 <= self.value < _HEADING_MAX_EXCLUSIVE):
            raise DomainError(
                f"HeadingDegrees must be in [0, {_HEADING_MAX_EXCLUSIVE}): {self.value!r}"
            )

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class AlarmFlags:
    """The normalized JT808 alarm bitfield (Database Design §7.1: `alarm_flags INT`; JT808
    Technical Design §11: alarm taxonomy examples — SOS, overspeed, fatigue, low-power,
    GPS-antenna fault, video-loss). The exact bit-position layout is a device-plane ACL
    concern (Phase 3.4 §6/§11 normalizes vendor dialects into this field) — not reproduced or
    re-invented here; this value object only bounds and carries the already-normalized
    integer. Non-negative — a bitfield, never signed."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise DomainError(f"AlarmFlags must not be negative: {self.value!r}")
        if self.value > _INT_MAX:
            raise DomainError(f"AlarmFlags must be at most {_INT_MAX}: {self.value!r}")

    def __str__(self) -> str:
        return str(self.value)

    @property
    def is_clear(self) -> bool:
        return self.value == 0

    def has_bit(self, bit: int) -> bool:
        """Tests a single bit position. Callers name the position (device-plane-normalized,
        Phase 3.4 §11) — this VO does not enumerate a bit->alarm-name mapping since no
        approved document specifies one."""
        return bool(self.value & (1 << bit))


class GeofenceEventType(str, Enum):
    """Database Design §7.2: `geofence_events.event_type ENUM(approaching_stop,entered_stop,
    arrived_org,exited)`. Maps 1:1 onto the four crossing events Phase 2 §22.2's evaluation
    diagram names: `VehicleApproachingStop`, `VehicleEnteredStopGeofence`,
    `VehicleArrivedAtOrganization`, `VehicleExitedGeofence` (see `domain/events.py`)."""

    APPROACHING_STOP = "approaching_stop"
    ENTERED_STOP = "entered_stop"
    ARRIVED_ORG = "arrived_org"
    EXITED = "exited"


class GeofenceTransition(str, Enum):
    """Output of the stateless `GeofenceEvaluationService.detect_transition` primitive
    (`domain/services.py`) — not a persisted/DB-backed enum, purely a domain-service return
    value describing whether containment changed between two already-known inside/outside
    readings."""

    ENTERED = "entered"
    EXITED = "exited"
    NONE = "none"
