"""Transport Operations value objects (Backend LLD §5.1; Database Design §6.2). Immutable,
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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


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
