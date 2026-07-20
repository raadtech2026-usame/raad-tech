"""Reporting entities (Backend LLD §5.1/§5.2; Database Design §8.6). Framework-free — no
SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state, enforce invariants, and
buffer the resulting `DomainEvent`s, matching every other module's exact shape (`Clock` passed
in, never called internally).

**One aggregate this phase: `ReportRun`** — matching the task's own scope, which names only
"ReportRun aggregate." `ReportDefinition` is **not built** — see `value_objects.py`'s module
docstring for the full gap (no `report_definitions` table in Database Design, no document
formalizing it beyond prose/conceptual mentions).

**`ReportRun`'s status transitions are not a guarded state machine — flagged, not invented.**
No document draws a state diagram for `report_runs.status` the way Phase-2 §6.2 does for `Trip`;
the ENUM's own listed order (`queued,running,succeeded,failed`, §8.6) is read as the natural
progression, but illegal-transition checking (`RuleViolationError`) is not implemented, mirroring
`billing.domain.entities.Payment`'s identical "no document describes this as a *guarded* state
machine" precedent — not `Trip`'s guarded one.

**Actual report rendering (PDF/Excel generation) is entirely out of this phase's scope** (task's
own Out of Scope list). `ReportRun.request()` persists a `QUEUED` row only — the "render, store
artifact, notify requester" half of the documented Report Worker's responsibility (Backend LLD
§11.2) belongs to a not-yet-built worker, mirroring `Payment.initiate()`/`Notification.create()`'s
identical "persist only, defer the real work to an unbuilt consumer" precedent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.reporting.domain import events as reporting_events
from raad.modules.reporting.domain.value_objects import (
    OrganizationId,
    ReportId,
    ReportStatus,
    ReportType,
    UserId,
)


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), duplicated per module
    deliberately — `.claude/rules/backend.md` #1 forbids one module reaching into another's
    internals, and no approved doc calls for a shared-kernel package (identical to every other
    module's own `_AggregateRoot` copy)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class ReportRun(_AggregateRoot):
    """`report_runs` (Database Design §8.6): one requested/rendered report artifact. No
    `+audit` line in §8.6 (its own `created_at`/`completed_at` pair already serves the purpose)
    — mirrors `Payment`'s identical `UlidPrimaryKeyMixin`-only ORM treatment.
    """

    def __init__(
        self,
        *,
        id: ReportId,
        organization_id: OrganizationId,
        type: ReportType,
        params: dict[str, Any] | None,
        status: ReportStatus,
        artifact_url: str | None,
        requested_by: UserId,
        created_at: datetime,
        completed_at: datetime | None,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.type = type
        self.params = params
        self.status = status
        self.artifact_url = artifact_url
        self.requested_by = requested_by
        self.created_at = created_at
        self.completed_at = completed_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ReportRun) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def request(
        cls,
        *,
        id: ReportId,
        organization_id: OrganizationId,
        type: ReportType,
        params: dict[str, Any] | None,
        requested_by: UserId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "ReportRun":
        """Backs `POST /reports/runs` (API Contracts §4.8: "async render → report_run"). Starts
        `QUEUED` — the ENUM's own first-listed value (§8.6), the same "no richer starting-state
        document exists, use the enum's own least-committal value" reasoning `Subscription.open`
        already establishes for `SubscriptionStatus.TRIAL`. `ReportRequested` has no approved
        document naming it — this phase's own flagged choice."""
        now = clock.now()
        report_run = cls(
            id=id,
            organization_id=organization_id,
            type=type,
            params=params,
            status=ReportStatus.QUEUED,
            artifact_url=None,
            requested_by=requested_by,
            created_at=now,
            completed_at=None,
        )
        report_run._record(
            reporting_events.report_requested(
                report_run_id=str(id),
                organization_id=str(organization_id),
                type=type.value,
                requested_by=str(requested_by),
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return report_run

    def start(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`QUEUED -> RUNNING`. No approved HTTP route — the future Report Worker's own entry
        point (`application/commands.py`'s own docstring). Idempotent same-state no-op,
        mirroring every other status-transition method in this codebase; no illegal-transition
        checking either — see this file's module docstring."""
        if self.status == ReportStatus.RUNNING:
            return
        self.status = ReportStatus.RUNNING
        self._record(
            reporting_events.report_started(
                report_run_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def succeed(
        self, *, artifact_url: str, clock: Clock, actor_id: str | None = None
    ) -> None:
        """`RUNNING -> SUCCEEDED`, sets `artifact_url`/`completed_at` (§8.6's documented pair).
        No approved HTTP route — the future Report Worker's own entry point once rendering
        (explicitly out of this phase's scope) actually exists."""
        self.status = ReportStatus.SUCCEEDED
        self.artifact_url = artifact_url
        self.completed_at = clock.now()
        self._record(
            reporting_events.report_succeeded(
                report_run_id=str(self.id),
                organization_id=str(self.organization_id),
                artifact_url=artifact_url,
                occurred_at=self.completed_at,
                actor_id=actor_id,
            )
        )

    def fail(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`RUNNING -> FAILED`, sets `completed_at`. No approved HTTP route."""
        self.status = ReportStatus.FAILED
        self.completed_at = clock.now()
        self._record(
            reporting_events.report_failed(
                report_run_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=self.completed_at,
                actor_id=actor_id,
            )
        )
