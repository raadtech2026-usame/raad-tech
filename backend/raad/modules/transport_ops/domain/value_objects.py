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
