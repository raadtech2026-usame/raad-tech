"""Organization aggregate roots (Backend LLD §5.1/§5.2; Database Design §4.1/§4.2).
Framework-free — no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state,
enforce invariants, and buffer the resulting `DomainEvent`s, matching the same shape as
`modules.iam.domain.entities` (`Clock` passed in, never called internally, so behavior stays
deterministic and unit-testable with a fake clock).

Scope note: only `Organization` and `Region` are implemented (Database Design §4.2/§4.1).
`OrgSettings` (§4.7) and `region_assignments`/`support_assignments` (§4.6) are deliberately
deferred — §4.7 is documented only in prose (no column table, unlike every other table in this
section) and one of its own examples ("parent-video-enabled=false by default — D5") would
conflict with `.claude/rules/jt1078.md` #1 ("not a configurable setting") if taken literally;
§4.6's module ownership isn't settled by the API contract rule (which routes only
`/organizations` + `/regions` to this module). Both need an explicit design decision before
implementation, not an invented one here.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.organization.domain import events as org_events
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrgType,
    OrganizationId,
    OrganizationStatus,
    RegionId,
    RegionStatus,
)


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

    Deliberately no `change_region`/`change_billing_model`/`reparent` behavior: neither the
    Database Design nor Phase 2 §18 document a rule for changing these post-creation, so they
    stay constructor-set only rather than inventing an unstated transition.
    """

    def __init__(
        self,
        *,
        id: OrganizationId,
        name: str,
        org_type: OrgType,
        parent_org_id: OrganizationId | None,
        region_id: RegionId,
        billing_model: BillingModel,
        status: OrganizationStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if not name:
            raise DomainError("Organization name must not be empty")
        self.id = id
        self.name = name
        self.org_type = org_type
        self.parent_org_id = parent_org_id
        self.region_id = region_id
        self.billing_model = billing_model
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

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
        billing_model: BillingModel,
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
            billing_model=billing_model,
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
                billing_model=billing_model.value,
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
