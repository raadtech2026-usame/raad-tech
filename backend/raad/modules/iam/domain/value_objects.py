"""IAM value objects (Backend LLD §5.1; Database Design §4.3/§4.5). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises
`DomainError` (`core.errors.exceptions`) — the project's existing domain-invariant exception,
not a parallel one; `core/errors/exceptions.py` is pure stdlib (no framework import), so this
is an approved shared-kernel dependency, not an infra/HTTP one (its docstring: "raised by the
domain layer").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raad.core.errors.exceptions import DomainError

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

# Crockford Base32 (excludes I, L, O, U), 26 chars — Database Design §1: primary keys are
# ULID, `CHAR(26)`. Matches the alphabet `core.ids.generator.UlidGenerator` encodes with.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

_TOKEN_HASH_LENGTH = (
    64  # Database Design §4.5: `token_hash CHAR(64)` (a SHA-256 hex digest)
)
_HEX_PATTERN = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)


@dataclass(frozen=True)
class UserId:
    """Locally minted by this module (via `core.ids.UlidGenerator`) — format is validated
    against the approved ULID shape (Database Design §1), unlike `OrganizationId` below,
    which is a foreign reference this module doesn't own the format of."""

    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"UserId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RefreshTokenId:
    """Locally minted by this module — see `UserId`'s docstring for why ULID format is
    validated here but not on `OrganizationId`."""

    value: str

    def __post_init__(self) -> None:
        if not _ULID_PATTERN.match(self.value):
            raise DomainError(f"RefreshTokenId must be a 26-character ULID: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """A reference to an `Organization` aggregate owned by the `organization` module
    (Database Design §4.2) — this module never loads or mutates that aggregate, only stores
    its id, per "cross-context references are by ID only" (`.claude/rules/architecture.md` #3
    / `.claude/rules/database.md` #3). Deliberately validated as an opaque non-empty string,
    not a specific ID format/scheme — `iam` doesn't own how `organization` mints its ids."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise DomainError("OrganizationId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Email:
    """Normalized (trimmed, lower-cased) on construction so two differently-cased inputs for
    the same address compare equal — matters for the `users.email` global-uniqueness
    constraint (Database Design §4.3)."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _EMAIL_PATTERN.match(normalized):
            raise DomainError(f"Invalid email address: {self.value!r}")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PhoneNumber:
    """E.164 format (Database Design §4.3: "phone ... E.164")."""

    value: str

    def __post_init__(self) -> None:
        if not _E164_PATTERN.match(self.value):
            raise DomainError(f"Phone number must be E.164 format: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class UserStatus(str, Enum):
    """Database Design §4.3: `status ENUM(active,disabled,invited)`."""

    ACTIVE = "active"
    DISABLED = "disabled"
    INVITED = "invited"


def validate_token_hash(token_hash: str) -> None:
    """Shared guard used by `RefreshToken` (Database Design §4.5: `token_hash CHAR(64)`, a
    SHA-256 hex digest). A free function rather than its own value object — a bare `str` is
    what every call site (repositories, `core.security`) already passes; this only guards the
    invariant: exactly 64 characters, and hexadecimal only (rejects e.g. a same-length string
    in the wrong encoding)."""
    if len(token_hash) != _TOKEN_HASH_LENGTH:
        raise DomainError(f"token_hash must be exactly {_TOKEN_HASH_LENGTH} characters")
    if not _HEX_PATTERN.match(token_hash):
        raise DomainError("token_hash must contain only hexadecimal characters")
