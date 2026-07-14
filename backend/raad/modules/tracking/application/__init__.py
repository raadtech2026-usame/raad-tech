"""Tracking application layer (Backend LLD §4) — Phase 8.2 scope.

Orchestration only: creates/loads entities via repositories bound to `TrackingUnitOfWork`
(and reads the current position via `LatestPositionPort`), invokes domain behavior, records
the resulting `DomainEvent`s, commits, and returns a DTO. No FastAPI/SQLAlchemy
implementation, no infra, no business rules (those live in `modules/tracking/domain`). Public
surface of this package.
"""

from raad.modules.tracking.application.commands import (
    EvaluateGeofenceCommand,
    RecordBackfillPositionCommand,
    RecordGeofenceCrossingCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import (
    LatestPositionPort,
    TrackingUnitOfWork,
)
from raad.modules.tracking.application.queries import (
    GeofenceCrossingDTO,
    GeofenceEvaluationResultDTO,
    GetCurrentVehiclePositionQuery,
    GetGeofenceCrossingsQuery,
    GetVehiclePositionHistoryQuery,
    VehiclePositionDTO,
)
from raad.modules.tracking.application.services import TrackingApplicationService

__all__ = [
    "EvaluateGeofenceCommand",
    "GeofenceCrossingDTO",
    "GeofenceEvaluationResultDTO",
    "GetCurrentVehiclePositionQuery",
    "GetGeofenceCrossingsQuery",
    "GetVehiclePositionHistoryQuery",
    "LatestPositionPort",
    "RecordBackfillPositionCommand",
    "RecordGeofenceCrossingCommand",
    "RecordVehiclePositionCommand",
    "TrackingApplicationService",
    "TrackingUnitOfWork",
    "VehiclePositionDTO",
]
