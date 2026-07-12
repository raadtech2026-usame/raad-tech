"""Organization value objects (Backend LLD §5.1; Database Design §4.1/§4.2). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`), the project's existing domain-invariant exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
# Unlike `iam`'s `OrganizationId` (a cross-module *reference* validated only as a non-empty
# opaque string), `OrganizationId`/`RegionId` here are minted and owned by *this* module
# (`organizations`/`regions` are this module's own tables), so the strict ULID shape is
# validated the same way `iam.domain.value_objects.UserId` validates its own primary key.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class OrganizationId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(
                f"OrganizationId must be a 26-character ULID: {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RegionId:
    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"RegionId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class OrgType(str, Enum):
    """Database Design §4.2: `org_type ENUM(school,…)` — **D3**: only `school` is an active
    value; the enum is a documented seam for future variants, not a set this module invents
    values for ahead of an approved extension."""

    SCHOOL = "school"


class BillingModel(str, Enum):
    """Database Design §4.2: `billing_model ENUM(organization_pays,parent_pays)` — **CR-1**
    input (`SubscriptionAccessPolicy`, owned by `billing`, consumes this value; this module
    only stores it)."""

    ORGANIZATION_PAYS = "organization_pays"
    PARENT_PAYS = "parent_pays"


class OrganizationStatus(str, Enum):
    """Database Design §4.2: `status ENUM(active,suspended,inactive)`."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class RegionStatus(str, Enum):
    """Database Design §4.1: `status ENUM(active,inactive)`."""

    ACTIVE = "active"
    INACTIVE = "inactive"
