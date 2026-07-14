"""Tracking domain layer (Backend LLD §5; Database Design §7.1/§7.2; Phase 2 §22/§23) —
Phase 8.1 scope.

Framework-free: entities/value objects/events/repository interfaces/policies/services only.
No application services, no infra, no DI, no JT808 protocol handling — those are later phases
(this module never terminates a device socket, `.claude/rules/architecture.md` #2). Public
surface of this package.

Scope: `VehiclePosition` and `GeofenceCrossing` — exactly the two Database Design §7 tables
this module owns. Device connectivity (`Online`/`Offline`), `device_status_log`, and geofence
*configuration* are deliberately absent — see `entities.py`'s module docstring for why each is
out of scope. `TrackingVisibilityPolicy` (`policies.py`) encodes Phase 2 §23.3's capability ∧
scope ∧ ownership ∧ time-window predicate as the required single policy object
(`.claude/rules/security.md` #4); `GeofenceEvaluationService` (`services.py`) provides the
stateless "geofence crossing evaluation primitives" Backend LLD §5.1 names as a domain-service
example.
"""

from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.policies import TrackingVisibilityPolicy
from raad.modules.tracking.domain.repositories import (
    GeofenceCrossingRepository,
    VehiclePositionRepository,
)
from raad.modules.tracking.domain.services import GeofenceEvaluationService
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeofenceTransition,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)

__all__ = [
    "AlarmFlags",
    "DeviceId",
    "GeoPoint",
    "GeofenceCrossing",
    "GeofenceCrossingId",
    "GeofenceCrossingRepository",
    "GeofenceEvaluationService",
    "GeofenceEventType",
    "GeofenceTransition",
    "HeadingDegrees",
    "OrganizationId",
    "SpeedKph",
    "StopId",
    "TrackingVisibilityPolicy",
    "TripId",
    "VehicleId",
    "VehiclePosition",
    "VehiclePositionId",
    "VehiclePositionRepository",
]
