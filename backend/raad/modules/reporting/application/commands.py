"""Reporting application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects —
every command carries the calling `Principal` as `actor`, identifiers are plain `str`, mirroring
`billing.application.commands`'s exact shape.

**`RequestReportCommand` backs the one documented write route** (API Contracts §4.8:
`POST /reports/runs`, "async render → report_run"). `requested_by` is **not** a client-supplied
field — the service derives it from `command.actor.user_id`, the same pattern `Payment.
initiate`'s `actor_id` already establishes.

**`StartReportCommand`/`MarkReportSucceededCommand`/`MarkReportFailedCommand` have no approved
HTTP route** — no document names a status-transition endpoint for `report_runs` (API Contracts
§4.8 lists only the two rows above). These are the future Report Worker's own entry points once
rendering itself (explicitly out of this phase's scope) exists, the same "use-case exists, no
approved endpoint yet" posture `MarkPaymentExpiredCommand`/`CreateNotificationCommand` already
establish.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class RequestReportCommand:
    organization_id: str
    type: str
    params: dict[str, Any] | None
    actor: Principal


@dataclass(frozen=True)
class StartReportCommand:
    report_run_id: str
    actor: Principal


@dataclass(frozen=True)
class MarkReportSucceededCommand:
    report_run_id: str
    artifact_url: str
    actor: Principal


@dataclass(frozen=True)
class MarkReportFailedCommand:
    report_run_id: str
    actor: Principal
