"""Domain events for the `reporting` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`), populated with `reporting`-specific
`event_type`/`aggregate_type`/`payload`, mirroring every other module's identical `_new_event`
pattern.

**No approved document names any event this module produces.** Database Design §8.6 documents
the `report_runs` *table*; Backend LLD §11.2 documents the Report *Worker's* behavior (a
consumer of report requests, not a documented event producer); neither API Contracts §13.2's
event catalogue nor its notification catalogue (§13.3) mentions `report_runs` at all. All four
events below are this phase's own flagged choice — PascalCase past-tense, named 1:1 with each
aggregate's own domain method, the same "flagged, not silently assumed" posture every prior
phase's own unnamed events already carry (e.g. `PaymentInitiated`, `NotificationCreated`).
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


def report_requested(
    *,
    report_run_id: str,
    organization_id: str,
    type: str,
    requested_by: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ReportRequested",
        aggregate_type="ReportRun",
        aggregate_id=report_run_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"type": type, "requested_by": requested_by, "actor_id": actor_id},
    )


def report_started(
    *,
    report_run_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ReportStarted",
        aggregate_type="ReportRun",
        aggregate_id=report_run_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def report_succeeded(
    *,
    report_run_id: str,
    organization_id: str,
    artifact_url: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ReportSucceeded",
        aggregate_type="ReportRun",
        aggregate_id=report_run_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"artifact_url": artifact_url, "actor_id": actor_id},
    )


def report_failed(
    *,
    report_run_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="ReportFailed",
        aggregate_type="ReportRun",
        aggregate_id=report_run_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )
