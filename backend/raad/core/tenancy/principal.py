"""The authenticated caller (Backend LLD §9.2, §18.2).

`Principal` is the outcome of JWT verification. This package defines the type only — JWT
verification itself lives in `core/security` (RBAC/JWT), which is not implemented in this
phase; the IAM module (`modules/iam`) owns issuing tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    """Roles from the Project Brief Ch. 4."""

    FOUNDER = "FOUNDER"
    REGIONAL_MANAGER = "REGIONAL_MANAGER"
    SUPPORT_STAFF = "SUPPORT_STAFF"
    FINANCE_STAFF = "FINANCE_STAFF"
    ORG_ADMIN = "ORG_ADMIN"
    DRIVER = "DRIVER"
    PARENT = "PARENT"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. `org_id` is the caller's own organization for tenant users
    (Org Admin, Driver, Parent); it is `None` for RAAD-staff roles, whose scope is resolved
    separately via `effective_org_scope` (Phase 2 §17.4) rather than a single org."""

    user_id: str
    role: Role
    org_id: str | None
