"""Application-layer command validators (Backend LLD §4.1's application table: "Contextual
pre-conditions of a use-case" — e.g. "actor has permission"). These check pre-conditions that
need repository I/O, which is exactly why they're an application concern and not a domain one:
`modules/iam/domain/services.py` explains why global email/phone uniqueness isn't a domain
service (domain services are I/O-free operations over already-loaded entities; checking "does
another row already have this email" needs a repository query).

Permission/authorization pre-condition checks (the LLD's "actor has permission" example) are
not implemented here yet — the RBAC permission matrix is still pending approval
(`core.security.permissions.PermissionEvaluator`, Phase 4.3).
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.domain.value_objects import Email, PhoneNumber


async def ensure_email_available(uow: IamUnitOfWork, email: Email) -> None:
    existing = await uow.users.get_by_email(email)
    if existing is not None:
        raise ConflictError(f"A user with email {email} already exists.")


async def ensure_phone_available(uow: IamUnitOfWork, phone: PhoneNumber) -> None:
    existing = await uow.users.get_by_phone(phone)
    if existing is not None:
        raise ConflictError(f"A user with phone {phone} already exists.")
