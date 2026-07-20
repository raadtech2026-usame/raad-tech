"""ORM ↔ Domain mappers for `reporting` (Backend LLD §7.1 "aggregate-in/aggregate-out"; §17
`db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions. Mirrors `billing.infra.mappers`'s `existing=` in-place-update pattern exactly,
including reusing the `_to_naive_utc` fix (Phase 12's live-verification finding: `SystemClock`
returns tz-aware `datetime`s, but every `DateTime(timezone=False)` column needs naive ones) for
every timestamp field here that comes from `Clock.now()`.
"""

from __future__ import annotations

from datetime import datetime

from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.value_objects import (
    OrganizationId,
    ReportId,
    ReportStatus,
    ReportType,
    UserId,
)
from raad.modules.reporting.infra.models import ReportRunModel


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """See `transport_ops.infra.mappers._to_naive_utc`'s own docstring for the live-DB finding
    that motivated this — identical fix, duplicated per module for the same reason every other
    per-module convention in this codebase is duplicated rather than shared
    (`.claude/rules/backend.md` #1)."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def report_run_to_model(
    report_run: ReportRun, *, existing: ReportRunModel | None = None
) -> ReportRunModel:
    model = existing if existing is not None else ReportRunModel(id=str(report_run.id))
    model.organization_id = str(report_run.organization_id)
    model.definition_key = report_run.type.value
    model.params_json = report_run.params
    model.status = report_run.status.value
    model.artifact_url = report_run.artifact_url
    model.requested_by = str(report_run.requested_by)
    model.created_at = _to_naive_utc(report_run.created_at)
    model.completed_at = _to_naive_utc(report_run.completed_at)
    return model


def model_to_report_run(model: ReportRunModel) -> ReportRun:
    return ReportRun(
        id=ReportId(model.id),
        organization_id=OrganizationId(model.organization_id),
        type=ReportType(model.definition_key),
        params=model.params_json,
        status=ReportStatus(model.status),
        artifact_url=model.artifact_url,
        requested_by=UserId(model.requested_by),
        created_at=model.created_at,
        completed_at=model.completed_at,
    )
