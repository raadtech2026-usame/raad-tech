"""Reporting value objects (Backend LLD §5.1; Database Design §8.6). Immutable, equality-by-
value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises `DomainError`
(`core.errors.exceptions`), mirroring every other module's identical convention.

**No LLD aggregate contract skeleton exists for `ReportRun`** (unlike `Trip`/`DeviceAssignment`)
— Backend LLD documents only the *Report Worker's* runtime behavior (§11.2: "Render PDF/Excel,
store artifact in object store, notify requester"), never a `ReportRun` domain-object shape.
Built here by structural analogy to `Payment`'s `UlidPrimaryKeyMixin`-only shape (a table with
no `+audit` line, Database Design §8.6).

**Cross-module references stay opaque, never re-validated** (`.claude/rules/database.md` #3):
`OrganizationId` (→ `organization.Organization`), `UserId` (→ `iam.User`, `report_runs.
requested_by`) — the same opaque, non-empty-string-only treatment every other module's own
cross-module VOs already establish.

**`ReportId` is a module-owned ULID VO** (Database Design §1/§20.2), same shape as every other
aggregate-owned id in this codebase.

**`ReportStatus`** — Database Design §8.6's `ENUM(queued,running,succeeded,failed)`, used
verbatim.

**`ReportType` is a genuinely under-specified field, flagged rather than guessed as a closed
enum.** The task's own scope names a `ReportType` value object, but Database Design §8.6 gives
the underlying column only as a bare `definition_key` — no `ENUM(...)` notation, unlike
`status` on the very same table row, which *does* get one. Two other documents gesture at a
richer catalog behind this field without ever formalizing it: Phase 2 Enterprise Architecture
§2/§10.1 names a `ReportDefinition` domain concept (a report *template*) alongside `ReportRun`,
and Project Brief §5.8 names two report categories in prose ("Student Transport Reports",
"Transport Payment Reports") — but **no `report_definitions` table exists anywhere in Database
Design** (the schema authority this task's own instructions say to follow exactly), no API route
manages report definitions, and neither prose category is ever given an exact wire-format string
value. Inventing a closed enum (e.g. guessing `"student_transport"` vs. `"student-transport"` vs.
`"STUDENT_TRANSPORT_REPORT"`) would be exactly the kind of undocumented behavior this phase's
instructions forbid. `ReportType` is therefore modeled as an opaque, non-empty, length-validated
string wrapping `definition_key` directly — the same treatment `billing.domain.entities.Payment.
provider` already gets for an analogous "documented as existing conceptually, no closed value
set given" field. The length (80) mirrors `audit_entries.action VARCHAR(80)`'s precedent for a
similarly-shaped "short label key" column, since §8.6 gives `definition_key` no explicit length
either — flagged, not presented as documented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_REPORT_TYPE_MAX_LENGTH = 80


@dataclass(frozen=True)
class ReportId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"ReportId must be a 26-character ULID: {self.value!r}")

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
    """Cross-module reference to an `iam.User` — opaque, non-empty string only. Names
    `report_runs.requested_by` (Database Design §8.6)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ReportType:
    """Opaque, non-empty wrapper over `report_runs.definition_key` — see module docstring for
    why this is not a closed enum."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("ReportType must not be empty")
        if len(self.value) > _REPORT_TYPE_MAX_LENGTH:
            raise DomainError(
                f"ReportType must be at most {_REPORT_TYPE_MAX_LENGTH} characters: "
                f"{len(self.value)}"
            )

    def __str__(self) -> str:
        return self.value


class ReportStatus(str, Enum):
    """Database Design §8.6 verbatim: `report_runs.status ENUM(queued,running,succeeded,
    failed)`."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
