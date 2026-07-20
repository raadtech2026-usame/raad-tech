"""Platform & Audit application commands (Backend LLD §4.2 "intent DTOs"). Immutable request
objects — every command carries the calling `Principal` as `actor`, mirroring
`billing.application.commands`'s exact shape.

**`SetSystemSettingCommand` backs `PATCH /admin/settings`** (API Contracts §4.8). No approved
document gives this route's exact request body shape — this command's fields (`key, value,
scope`) are the minimal, direct mirror of `system_settings`' own three documented columns
(Database Design §8.9), the same "flagged, minimal placeholder" posture
`billing.application.commands.PaymentCallbackCommand`'s own docstring already establishes for an
equally under-specified body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class SetSystemSettingCommand:
    key: str
    value: dict[str, Any]
    scope: str
    actor: Principal
