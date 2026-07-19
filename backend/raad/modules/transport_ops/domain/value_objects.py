"""Transport Operations value objects (Backend LLD §5.1; Database Design §6.2/§6.3). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`), the project's existing domain-invariant exception.

Phase 10.1 scope: `Student` only (confirmed with the user before implementing — see
`entities.py`'s module docstring for the full scope note). `StudentId` is minted and owned by
*this* module (`students` is this module's own table, Database Design §6.2), so the strict
ULID shape is validated, the same way `organization.domain.value_objects.OrganizationId`
validates its own primary key. `OrganizationId` here is a cross-module reference to the
`organization` module's aggregate — opaque, non-empty string only, never re-validating another
module's id format (`.claude/rules/database.md` #3), mirroring `tracking.domain.value_objects.
OrganizationId` exactly.

**Phase 10.6 addition: `Parent`.** `ParentId` is minted and owned by this module (`parents` is
this module's own table, Database Design §6.3) — strict ULID shape, same treatment as
`StudentId`. `UserId` here is a **cross-module reference** to the `iam` module's `User`
aggregate (Database Design §6.3: "`user_id FK→users`") — despite the doc's "FK" shorthand,
`users` is owned by `iam`, not this module, so per `.claude/rules/database.md` #3 this is
validated only as an opaque non-empty string, never re-validating `iam`'s own ULID format,
exactly mirroring this file's own `OrganizationId` treatment (and never DB-FK-constrained at
the infra layer — see `infra/models.py`'s Phase 10.6 addition). A local `UserId`/`PhoneNumber`
are declared here rather than imported from `iam.domain.value_objects`, since
`.claude/rules/backend.md` #1 forbids one module importing another's private `domain` package
— the same reasoning `_AggregateRoot`'s per-module duplication already establishes in this
codebase. `PhoneNumber` mirrors `iam.domain.value_objects.PhoneNumber`'s E.164 validation
exactly, for the same reason.

**Phase 10.8 addition: `Driver`.** `DriverId` is minted and owned by this module (`drivers` is
this module's own table, Database Design §6.1, ADR-0001) — strict ULID shape, same treatment as
`StudentId`/`ParentId`. No new `UserId`/`OrganizationId` declaration is needed — `Driver.user_id`
reuses the same cross-module-reference `UserId` already declared for `Parent` above (Database
Design §6.1: "`user_id FK→users`", the identical "FK" shorthand for an `iam`-owned table).
`DriverStatus` mirrors `ParentStatus`'s exact reasoning below — see its own docstring.

**Phase 11 addition: `Route`/`Stop`.** `RouteId`/`StopId` are minted and owned by this module
(`routes`/`stops` are this module's own tables, Database Design §6.5/§6.6) — strict ULID shape,
same treatment as every other module-owned id above. `RouteStatus` is, unlike `ParentStatus`/
`DriverStatus`, **actually documented**: Database Design §6.5 spells out
`routes.status ENUM(active,inactive)` explicitly — not a guessed flat toggle this time, though
the two enums happen to end up the same shape. No "archived" value is documented anywhere
(§6.5's enum is exhaustively two values) — flagged in `entities.py`'s module docstring rather
than invented, since the task scope for this phase explicitly says "Archive (if specified)".

**Phase 12 addition: `Trip`.** `TripId` is minted and owned by this module (`trips` is this
module's own table, Database Design §6.8, ADR-0001) — strict ULID shape, same treatment as
`RouteId`/`DriverId`. `TripStatus` is, like `RouteStatus`, **actually documented**: Database
Design §6.8 spells out `ENUM(scheduled,in_progress,interrupted,completed)` explicitly, and
Phase-2 §6.2's state diagram confirms the exact same four values with the exact transition
graph enforced in `entities.py`'s `Trip` behavior methods — not a guessed flat toggle. `TripType`
is likewise documented (`ENUM(morning,afternoon)`, §6.8, "Ch. 7.9 independent"). `VehicleId` is
a **cross-module reference** to the `fleet_device` module's `Vehicle` aggregate — confirmed with
the user before implementing: `transport_ops` cannot perform a cross-module DB read
(`.claude/rules/backend.md` #3), and the only cross-module-coordination design in this codebase,
ADR-0003, is still "Proposed, not accepted" and covers a write workflow, not a read/validation.
Mirrors `OrganizationId`/`UserId`'s identical treatment above exactly: opaque, non-empty string
only, no existence check anywhere in this module — the same trust level already given to
`Parent.user_id`/`Driver.user_id` for their own cross-module references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# Database Design §6.3 gives `parents` in compact notation with no explicit VARCHAR lengths —
# unlike §6.2's fully-spelled-out `students` table. `full_name`/`phone` reuse the lengths
# already established for the identically-named columns elsewhere in this schema
# (`users.full_name VARCHAR(200)`, `users.phone VARCHAR(32)`, `iam/infra/models.py`) rather
# than inventing new numbers — the same column name, the same convention, not a guess.
_PHONE_MAX_LENGTH = 32
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


@dataclass(frozen=True)
class StudentId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"StudentId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """Cross-module reference to an `Organization` aggregate owned by the `organization`
    module — opaque, non-empty string only, mirroring `tracking.domain.value_objects.
    OrganizationId` exactly (`.claude/rules/database.md` #3)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


class StudentStatus(str, Enum):
    """Database Design §6.2: `students.status ENUM(active,disabled,graduated,transferred)`.
    **CR-1**: non-active statuses revoke parent access via the student's assignment
    (`student_assignments`, a separate aggregate — deliberately out of this phase's scope, see
    `entities.py`'s module docstring).

    No transition diagram is documented for this enum anywhere in the approved documentation
    (unlike `Device`'s Phase 2 §19.2 diagram or `Trip`'s Phase 2 §6.2 machine) — flagged, not
    guessed. `Student`'s behavior methods (`entities.py`) therefore treat every value as
    directly settable with an idempotent same-state no-op, the exact precedent `organization.
    domain.entities.Organization.suspend/reactivate/deactivate` already establishes for an
    equally undocumented transition set."""

    ACTIVE = "active"
    DISABLED = "disabled"
    GRADUATED = "graduated"
    TRANSFERRED = "transferred"


@dataclass(frozen=True)
class ParentId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"ParentId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserId:
    """Cross-module reference to a `User` aggregate owned by `iam` — opaque, non-empty string
    only, mirroring this file's own `OrganizationId` treatment exactly
    (`.claude/rules/database.md` #3). Not `iam.domain.value_objects.UserId` — see module
    docstring for why this module declares its own rather than importing `iam`'s."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PhoneNumber:
    """E.164 format, mirroring `iam.domain.value_objects.PhoneNumber` exactly — see module
    docstring for why this module declares its own rather than importing `iam`'s."""

    value: str

    def __post_init__(self) -> None:
        if not _E164_PATTERN.match(self.value):
            raise DomainError(f"Phone number must be E.164 format: {self.value!r}")
        if len(self.value) > _PHONE_MAX_LENGTH:
            raise DomainError(
                f"Phone number must be at most {_PHONE_MAX_LENGTH} characters: "
                f"{self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


class ParentStatus(str, Enum):
    """Database Design §6.3 gives `parents.status` with no enumerated values at all (unlike
    §6.2's fully-spelled-out `students.status ENUM(...)`) — flagged, not guessed. The simplest
    defensible choice, mirroring `organization.domain.value_objects.RegionStatus`'s identical
    situation (an entity with no documented richer lifecycle): a flat active/inactive toggle,
    not an invented richer state machine. `Parent`'s own login/account lifecycle (invited/
    active/disabled) lives entirely on the linked `iam.User` row (Database Design §6.3:
    "Login is via the linked `users` row") — this status is `transport_ops`'s own, separate
    concept (e.g. an Org Admin enabling/disabling a parent's transport-facing profile without
    touching their login credentials)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class DriverId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"DriverId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class DriverStatus(str, Enum):
    """Database Design §6.1 gives `drivers.status` with no enumerated values at all (unlike
    §6.2's fully-spelled-out `students.status ENUM(...)`) — flagged, not guessed, the identical
    situation `ParentStatus` above already documents for `parents.status`. Same simplest
    defensible choice: a flat active/inactive toggle, not an invented richer state machine.
    `Driver`'s own login/account lifecycle lives entirely on the linked `iam.User` row (Database
    Design §6.1: "Profile for users with `role=driver`") — this status is `transport_ops`'s own,
    separate concept (e.g. an Org Admin enabling/disabling a driver's transport-facing profile
    without touching their login credentials), mirroring `ParentStatus`'s identical reasoning.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class RouteId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"RouteId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StopId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"StopId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class RouteStatus(str, Enum):
    """Database Design §6.5: `routes.status ENUM(active,inactive)` — documented explicitly,
    unlike `ParentStatus`/`DriverStatus` above (both flat-toggle guesses for an undocumented
    enum). No third "archived" value exists in this enum; `Route`'s behavior methods
    (`entities.py`) therefore only ever set one of these two values."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class TripId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"TripId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class VehicleId:
    """Cross-module reference to a `Vehicle` aggregate owned by `fleet_device` — opaque,
    non-empty string only, mirroring this file's own `OrganizationId`/`UserId` treatment
    exactly (`.claude/rules/database.md` #3; see module docstring's Phase 12 addition)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("VehicleId must not be empty")

    def __str__(self) -> str:
        return self.value


class TripType(str, Enum):
    """Database Design §6.8: `trips.trip_type ENUM(morning,afternoon)` — "Ch. 7.9 independent"
    (morning and afternoon are separate `Trip` instances, not two phases of one trip, Phase-2
    §6.2's closing note)."""

    MORNING = "morning"
    AFTERNOON = "afternoon"


class TripStatus(str, Enum):
    """Database Design §6.8: `trips.status ENUM(scheduled,in_progress,interrupted,completed)`,
    matching Phase-2 §6.2's documented state diagram exactly:

        Scheduled -> InProgress (Driver starts trip)
        InProgress -> Completed (Driver ends trip)
        InProgress -> Interrupted (timeout / device offline / manual)
        Interrupted -> InProgress (resume)
        Interrupted -> Completed (force end)

    Unlike `ParentStatus`/`DriverStatus`, this is a fully documented enum **and** a documented
    transition graph — `Trip`'s behavior methods (`entities.py`) enforce the graph above exactly,
    raising `RuleViolationError` (not the flat idempotent-no-op convention `Student`/`Parent`/
    `Driver`/`Route` use for their own undocumented-transition enums) for any edge not drawn
    above."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
