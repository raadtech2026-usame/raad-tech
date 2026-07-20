"""Notifications application commands (Backend LLD §4.2 "intent DTOs"). Immutable request
objects — every command carries the calling `Principal` as `actor`, identifiers are plain `str`,
mirroring `billing.application.commands`'s exact shape.

**`CreateNotificationCommand` has no approved HTTP route** — API Contracts §4.6 documents no
generic `POST /notifications`; it is the application-layer entry point the future Notification
Worker will call once event consumption/broker wiring exists (out of this phase's scope), the
same "use-case exists, no approved endpoint yet" posture `RenewParentSubscriptionCommand`
already establishes for `billing`.

**Every other command backs a documented route 1:1** (API Contracts §4.6): `MarkNotificationRead`
→ `POST /notifications/{id}/read`; `RegisterDeviceToken` → `POST /notifications/tokens`;
`RevokeDeviceToken` → `DELETE /notifications/tokens/{id}`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class CreateNotificationCommand:
    organization_id: str
    recipient_user_id: str
    type: str
    title: str
    body: str
    data: dict[str, Any] | None
    trip_id: str | None
    actor: Principal


@dataclass(frozen=True)
class MarkNotificationReadCommand:
    notification_id: str
    actor: Principal


@dataclass(frozen=True)
class RegisterDeviceTokenCommand:
    fcm_token: str
    platform: str
    actor: Principal


@dataclass(frozen=True)
class RevokeDeviceTokenCommand:
    device_token_id: str
    actor: Principal
