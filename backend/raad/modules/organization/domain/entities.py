"""Organization aggregate roots (Backend LLD §5.1/§5.2; Database Design §4.1/§4.2).
Framework-free — no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state,
enforce invariants, and buffer the resulting `DomainEvent`s, matching the same shape as
`modules.iam.domain.entities` (`Clock` passed in, never called internally, so behavior stays
deterministic and unit-testable with a fake clock).

Scope note: only `Organization` and `Region` are implemented as rich entities here (Database
Design §4.2/§4.1). `OrgSettings` (§4.7) remains deliberately deferred — documented only in prose
(no column table, unlike every other table in this section), and one of its own examples
("parent-video-enabled=false by default — D5") would conflict with `.claude/rules/jt1078.md` #1
("not a configurable setting") if taken literally, so it needs an explicit design decision
before implementation, not an invented one here. `region_assignments`/`support_assignments`
(§4.6) were never going to be rich entities either way — `ScopeAssignmentRepository`'s own
docstring calls them "pure grant/revoke reference data, no aggregate lifecycle," the same shape
`iam`'s `role_permissions` already has — but their *module ownership* (not settled by the API
contract rule, which only routes `/organizations` + `/regions` here) was the real open question;
resolved as `organization`'s own (Priority 1 Item 6, `PROJECT_STATUS.md`) — see
`api/routers.py`'s `scope_assignments_router`.

**`latitude`/`longitude`/`geofence_radius_m` (added post-hoc, ADR-0014).** Phase 2 §22.1 names
an "organization geofence" for `VehicleArrivedAtOrganization` evaluation, but the originally
approved Database Design §4.2 gives `organizations` no geographic location at all — this gap
was found while implementing the post-F7 roadmap's item A5 (live geofence evaluation) and
confirmed with the user before adding columns; see ADR-0014 for the full record. All three
fields are optional (an organization that hasn't configured its location yet simply has no
organization-geofence evaluation performed for it — `tracking`'s evaluator treats this as "not
configured," never a zero-island fallback) and are set together or not at all via
`set_geofence`, never at `register()` time — no approved document gives this a creation-time
field, and requiring an Org Admin to know exact coordinates at registration would be a UX
regression on an already-approved flow. **No approved HTTP route exists yet** for `set_geofence`
— reachable at the application layer only, the same posture
`ScopeAssignmentApplicationService`'s grant/revoke methods already establish.

**`approaching_distance_m` (ADR-0014 amendment).** Replaces the temporary
`_APPROACH_RADIUS_MULTIPLIER` stand-in `tracking/events/subscribers.py` previously used
(`stop.geofence_radius_m * 3`) with a real, organization-level configurable value: how far (in
meters) from a stop's own center `APPROACHING_STOP` fires, independent of that stop's arrival
radius. Unlike the geofence trio above, this is **never `None`** — every organization has some
approaching distance, defaulting to `_DEFAULT_APPROACHING_DISTANCE_M` (300m, the user's own
chosen default) at `register()` time, changed only via `set_approaching_distance_m`. Deliberately
its own setter/event rather than folded into `set_geofence` — this value governs *stop*-approach
evaluation (route-scoped), completely orthogonal to the organization's own arrival geofence
(location-scoped); the two happen to share a table for the same reason `org_settings` was never
built as a separate one (Database Design §4.7, deferred). **Designed for a future per-stop
override**: this is the org-level *default* a stop's own evaluation falls back to — a later
phase could add a nullable `stops.approaching_distance_m` that takes precedence when set, with no
change needed to this method's own shape, only to the resolution point in
`tracking/events/subscribers.py`. **No approved HTTP route exists yet** — same posture as
`set_geofence`.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.organization.domain import events as org_events
from raad.modules.organization.domain.value_objects import (
    OrgType,
    OrganizationId,
    OrganizationStatus,
    RegionId,
    RegionStatus,
)

_MIN_LATITUDE = -90.0
_MAX_LATITUDE = 90.0
_MIN_LONGITUDE = -180.0
_MAX_LONGITUDE = 180.0

# ADR-0014 amendment: the org-level default for "approaching stop" evaluation, replacing the
# previously-hardcoded _APPROACH_RADIUS_MULTIPLIER (tracking/events/subscribers.py) - the user's
# own chosen default, not invented here.
_DEFAULT_APPROACHING_DISTANCE_M = 300


def _validate_approaching_distance(value: int) -> None:
    if value <= 0:
        raise DomainError(
            f"Organization approaching_distance_m must be positive: {value}"
        )


def _validate_geofence(
    *, latitude: float | None, longitude: float | None, radius_m: int | None
) -> None:
    """All three fields are set together or not at all — a geofence with a center but no
    radius (or vice versa) could never be evaluated, so a partial configuration is rejected
    rather than silently half-accepted."""
    values = (latitude, longitude, radius_m)
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise DomainError(
            "Organization geofence latitude/longitude/geofence_radius_m must be set "
            "together, or not at all."
        )
    if not (_MIN_LATITUDE <= latitude <= _MAX_LATITUDE):
        raise DomainError(
            f"Organization latitude must be between {_MIN_LATITUDE} and {_MAX_LATITUDE}: "
            f"{latitude}"
        )
    if not (_MIN_LONGITUDE <= longitude <= _MAX_LONGITUDE):
        raise DomainError(
            f"Organization longitude must be between {_MIN_LONGITUDE} and "
            f"{_MAX_LONGITUDE}: {longitude}"
        )
    if radius_m <= 0:
        raise DomainError(f"Organization geofence_radius_m must be positive: {radius_m}")


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), identical to
    `iam.domain.entities._AggregateRoot`. Not shared as a common base module between the two
    yet — `.claude/rules/backend.md` #1 forbids one module reaching into another's internals,
    and this is a small enough mechanism that duplicating it is cheaper than inventing a
    shared-kernel package neither approved doc calls for."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class Organization(_AggregateRoot):
    """Tenant root (Database Design §4.2; Phase 2 §10.2/§18). `parent_org_id` supports the
    operator → sub-organization/campus hierarchy (§18.2); the isolation boundary is the top of
    that hierarchy, not this aggregate's concern to enforce (that's a repository/authorization
    concern per §2's cross-cutting tenancy note).

    Deliberately no `change_region`/`reparent` behavior: neither the Database Design nor Phase 2
    §18 document a rule for changing these post-creation, so they stay constructor-set only
    rather than inventing an unstated transition. **ADR-0016 (RAAD business model realignment)
    removed `billing_model` entirely** — it was never a `change_*` candidate to begin with,
    listed here only for the pattern; see `domain/value_objects.py`'s own docstring for why the
    field itself is gone.
    """

    def __init__(
        self,
        *,
        id: OrganizationId,
        name: str,
        org_type: OrgType,
        parent_org_id: OrganizationId | None,
        region_id: RegionId,
        status: OrganizationStatus,
        created_at: datetime,
        updated_at: datetime,
        latitude: float | None = None,
        longitude: float | None = None,
        geofence_radius_m: int | None = None,
        approaching_distance_m: int = _DEFAULT_APPROACHING_DISTANCE_M,
    ) -> None:
        super().__init__()
        if not name:
            raise DomainError("Organization name must not be empty")
        _validate_geofence(
            latitude=latitude, longitude=longitude, radius_m=geofence_radius_m
        )
        _validate_approaching_distance(approaching_distance_m)
        self.id = id
        self.name = name
        self.org_type = org_type
        self.parent_org_id = parent_org_id
        self.region_id = region_id
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.latitude = latitude
        self.longitude = longitude
        self.geofence_radius_m = geofence_radius_m
        self.approaching_distance_m = approaching_distance_m

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Organization) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def register(
        cls,
        *,
        id: OrganizationId,
        name: str,
        org_type: OrgType,
        region_id: RegionId,
        parent_org_id: OrganizationId | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Organization":
        """Factory for a newly-registered organization. No `invited`/pending status exists in
        the approved enum (Database Design §4.2: `active,suspended,inactive` only), so a
        registered organization starts `active` — unlike `iam.User.invite`, there is no
        intermediate state to model."""
        now = clock.now()
        organization = cls(
            id=id,
            name=name,
            org_type=org_type,
            parent_org_id=parent_org_id,
            region_id=region_id,
            status=OrganizationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        organization._record(
            org_events.organization_registered(
                organization_id=str(id),
                name=name,
                org_type=org_type.value,
                parent_org_id=str(parent_org_id) if parent_org_id else None,
                region_id=str(region_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return organization

    def suspend(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == OrganizationStatus.SUSPENDED:
            return
        self.status = OrganizationStatus.SUSPENDED
        self.updated_at = clock.now()
        self._record(
            org_events.organization_suspended(
                organization_id=str(self.id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def reactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == OrganizationStatus.ACTIVE:
            return
        self.status = OrganizationStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            org_events.organization_reactivated(
                organization_id=str(self.id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def deactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == OrganizationStatus.INACTIVE:
            return
        self.status = OrganizationStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            org_events.organization_deactivated(
                organization_id=str(self.id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def set_geofence(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Configures this organization's geofence center + radius (ADR-0014) — see module
        docstring for why this exists post-hoc and is set-together-or-not-at-all."""
        _validate_geofence(latitude=latitude, longitude=longitude, radius_m=radius_m)
        self.latitude = latitude
        self.longitude = longitude
        self.geofence_radius_m = radius_m
        self.updated_at = clock.now()
        self._record(
            org_events.organization_geofence_updated(
                organization_id=str(self.id),
                latitude=latitude,
                longitude=longitude,
                radius_m=radius_m,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def set_approaching_distance_m(
        self,
        *,
        approaching_distance_m: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Configures this organization's stop-approaching distance (ADR-0014 amendment) —
        see module docstring for why this is a distinct setter/event from `set_geofence`."""
        _validate_approaching_distance(approaching_distance_m)
        self.approaching_distance_m = approaching_distance_m
        self.updated_at = clock.now()
        self._record(
            org_events.organization_approaching_distance_updated(
                organization_id=str(self.id),
                approaching_distance_m=approaching_distance_m,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Region(_AggregateRoot):
    """RAAD-internal region scoping (Database Design §4.1; Phase 2 §17.3): "`Region` is a
    first-class entity... every customer `Organization` belongs to exactly one region.
    """

    def __init__(
        self,
        *,
        id: RegionId,
        name: str,
        geographic_scope: str | None,
        status: RegionStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if not name:
            raise DomainError("Region name must not be empty")
        self.id = id
        self.name = name
        self.geographic_scope = geographic_scope
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Region) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: RegionId,
        name: str,
        geographic_scope: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Region":
        now = clock.now()
        region = cls(
            id=id,
            name=name,
            geographic_scope=geographic_scope,
            status=RegionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        region._record(
            org_events.region_created(
                region_id=str(id),
                name=name,
                geographic_scope=geographic_scope,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return region

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == RegionStatus.ACTIVE:
            return
        self.status = RegionStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            org_events.region_activated(
                region_id=str(self.id), occurred_at=clock.now(), actor_id=actor_id
            )
        )

    def deactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == RegionStatus.INACTIVE:
            return
        self.status = RegionStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            org_events.region_deactivated(
                region_id=str(self.id), occurred_at=clock.now(), actor_id=actor_id
            )
        )
