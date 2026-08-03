"""Domain events for the `iam` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`) — the existing abstraction, not a parallel one —
populated with `iam`-specific `event_type`/`aggregate_type`/`payload`.

Factories take primitive values (ids as `str`, roles as `str`), never the aggregate objects
themselves — events must be serializable (they land in `outbox.payload_json`, Database Design
§8.8) and this also avoids a circular import with `entities.py` (which calls these factories).
`generate_ulid` (`core.ids`) is a pure stdlib utility, not a framework/infra dependency, so
using it here doesn't violate the domain's "no framework, no I/O" rule (LLD §5.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str | None,
    org_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


def user_invited(
    *,
    user_id: str,
    organization_id: str | None,
    role: str,
    email: str | None,
    phone: str | None,
    full_name: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserInvited",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "role": role,
            "email": email,
            "phone": phone,
            "full_name": full_name,
            "actor_id": actor_id,
        },
    )


def user_activated(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserActivated",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def user_disabled(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserDisabled",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def user_logged_in(
    *, user_id: str, organization_id: str | None, occurred_at: datetime
) -> DomainEvent:
    return _new_event(
        event_type="UserLoggedIn",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={},
    )


def user_login_failed(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    failed_login_attempts: int,
    locked_until: datetime | None,
) -> DomainEvent:
    """Priority 1 Item 3 (PROJECT_STATUS.md, account lockout). Recorded for every failed
    attempt against a *known* account (an unknown identifier never reaches `User.
    record_failed_login` — there's no aggregate to record it on), audited via the same
    outbox/`audit_entries` path every other event already uses (ADR-0007). `locked_until` is
    `None` unless this specific failure just crossed the lockout threshold — lets a consumer
    distinguish "one more failed attempt" from "this account just got locked."""
    return _new_event(
        event_type="UserLoginFailed",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "failed_login_attempts": failed_login_attempts,
            "locked_until": locked_until.isoformat() if locked_until else None,
        },
    )


def user_password_changed(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserPasswordChanged",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def user_temporary_password_set(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0017/ADR-0003 Extension: a one-time hand-off credential was generated and set,
    requiring a forced change on next login — distinct from `UserPasswordChanged` (the user's
    own deliberate choice) since this is admin-initiated and leaves `is_password_change_
    required=True`. No approved document names this event; this phase's own flagged choice,
    matching every other unnamed-event precedent in this codebase."""
    return _new_event(
        event_type="UserTemporaryPasswordSet",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def user_mfa_enabled(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserMfaEnabled",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def user_mfa_disabled(
    *,
    user_id: str,
    organization_id: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="UserMfaDisabled",
        aggregate_type="User",
        aggregate_id=user_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def refresh_token_issued(
    *, token_id: str, user_id: str, expires_at: datetime, occurred_at: datetime
) -> DomainEvent:
    return _new_event(
        event_type="RefreshTokenIssued",
        aggregate_type="RefreshToken",
        aggregate_id=token_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"user_id": user_id, "expires_at": expires_at.isoformat()},
    )


def refresh_token_revoked(
    *, token_id: str, user_id: str, occurred_at: datetime
) -> DomainEvent:
    return _new_event(
        event_type="RefreshTokenRevoked",
        aggregate_type="RefreshToken",
        aggregate_id=token_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={"user_id": user_id},
    )


def role_permission_granted(
    *, role: str, permission: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    """RBAC/scope change (Database Design §10's audit-worthy action list names this category
    explicitly) — no approved document names this event; this phase's own flagged choice,
    matching every other unnamed-event precedent in this codebase.

    `aggregate_id=None` (Priority 1 Item 6, `PROJECT_STATUS.md`) — `RolePermission` has no real
    minted ULID (`RolePermissionRepository`'s own "pure grant data, no aggregate lifecycle"
    docstring); a composite `f"{role}:{permission}"` string was tried first and, live-verified
    against a real permission string, overflowed `audit_entries.entity_id`'s `CHAR(26)` column
    (`StringDataRightTruncationError`) — never caught earlier because no HTTP route reached this
    factory before this item. `role`/`permission` are still fully captured in `payload` below,
    so no identifying information is actually lost by omitting `aggregate_id`."""
    return _new_event(
        event_type="RolePermissionGranted",
        aggregate_type="RolePermission",
        aggregate_id=None,
        org_id=None,
        occurred_at=occurred_at,
        payload={"role": role, "permission": permission, "actor_id": actor_id},
    )


def role_permission_revoked(
    *, role: str, permission: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    """See `role_permission_granted`'s own docstring for why `aggregate_id=None`."""
    return _new_event(
        event_type="RolePermissionRevoked",
        aggregate_type="RolePermission",
        aggregate_id=None,
        org_id=None,
        occurred_at=occurred_at,
        payload={"role": role, "permission": permission, "actor_id": actor_id},
    )
