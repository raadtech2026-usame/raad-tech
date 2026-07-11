"""IAM value objects (Backend LLD §5.1; Database Design §4.3/§4.5). Immutable,
equality-by-value, framework-free — no SQLAlchemy/Pydantic/FastAPI. Validation raises plain
`ValueError`; there is no HTTP/error-envelope concept at this layer (`core/errors` is an
edge/application concern, not imported here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
_TOKEN_HASH_LENGTH = (
    64  # Database Design §4.5: `token_hash CHAR(64)` (a SHA-256 hex digest)
)


@dataclass(frozen=True)
class UserId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("UserId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RefreshTokenId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("RefreshTokenId must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class OrganizationId:
    """A reference to an `Organization` aggregate owned by the `organization` module
    (Database Design §4.2) — this module never loads or mutates that aggregate, only stores
    its id, per "cross-context references are by ID only" (`.claude/rules/architecture.md` #3
    / `.claude/rules/database.md` #3)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("OrganizationId must not be empty")

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
            raise ValueError(f"Invalid email address: {self.value!r}")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PhoneNumber:
    """E.164 format (Database Design §4.3: "phone ... E.164")."""

    value: str

    def __post_init__(self) -> None:
        if not _E164_PATTERN.match(self.value):
            raise ValueError(f"Phone number must be E.164 format: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class UserStatus(str, Enum):
    """Database Design §4.3: `status ENUM(active,disabled,invited)`."""

    ACTIVE = "active"
    DISABLED = "disabled"
    INVITED = "invited"


def validate_token_hash(token_hash: str) -> None:
    """Shared guard used by `RefreshToken` (Database Design §4.5: `token_hash CHAR(64)`).
    A free function rather than its own value object — a bare `str` is what every call site
    (repositories, `core.security`) already passes; this only guards the invariant."""
    if len(token_hash) != _TOKEN_HASH_LENGTH:
        raise ValueError(f"token_hash must be exactly {_TOKEN_HASH_LENGTH} characters")
