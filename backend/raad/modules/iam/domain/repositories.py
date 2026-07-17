"""Repository interfaces for the `iam` module (Backend LLD §5.1/§7.1/§7.2). Framework-free —
no SQLAlchemy/FastAPI/Pydantic.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`:
that module co-locates a SQLAlchemy-dependent concrete class (`SqlAlchemyRepositoryBase`) in
the same file, so importing anything from it — even just the interfaces — would make this
domain layer's import graph require SQLAlchemy to load at all, which is exactly what LLD §5.3
("the domain imports no framework, ORM, or I/O") forbids. These interfaces are declared fresh
instead, matching the same conceptual shape as the LLD §7.2 contract skeleton. The concrete
`infra/repositories.py` implementation (a later phase) is free to also satisfy
`core.db.repository.TenantScopedRepository` if useful — that's an infra-layer decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    PhoneNumber,
    RefreshTokenId,
    UserId,
)


class UserRepository(ABC):
    """Tenant scoping (Phase 2 §12.3/§17.4) applies here too — `organization_id=None` is only
    valid for RAAD-staff roles, and this repository's implementation is expected to enforce
    the same tenant/region scope as every other module's repository, not a shortcut version.
    """

    @abstractmethod
    async def get(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_email(self, email: Email) -> User | None:
        """Backs the global email-uniqueness constraint (Database Design §4.3)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_phone(self, phone: PhoneNumber) -> User | None:
        """Backs the global phone-uniqueness constraint (Database Design §4.3)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, user: User) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError


class RefreshTokenRepository(ABC):
    @abstractmethod
    async def get(self, token_id: RefreshTokenId) -> RefreshToken | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        """Lookup path for verifying a presented refresh token (Database Design §4.5:
        `token_hash CHAR(64)` unique)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, refresh_token: RefreshToken) -> None:
        raise NotImplementedError
