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


SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)
"""A real, flagged gap, not a silent invention — shared by every module that needs *a*
`Principal` for a non-human, worker- or webhook-triggered command (every application command in
this codebase requires `actor: Principal`, including ones with no real authenticated caller). No
approved document defines a system/worker actor concept, and `Role` has no `SYSTEM` value among
its seven documented roles (Project Brief Ch. 4) — adding an eighth role would touch the RBAC
seed matrix (ADR-0004), `ScopeResolver` (ADR-0005), and every policy that switches on `Role`, a
far larger change than any single caller of this constant needs. `Role.FOUNDER` is the closest
existing role conceptually (unrestricted scope, matching what a background process/verified
webhook needs), not a claim the caller "is" a Founder user; `audit_entries.actor_user_id` reads
the literal string `"system"` for these rows, distinguishable from any real user id.

Originally defined only in `modules/notifications/events/subscribers.py` (for the Notification
Worker's own CR-1-gated `Notification.create()` calls); moved here (ADR-0022) so `billing`'s
webhook-callback path can share the identical constant rather than an independently-drifting
second copy — both call sites are the same underlying gap, not two different ones."""
