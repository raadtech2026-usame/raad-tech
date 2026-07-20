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
    aggregate_id: str,
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
    matching every other unnamed-event precedent in this codebase."""
    return _new_event(
        event_type="RolePermissionGranted",
        aggregate_type="RolePermission",
        aggregate_id=f"{role}:{permission}",
        org_id=None,
        occurred_at=occurred_at,
        payload={"role": role, "permission": permission, "actor_id": actor_id},
    )


def role_permission_revoked(
    *, role: str, permission: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="RolePermissionRevoked",
        aggregate_type="RolePermission",
        aggregate_id=f"{role}:{permission}",
        org_id=None,
        occurred_at=occurred_at,
        payload={"role": role, "permission": permission, "actor_id": actor_id},
    )
